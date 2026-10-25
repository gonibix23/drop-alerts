"""Public local tournament calendars from the user's shared research.

No login, recurrence extrapolation or store-stock inference is involved.
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit

from ..event_schedule import normalize_event_schedule
from ..models import ExtractionError, FetchResult, Item, fingerprint, safe_url
from ..profiles import infer_event_tcg
from ..release_dates import MONTHS
from .common import soup_from, text
from .local_store_catalog import NEARBY_STORES_EXTRA, MADRID_STORES_EXTRA

NEARBY_STORES = ("medusa-comics", "alcala-comics", "torrejugones", "hobbyshop-wargames") + NEARBY_STORES_EXTRA
MADRID_STORES = ("factory-cards", "tcg-box", "ludoteca-maldita", "tablerum", "kingdom-wargames", "jupiter-madrid-norte") + MADRID_STORES_EXTRA
REGISTRATION_HOSTS = {"www.bandai-tcg-plus.com", "bandai-tcg-plus.com", "localbatoru.com", "locator.wizards.com", "events.pokemon.com", "play.pokemon.com", "www.play.pokemon.com"}


def event_records(soup):
    """Walk only observed JSON-LD Event/ItemList/@graph containers, never JS."""
    records, recognized = [], False
    def walk(value, depth=0):
        nonlocal recognized
        if depth > 20 or len(records) > 1000:
            raise ExtractionError("Calendario demasiado grande o anidado")
        if isinstance(value, list):
            for entry in value:
                walk(entry, depth + 1)
        elif isinstance(value, dict):
            if value.get("@type") == "Event":
                records.append(value)
                recognized = True
            elif value.get("@type") == "ItemList":
                recognized = True
            for key in ("@graph", "itemListElement", "item"):
                if key in value:
                    walk(value[key], depth + 1)
    for node in soup.find_all("script", type="application/ld+json"):
        try:
            walk(json.loads(node.string or node.get_text()))
        except (ValueError, TypeError, RecursionError):
            continue
    if not recognized:
        raise ExtractionError("No hay un calendario JSON-LD reconocible")
    return records


def fee_fields(raw, currency="EUR", secondary=False) -> dict:
    if isinstance(raw, bool) or not isinstance(currency, str) or not re.fullmatch(r"[A-Z]{3}", currency):
        return {}
    if isinstance(raw, str) and raw.strip().casefold() in ("gratis", "gratuito", "free"):
        return {} if secondary else {"entry_price": "0.00", "entry_currency": currency, "entry_price_verified": True}
    value = str(raw).strip().replace("€", "").strip().replace(",", ".")
    if not re.fullmatch(r"\d{1,6}(?:\.\d{1,2})?", value):
        return {}
    try:
        amount = Decimal(value)
        if not amount.is_finite() or amount < 0 or amount > 100000 or (amount == 0 and secondary):
            return {}
        return {"entry_price": format(amount, ".2f"), "entry_currency": currency, "entry_price_verified": True}
    except InvalidOperation:
        return {}


def _registration(value):
    try:
        url = safe_url(value) if isinstance(value, str) else None
        return url if url and urlsplit(url).scheme == "https" and urlsplit(url).hostname in REGISTRATION_HOSTS and urlsplit(url).port in (None, 443) else None
    except ValueError:
        return None


@dataclass
class LocalTCGEventsSource:
    id: str = "local_tcg_events"
    stores: tuple[str, ...] = NEARBY_STORES
    max_items: int = 100
    max_duration_seconds: float = 90
    url: str = "https://dondejugartcg.com/es/torneos/todos/comunidad-de-madrid/alcala-de-henares"

    def parse(self, body: str, page_url: str) -> tuple[list[Item], list[str]]:
        soup = soup_from(body)
        records = event_records(soup)
        accepted, inventory, errors, relevant = [], [], 0, 0
        for record in records:
            title = text(record.get("name", ""))
            description = text(record.get("description", ""))
            location = record.get("location", {})
            if not title or not isinstance(location, dict):
                errors += 1
                continue
            address = location.get("address", {})
            address = address if isinstance(address, dict) else {}
            venue, city = text(location.get("name", "")), text(address.get("addressLocality", ""))
            country = address.get("addressCountry", "")
            if isinstance(country, dict):
                country = country.get("name", "")
            offers = record.get("offers", {})
            if isinstance(offers, list):
                offers = offers[0] if len(offers) == 1 else {}
            offers = offers if isinstance(offers, dict) else {}
            registration = _registration(record.get("url")) or _registration(offers.get("url"))
            raw_start, raw_end = record.get("startDate"), record.get("endDate")
            identity = registration or "calendar:" + fingerprint({"page": page_url, "title": title, "start": raw_start})
            inventory.append(identity)
            game = infer_event_tcg(title + " " + description)
            if game is None:
                continue
            relevant += 1
            if country not in ("ES", "España", "Spain") or not venue or not city:
                errors += 1
                continue
            schedule = normalize_event_schedule(raw_start, raw_end, "Europe/Madrid")
            if schedule["certainty"] == "unknown":
                errors += 1
                continue
            data = {"tcg": game, "region": "EU", "country": "ES", "language": "es", "channel": "event",
                    "provenance": "secondary", "venue": venue, "city": city,
                    "address": text(address.get("streetAddress", "")), "summary": description or title,
                    "event_schedule": schedule, "availability_verified": False,
                    "source_page": page_url, "evidence": [title, str(raw_start)],
                    "fee_note": "Tarifa publicada por el agregador; confirmar con la tienda."}
            if registration:
                data["event_reference_url"] = registration
            data.update(fee_fields(offers.get("price"), offers.get("priceCurrency", "EUR"), secondary=True))
            image = record.get("image")
            try:
                if isinstance(image, str) and urlsplit(image).scheme == "https" and urlsplit(image).hostname == "wiugoevdlmfeiprtfzda.supabase.co":
                    data.update(image_url=safe_url(image), image_verified=True)
            except ValueError:
                pass
            raw_status = record.get("eventStatus")
            statuses = {"EventScheduled": "SCHEDULED", "EventCancelled": "CANCELLED", "EventPostponed": "POSTPONED", "EventRescheduled": "RESCHEDULED", "EventMovedOnline": "ANNOUNCED"}
            if raw_status is None:
                state = "ANNOUNCED"
            else:
                try:
                    parts = urlsplit(raw_status)
                    state = statuses.get(parts.path.rsplit("/", 1)[-1], "UNKNOWN") if parts.hostname == "schema.org" and parts.scheme in ("http", "https") else "UNKNOWN"
                except (ValueError, TypeError):
                    state = "UNKNOWN"
            if state == "POSTPONED":
                schedule.update(certainty="estimated", note="Evento aplazado; confirmar la nueva fecha con la tienda.")
            content = "\n".join([title, description, venue, city, str(raw_start or ""), str(raw_end or "")])
            accepted.append(Item(identity, self.id, title, registration or page_url, kind="event", state=state, data=data, content=content))
        if (records and errors == len(records)) or (relevant and not accepted):
            raise ExtractionError("Calendario sin eventos válidos; se conserva el estado")
        self._parse_errors = errors
        return accepted, inventory

    async def fetch(self, http):
        deadline = time.monotonic() + self.max_duration_seconds
        found, inventories, errors = {}, {}, []
        successes = 0
        for slug in self.stores:
            url = "https://dondejugartcg.com/es/tiendas/" + slug
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                errors.append("calendar:time_budget_exhausted")
                break
            try:
                items, inventory = self.parse(await asyncio.wait_for(http.get(url), remaining), url)
            except (ExtractionError, TimeoutError):
                errors.append("calendar:" + slug + ":unavailable")
                continue
            successes += 1
            if getattr(self, "_parse_errors", 0):
                errors.append("calendar:" + slug + ":partial_records")
            if not getattr(self, "_parse_errors", 0):
                inventories["store:" + slug] = inventory
            found.update((item.id, item) for item in items)
        if not successes:
            raise ExtractionError("No se pudo comprobar ningún calendario local")
        items = list(found.values())
        store = getattr(http, "store", None)
        key = "source_cursor:" + self.id
        cursor = int(store.get_meta(key, 0)) if store else getattr(self, "_cursor", 0)
        cursor %= max(1, len(items))
        selected = (items[cursor:] + items[:cursor])[:self.max_items]
        self._cursor = (cursor + len(selected)) % max(1, len(items))
        if store:
            store.set_meta(key, self._cursor)
        return FetchResult(selected, not_modified=not selected, metadata={"method": "public JSON-LD Event calendars", "errors": errors,
                           "bootstrap_ids": list(found), "discovery_inventories": inventories})


@dataclass
class MundicomicsEventsSource:
    id: str = "mundicomics_events"
    url: str = "https://www.mundicomics.com/torneos-tcg"
    max_items: int = 100

    def parse(self, body: str) -> FetchResult:
        soup = soup_from(body)
        root = soup.find("html")
        classes = " ".join(root.get("class", [])) if root else ""
        parts = {key: re.search(r"(?:^|\s)" + key + r"-(\d+)(?:\s|$)", classes) for key in ("year", "month", "day")}
        if not all(parts.values()):
            raise ExtractionError("Calendario Mundicomics sin contexto anual verificable")
        try:
            rendered = date(*(int(parts[key].group(1)) for key in ("year", "month", "day")))
        except ValueError:
            raise ExtractionError("Contexto temporal Mundicomics inválido") from None
        sections = soup.select(".mc-week-section")
        if not sections:
            raise ExtractionError("Estructura de calendario Mundicomics no reconocida")
        found = {}
        weekdays = ("lun", "mar", "mié", "jue", "vie", "sáb", "dom")
        for section in sections[:12]:
            heading = section.select_one(".mc-week-dates") or section.select_one(".mc-week-label")
            label = text(heading.get_text(" ", strip=True)) if heading else ""
            match = re.fullmatch(r"(\d{1,2})(?:\s+de\s+([a-záéíóú]+))?\s*[-–]\s*(\d{1,2})\s+de\s+([a-záéíóú]+)", label, re.I)
            if not match:
                raise ExtractionError("Semana Mundicomics sin fecha reconocible")
            start_day, start_month = int(match[1]), MONTHS.get((match[2] or match[4]).lower())
            end_day, end_month = int(match[3]), MONTHS.get(match[4].lower())
            candidates = []
            for year in range(rendered.year - 1, rendered.year + 2):
                try:
                    start = date(year, start_month, start_day)
                except (ValueError, TypeError):
                    continue
                end = start + timedelta(days=6)
                if start.weekday() == 0 and end.day == end_day and end.month == end_month and -14 <= (start - rendered).days <= 120:
                    candidates.append(start)
            if len(candidates) != 1:
                raise ExtractionError("Año del calendario Mundicomics ambiguo o desactualizado")
            start = candidates[0]
            days = section.select(".mc-day-card")
            if len(days) != 7:
                raise ExtractionError("Semana Mundicomics incompleta")
            for position, card in enumerate(days):
                day = start + timedelta(days=position)
                name, number = card.select_one(".mc-day-name"), card.select_one(".mc-day-num")
                if (not name or not number or name.get_text(strip=True).casefold() != weekdays[position]
                        or number.get_text(strip=True) != str(day.day)):
                    raise ExtractionError("Día Mundicomics no coincide con la semana")
                counts = {}
                for node in card.select(".mc-event"):
                    game_node = node.select_one(".mc-event-game")
                    title = text(game_node.get_text(" ", strip=True)) if game_node else ""
                    game = infer_event_tcg(title)
                    if not game:
                        continue
                    mode_node, hour_node = node.select_one(".mc-event-mode"), node.select_one(".mc-detail-time")
                    mode = text(mode_node.get_text(" ", strip=True)) if mode_node else ""
                    hour = text(hour_node.get_text(" ", strip=True)) if hour_node else ""
                    if hour and not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", hour):
                        raise ExtractionError("Hora Mundicomics inválida")
                    raw_start = day.isoformat() + "T" + hour if hour else day.isoformat()
                    schedule = normalize_event_schedule(raw_start, venue_timezone="Europe/Madrid")
                    schedule.update(certainty="estimated", note="Año deducido del contexto publicado del calendario; confirmar con la tienda.", evidence=[label, hour or str(day.day), "year-" + str(rendered.year)])
                    count_key = (game, title, mode)
                    counts[count_key] = counts.get(count_key, 0) + 1
                    identity = "event:" + fingerprint({"day": day.isoformat(), "game": game, "title": title, "mode": mode, "slot": counts[count_key]})
                    data = {"tcg": game, "region": "EU", "country": "ES", "language": "es", "channel": "event", "provenance": "retailer",
                            "venue": "Mundicomics", "city": "Torrejón de Ardoz", "summary": title + (" · " + mode if mode else ""),
                            "event_schedule": schedule, "availability_verified": False, "evidence": [label, title]}
                    price_node = node.select_one(".mc-detail-price")
                    if price_node:
                        data.update(fee_fields(text(price_node.get_text(" ", strip=True))))
                    spots = node.select_one(".mc-detail-spots")
                    if spots:
                        capacity = re.fullmatch(r"(\d{1,4})\s+plazas", spots.get_text(strip=True))
                        if capacity:
                            data["capacity"] = int(capacity[1])
                    content = "\n".join([title, mode, label, str(day.day), hour, "year-" + str(rendered.year), "Mundicomics · Torrejón de Ardoz"])
                    found[identity] = Item(identity, self.id, title + (" · " + mode if mode else ""), self.url,
                                           kind="event", state="SCHEDULED", data=data, content=content)
        items = list(found.values())
        return FetchResult(items[:self.max_items], not_modified=not items,
                           metadata={"method": "retailer weekly HTML calendar; inferred year", "bootstrap_ids": list(found)})

    async def fetch(self, http):
        return self.parse(await http.get(self.url))
