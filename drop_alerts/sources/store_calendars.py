"""Observed local store calendars; ticket/event data never means product stock."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
import re
import time
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from ..event_schedule import normalize_event_schedule
from ..models import ExtractionError, FetchResult, Item
from ..profiles import TCG_LABELS, infer_event_tcg, normalized_name
from .common import jsonld, official_url, soup_from, text


def _price(value, currency) -> dict:
    if not isinstance(currency, str) or not re.fullmatch(r"[A-Z]{3}", currency):
        return {}
    try:
        number = Decimal(str(value))
        if not number.is_finite() or not 0 <= number <= Decimal("1000000") or number.as_tuple().exponent < -4:
            return {}
        return {"entry_price": format(number, "f"), "entry_currency": currency, "entry_price_verified": True}
    except (ValueError, InvalidOperation):
        return {}


def _text_fee(value: str, labelled=False) -> dict:
    prefix = r"(?:entrada|inscripci[oó]n|precio|coste?)\s*(?:al torneo)?\s*[:\n]?\s*(?:[^\w\d\s]{0,3}\s*)?" if labelled else ""
    matches = list(re.finditer(prefix + r"(\d+(?:[.,]\d{1,2})?)\s*(?:€|euros?\b)", value, re.I))
    if not labelled and re.search(r"\b(?:desde|starts|from|variable|confirmar)\b", value, re.I):
        return {}
    prices = {match.group(1).replace(",", ".") for match in matches}
    return _price(next(iter(prices)), "EUR") if len(prices) == 1 else {}


def _offer(record) -> dict:
    offers = record.get("offers", {})
    if isinstance(offers, list):
        offers = offers[0] if len(offers) == 1 else {}
    return _price(offers.get("price"), offers.get("priceCurrency")) if isinstance(offers, dict) else {}


def _picture(data: dict, image, base: str):
    if isinstance(image, list):
        image = image[0] if image else None
    if isinstance(image, dict):
        image = image.get("url")
    try:
        if isinstance(image, str) and (url := official_url(base, image)):
            data.update(image_url=url, image_verified=True)
    except (ValueError, TypeError):
        pass


def _event(source, identity, title, url, content, game, start=None, end=None, venue_timezone="Europe/Madrid", **extra) -> Item:
    schedule = normalize_event_schedule(start, end, venue_timezone=venue_timezone)
    if start and not (schedule["start_at"] or schedule["start_date"]):
        raise ExtractionError("Fecha de evento inválida")
    proof = "\n".join("Fecha publicada: " + quote for quote in schedule["evidence"])
    content = (content[:11000] + "\n" + proof).strip()
    data = {"tcg": game, "region": "EU", "language": "es", "country": "ES", "channel": "event",
            "provenance": "retailer", "availability_verified": False, "summary": content[:1000],
            "evidence": [title[:300]], "event_schedule": schedule, **extra}
    return Item(identity, source, title, url, kind="event", state="SCHEDULED" if schedule["start_at"] or schedule["start_date"] else "ANNOUNCED",
                content=content, data=data)


def _select(source, items: list, http, limit: int):
    """Bounded new-item priority plus a persistent rotating historical window."""
    store = getattr(http, "store", None)
    cursor = getattr(source, "_cursor", 0)
    if store and hasattr(store, "get_meta"):
        try:
            cursor = int(store.get_meta("source_cursor:" + source.id, 0))
        except (ValueError, TypeError):
            cursor = 0
    known = {item.id for item in store.get_source_items(source.id)} if store and hasattr(store, "get_source_items") else getattr(source, "_known", set())
    cursor %= max(1, len(items))
    priority = [item for item in items if item.id not in known][:limit // 2]
    selected, priority_ids = [], {item.id for item in priority}
    traversed = 0
    for traversed, item in enumerate(items[cursor:] + items[:cursor], 1):
        if len(selected) >= limit - len(priority):
            traversed -= 1
            break
        if item.id not in priority_ids:
            selected.append(item)
    selected += priority
    source._cursor = (cursor + traversed) % max(1, len(items))
    source._known = known | {item.id for item in selected}
    if store and hasattr(store, "set_meta"):
        store.set_meta("source_cursor:" + source.id, source._cursor)
    return selected


@dataclass
class _Candidate:
    id: str
    title: str
    url: str
    hints: dict = field(default_factory=dict)


class _DetailsSource:
    async def fetch(self, http):
        deadline = time.monotonic() + self.max_duration_seconds
        async def get(url):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError
            return await asyncio.wait_for(http.get(url), remaining)
        try:
            candidates = self.parse_listing(await get(self.url))
        except TimeoutError:
            raise ExtractionError("Presupuesto de calendario agotado") from None
        selected = _select(self, candidates, http, min(self.max_items, self.max_details))
        accepted, errors, valid = [], [], 0
        for candidate in selected:
            try:
                item = self.parse_detail(await get(candidate.url), candidate)
                valid += 1
            except TimeoutError:
                errors.append("event:time_budget_exhausted")
                break
            except ExtractionError:
                errors.append("event:detail_failed")
                continue
            if item:
                accepted.append(item)
        if selected and not valid:
            raise ExtractionError("No se pudo confirmar ninguna ficha de evento")
        return FetchResult(accepted, not_modified=not accepted,
                           metadata={"method": "observed retailer HTML and JSON-LD", "errors": errors,
                                     "bootstrap_ids": [item.id for item in candidates]})


@dataclass
class GladiusEventsSource(_DetailsSource):
    id: str = "gladius_events"
    url: str = "https://gladiusgames.net/es/238-torneos-tcg"
    max_items: int = 30
    max_details: int = 8
    max_duration_seconds: float = 90

    def parse_listing(self, body: str):
        soup = soup_from(body)
        listing = next((value for value in jsonld(soup) if value.get("@type") == "ItemList"), None)
        if listing is None or not isinstance(listing.get("itemListElement"), list):
            raise ExtractionError("Gladius: listado de entradas no reconocido")
        found = {}
        for record in listing["itemListElement"][:500]:
            if not isinstance(record, dict):
                continue
            url = official_url(self.url, record.get("url", ""))
            match = re.fullmatch(r"/es/torneos-tcg/(\d+)-[^/]+\.html", urlsplit(url).path) if url else None
            name = text(record.get("name", ""))
            if match and name:
                found[match.group(1)] = _Candidate("product:" + match.group(1), name, url)
        if listing["itemListElement"] and not found:
            raise ExtractionError("Gladius: identidades de torneo no reconocidas")
        return list(found.values())

    def parse_detail(self, body: str, candidate: _Candidate):
        soup = soup_from(body)
        record = next((value for value in jsonld(soup) if value.get("@type") == "Product"), None)
        title = text(record.get("name", "")) if record else ""
        if not record or not title or not any(normalized_name(title) == normalized_name(node.get_text(" ", strip=True)) for node in soup.find_all("h1")):
            raise ExtractionError("Gladius: ficha de entrada incompleta")
        summary = text(record.get("description", ""))[:3500]
        game = infer_event_tcg(title) or infer_event_tcg(title + "\n" + summary)
        if not game:
            return None
        dates = re.findall(r"\b(\d{2})/(\d{2})/(20\d{2})\b", title)
        start = None
        if len(dates) == 1:
            day, month, year = dates[0]
            try:
                start = datetime(int(year), int(month), int(day)).date().isoformat()
            except ValueError:
                raise ExtractionError("Gladius: fecha de entrada inválida") from None
        content = title + "\n" + summary
        item = _event(self.id, candidate.id, title, candidate.url, content, game, start,
                      venue="Gladius Games", city="Alcalá de Henares",
                      address="Calle Cánovas del Castillo 5, 28807 Alcalá de Henares (Madrid)",
                      **_offer(record))
        _picture(item.data, record.get("image"), self.url)
        return item


@dataclass
class NextDiceEventsSource:
    id: str = "nextdice_events"
    url: str = "https://nextdice.es/eventos/"
    max_items: int = 80

    def parse(self, body: str):
        soup = soup_from(body)
        cards = soup.select("article.ndep-card")
        if not cards or len(cards) > 1000:
            raise ExtractionError("Next Dice: tarjetas de calendario no reconocidas")
        found, errors = {}, []
        for card in cards:
            heading = card.find("h2")
            anchor = heading.find("a", href=True) if heading else None
            url = official_url(self.url, anchor["href"]) if anchor else None
            if not url or not re.fullmatch(r"/evento/[^/]+/?", urlsplit(url).path):
                errors.append("event:identity_invalid")
                continue
            title = text(heading.get_text(" ", strip=True))
            category = card.select_one(".ndep-card__category")
            category = text(category.get_text(" ", strip=True)) if category else ""
            game = infer_event_tcg(title + "\n" + category)
            if not game:
                continue
            if not card.has_attr("data-start"):
                errors.append("event:date_structure_changed")
                continue
            start = card.get("data-start", "")
            excerpt = card.select_one(".ndep-card__excerpt")
            excerpt = text(excerpt.get_text(" ", strip=True)) if excerpt else ""
            footer = card.select_one(".ndep-card__footer strong")
            fee = text(footer.get_text(" ", strip=True)) if footer else ""
            content = "\n".join([title, "Categoría: " + category, excerpt, "Inscripción publicada: " + fee])
            try:
                item = _event(self.id, url, title, url, content, game, start,
                              venue="Next Dice", city="Algete",
                              address="Calle de Jorge Manrique S/N, Local 3-19, 28110 Algete (Madrid)",
                              **_text_fee(fee))
            except ExtractionError:
                errors.append("event:date_invalid")
                continue
            image = card.find("img", src=True)
            _picture(item.data, image.get("src") if image else None, self.url)
            found[url] = item
        if errors and not found and len(errors) == len(cards):
            raise ExtractionError("Next Dice: calendario incompleto")
        return list(found.values()), errors

    async def fetch(self, http):
        items, errors = self.parse(await http.get(self.url))
        # The current HTML contains an archive. Inspect newer published schedules
        # first without replacing dates from the source with the monitor's clock.
        items.sort(key=lambda item: item.data["event_schedule"].get("start_at") or item.data["event_schedule"].get("start_date") or "", reverse=True)
        selected = _select(self, items, http, self.max_items)
        return FetchResult(selected, not_modified=not selected,
                           metadata={"method": "Next Dice server-rendered event cards", "errors": errors,
                                     "bootstrap_ids": [item.id for item in items]})


def _ics_value(value: str) -> str:
    return re.sub(r"\\([nN,;\\])", lambda match: "\n" if match.group(1).lower() == "n" else match.group(1), value)


def _ics_datetime(value: str, parameters: str):
    if re.fullmatch(r"\d{8}", value):
        return datetime.strptime(value, "%Y%m%d").date().isoformat()
    if not re.fullmatch(r"\d{8}T\d{6}Z?", value):
        return None
    parsed = datetime.strptime(value.rstrip("Z"), "%Y%m%dT%H%M%S")
    if value.endswith("Z"):
        return parsed.isoformat() + "+00:00"
    match = re.search(r'(?:^|;)TZID=(?:"([^"]+)"|([^;]+))', parameters)
    if match:
        zone = ZoneInfo(match.group(1) or match.group(2))
        aware = parsed.replace(tzinfo=zone)
        if aware.utcoffset() != parsed.replace(tzinfo=zone, fold=1).utcoffset():
            return None
        if aware.astimezone(ZoneInfo("UTC")).astimezone(zone).replace(tzinfo=None) != parsed:
            return None
        return aware.isoformat()
    return parsed.isoformat()


@dataclass
class Arte9EventsSource:
    id: str = "arte9_events"
    url: str = "https://arte9.com/torneos/?ical=1"
    max_items: int = 80

    def parse(self, body: str):
        if "BEGIN:VCALENDAR" not in body or "END:VCALENDAR" not in body or len(body) > 2_000_000:
            raise ExtractionError("Arte9: calendario iCal no reconocido")
        lines = re.sub(r"\r?\n[ \t]", "", body).splitlines()
        records, current = [], None
        for line in lines:
            line = line.strip()
            if line == "BEGIN:VEVENT":
                if current is not None:
                    raise ExtractionError("Arte9: calendario anidado inválido")
                current = {}
            elif line == "END:VEVENT":
                if current is None:
                    raise ExtractionError("Arte9: calendario incompleto")
                records.append(current)
                current = None
            elif current is not None and ":" in line:
                key, value = line.split(":", 1)
                name, _, parameters = key.partition(";")
                current.setdefault(name.upper(), []).append((parameters, value))
        if current is not None or len(records) > 1000:
            raise ExtractionError("Arte9: calendario incompleto o demasiado grande")
        items, errors, identities = [], [], set()
        for record in records:
            def prop(name):
                return record.get(name, [("", "")])[0][1]
            uid, url = prop("UID"), official_url(self.url, _ics_value(prop("URL")))
            if not uid or not url or not re.fullmatch(r"/torneo/[^/]+/?", urlsplit(url).path):
                errors.append("event:identity_invalid")
                continue
            if any(key in record for key in ("RRULE", "RDATE", "EXDATE")):
                errors.append("event:recurrence_not_expanded")
                continue
            title, description, category = (_ics_value(prop(name)) for name in ("SUMMARY", "DESCRIPTION", "CATEGORIES"))
            game = infer_event_tcg(title + "\n" + category)
            if not game:
                continue
            derived_title = not title.strip()
            if derived_title:
                title = "Evento de " + TCG_LABELS.get(game, game) + " · Arte9"
            try:
                start = _ics_datetime(prop("DTSTART"), record.get("DTSTART", [("", "")])[0][0])
                end = _ics_datetime(prop("DTEND"), record.get("DTEND", [("", "")])[0][0]) if prop("DTEND") else None
                if prop("DTEND") and not end:
                    raise ValueError("Final inválido")
                if start and end and len(start) > 10 and len(end) > 10 and datetime.fromisoformat(end) < datetime.fromisoformat(start):
                    raise ValueError("Final anterior al comienzo")
            except (ValueError, TypeError, KeyError, OverflowError):
                errors.append("event:date_invalid")
                continue
            if not start:
                errors.append("event:date_invalid")
                continue
            if end == start:
                end = None  # The publisher often repeats the opening time as a default end.
            recurrence = prop("RECURRENCE-ID")
            # Arte9's UID embeds the timestamp; its WordPress post ID in the URL
            # is the stable identifier when the same event is rescheduled.
            identity = "event:" + urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1]
            if recurrence:
                identity += ":occurrence:" + recurrence
            if identity in identities:
                raise ExtractionError("Arte9: identidades de eventos duplicadas")
            identities.add(identity)
            content = title + "\nCategoría: " + category + "\n" + description[:9500]
            content += "\nDTSTART publicado: " + prop("DTSTART")
            location = _ics_value(prop("LOCATION"))
            if location:
                content += "\nLugar publicado: " + location
            item = _event(self.id, identity, title, url, content, game, start, end,
                          venue_timezone="Europe/Madrid" if "madrid" in location.casefold() else None,
                          venue=location.split(",", 1)[0] if location else "",
                          city="Madrid" if "madrid" in location.casefold() else "", address=location,
                          calendar_uid=uid, **_text_fee(description[:1000], labelled=True))
            if derived_title:
                item.data.update(title_derived=True, evidence=["Categoría: " + category, "DTSTART publicado: " + prop("DTSTART")])
            if prop("STATUS").upper() == "CANCELLED":
                item.state = "CANCELLED"
            _picture(item.data, prop("ATTACH"), self.url)
            items.append(item)
        if records and errors and not items and len(errors) == len(records):
            raise ExtractionError("Arte9: calendario sin eventos admitidos")
        return items, errors

    async def fetch(self, http):
        items, errors = self.parse(await http.get(self.url))
        selected = _select(self, items, http, self.max_items)
        return FetchResult(selected, not_modified=not selected,
                           metadata={"method": "published Arte9 iCal", "errors": errors,
                                     "bootstrap_ids": [item.id for item in items]})


@dataclass
class LudotecaEventsSource(_DetailsSource):
    id: str = "ludoteca_events"
    url: str = "https://ludotecamaldita.com/eventos/"
    max_items: int = 30
    max_details: int = 8
    max_duration_seconds: float = 90

    def parse_listing(self, body: str):
        soup = soup_from(body)
        cards = soup.select(".mep_list_event_details")
        if not cards:
            raise ExtractionError("Ludoteca Maldita: calendario no reconocido")
        found = {}
        for card in cards[:500]:
            heading, link = card.find("h2"), card.select_one("a.event_details_link[href]")
            url = official_url(self.url, link["href"]) if link else None
            title = text(heading.get_text(" ", strip=True)) if heading else ""
            if not title or not url or not re.fullmatch(r"/evento/[^/]+/?", urlsplit(url).path):
                continue
            button = card.find(attrs={"data-event-id": True})
            identity = "event:" + button["data-event-id"] if button and re.fullmatch(r"\d+", button["data-event-id"]) else url
            period = card.select_one(".upcomming_date_only_only")
            hints = {"period": text(period.get_text(" ", strip=True)) if period else ""}
            found[url] = _Candidate(identity, title, url, hints)
        if not found:
            raise ExtractionError("Ludoteca Maldita: identidades de evento no reconocidas")
        return list(found.values())

    def parse_detail(self, body: str, candidate: _Candidate):
        soup = soup_from(body)
        heading = soup.find("h1")
        title = text(heading.get_text(" ", strip=True)) if heading else ""
        record = next((value for value in jsonld(soup) if value.get("@type") == "Event" and normalized_name(text(value.get("name", ""))) == normalized_name(title)), None)
        if not title or not record:
            raise ExtractionError("Ludoteca Maldita: ficha de evento incompleta")
        game = infer_event_tcg(title)
        if not game:
            return None
        summary = text(record.get("description", ""))[:3500]
        location = record.get("location", {})
        address = location.get("address", {}) if isinstance(location, dict) else {}
        city = text(address.get("addressLocality", "")) if isinstance(address, dict) else ""
        street = text(address.get("streetAddress", "")) if isinstance(address, dict) else ""
        content = title + "\n" + summary
        period = candidate.hints.get("period", "")
        multiple = bool(re.search(r"\bo\s+(?:lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bado|domingo)\b", summary, re.I))
        if period:
            content += "\nPeríodo publicado: " + period
        item = _event(self.id, candidate.id, title, candidate.url, content, game,
                      None if multiple else record.get("startDate"), None if multiple else record.get("endDate"),
                      venue="Ludoteca Maldita", city=city or "Madrid", address=street or "Vicente Espinel 4 Local Derecho, Madrid",
                      **_offer(record))
        if multiple:
            item.data.update(event_period_text=period, multiple_sessions=True, needs_review=True,
                             schedule_note="La ficha publica varias sesiones; no se inventan ocurrencias ni una sesión continua.")
        if record.get("eventStatus") == "https://schema.org/EventCancelled":
            item.state = "CANCELLED"
        _picture(item.data, record.get("image"), self.url)
        return item
