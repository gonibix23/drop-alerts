"""The public, server-rendered Guadalajara calendar, checked 2026-10-25.

Every occurrence comes from a dated cell. Activity URLs identify recurring
descriptions, so identity includes the actual day and a slot within that day.
Moving an activity to another day creates a different occurrence; the source
does not provide a stable occurrence identifier to correlate that move.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date, timedelta
import re
import time
from urllib.parse import parse_qs, urljoin, urlsplit

from ..event_schedule import normalize_event_schedule
from ..models import ExtractionError, FetchResult, Item
from ..profiles import infer_event_tcg, normalized_name
from ..release_dates import MONTHS
from .common import soup_from, text


HOST = "jupiterjuegos.com"
PATH = "/tiendas/guadalajara/"
WEEKDAYS = ("lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo")


def _approved_url(base: str, value: str) -> str | None:
    try:
        candidate = urljoin(base, value)
        parts = urlsplit(candidate)
        if (parts.scheme == "https" and parts.hostname == HOST and not parts.username
                and not parts.password and parts.port in (None, 443) and not parts.fragment):
            return candidate
    except (TypeError, ValueError):
        pass
    return None


@dataclass
class JupiterGuadalajaraEventsSource:
    id: str = "jupiter_guadalajara_events"
    url: str = "https://jupiterjuegos.com/tiendas/guadalajara/"
    max_items: int = 80
    max_duration_seconds: float = 60

    def parse(self, body: str, page_url: str | None = None) -> FetchResult:
        page_url = page_url or self.url
        soup = soup_from(body)
        heading = soup.select_one(".fecha_en_grande")
        title = soup.find("h1")
        if not heading or not title or "guadalajara" not in normalized_name(title.get_text(" ", strip=True)):
            raise ExtractionError("Júpiter Guadalajara: calendario no reconocido")
        label_node = heading.find("span")
        label = text(label_node.get_text(" ", strip=True)) if label_node else ""
        match = re.fullmatch(r"([a-záéíóú]+)\s+(20\d{2})", label, re.I)
        month = MONTHS.get(match[1].lower()) if match else None
        if not month:
            raise ExtractionError("Júpiter Guadalajara: cabecera mensual sin fecha válida")
        month_start = date(int(match[2]), month, 1)
        following = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1)
        grid_start = month_start - timedelta(days=month_start.weekday())
        cells = soup.select("div.calendario_igualar_alturas")
        days_in_month = (following - timedelta(days=1)).day
        expected_cells = ((days_in_month + month_start.weekday() + 6) // 7) * 7
        if len(cells) != expected_cells:
            raise ExtractionError("Júpiter Guadalajara: calendario mensual incompleto")

        found, malformed, target_cards = {}, 0, 0
        for index, cell in enumerate(cells):
            day = grid_start + timedelta(days=index)
            wrapper = cell.parent
            header = wrapper.find("div", recursive=False)
            values = header.find_all("div", recursive=False) if header else []
            if (len(values) != 2 or values[0].get_text(strip=True) != str(day.day)
                    or normalized_name(values[1].get_text(strip=True)) != WEEKDAYS[day.weekday()]):
                raise ExtractionError("Júpiter Guadalajara: secuencia de días no coincide con el mes")
            # Adjacent-month cells are visible context. Their own monthly page
            # supplies the canonical occurrence and avoids overlapping updates.
            if day.month != month_start.month or day.year != month_start.year:
                continue
            counts = {}
            for anchor in cell.find_all("a", href=True, recursive=False):
                details = anchor.find_all("div", recursive=False)
                event_title = text(details[0].get_text(" ", strip=True)) if details else ""
                game = infer_event_tcg(event_title)
                if not game:
                    continue
                target_cards += 1
                activity_url = _approved_url(page_url, anchor["href"])
                path_match = re.fullmatch(r"/tiendas/actividad/(\d+)/", urlsplit(activity_url).path) if activity_url else None
                if not path_match or urlsplit(activity_url).query or len(details) < 2:
                    malformed += 1
                    continue
                activity_id = path_match[1]
                hour_raw = text(details[1].get_text(" ", strip=True))
                hour_match = re.fullmatch(r"([01]?\d|2[0-3]):([0-5]\d)h", hour_raw)
                if hour_raw and not hour_match:
                    malformed += 1
                    continue
                hour = f"{int(hour_match[1]):02}:{hour_match[2]}" if hour_match else ""
                start = day.isoformat() + "T" + hour if hour else day.isoformat()
                schedule = normalize_event_schedule(start, venue_timezone="Europe/Madrid")
                if schedule["certainty"] == "unknown":
                    malformed += 1
                    continue
                weekday_raw = text(values[1].get_text(" ", strip=True))
                evidence = [label, str(day.day), weekday_raw] + ([hour_raw] if hour_raw else [])
                schedule["evidence"] = evidence
                # The date is printed by the calendar. The local timezone, when
                # a time exists, is inferred from the Guadalajara venue.
                counts[activity_id] = counts.get(activity_id, 0) + 1
                identity = f"event:jupiter-guadalajara:{activity_id}:{day.isoformat()}:{counts[activity_id]}"
                data = {
                    "tcg": game, "region": "EU", "country": "ES", "language": "es", "channel": "event",
                    "provenance": "retailer", "venue": "Júpiter Guadalajara", "city": "Guadalajara",
                    "summary": event_title, "event_schedule": schedule, "availability_verified": False,
                    "event_reference_url": activity_url, "source_page": self.url,
                    "evidence": evidence + [event_title], "activity_id": activity_id,
                    "fee_note": "Tarifa no publicada en la celda del calendario; confirmar con la tienda.",
                }
                content = "\n".join(["Júpiter Guadalajara", event_title, *evidence, activity_url])
                found[identity] = Item(identity, self.id, event_title, activity_url,
                                       kind="event", state="SCHEDULED", data=data, content=content)
        if target_cards and malformed == target_cards:
            raise ExtractionError("Júpiter Guadalajara: todas las actividades objetivo son inválidas")

        next_page = None
        for anchor in heading.find_all("a", href=True):
            candidate = _approved_url(page_url, anchor["href"])
            if not candidate:
                continue
            parts = urlsplit(candidate)
            query = parse_qs(parts.query)
            if parts.path != PATH or set(query) != {"fecha"} or len(query["fecha"]) != 1:
                continue
            if query["fecha"][0] == following.strftime("%d-%m-%Y"):
                next_page = candidate
                break
        items = list(found.values())
        return FetchResult(items, not_modified=not items, metadata={
            "method": "retailer dated monthly HTML cells", "month": month_start.strftime("%Y-%m"),
            "next_page": next_page, "bootstrap_ids": list(found),
            "errors": ["calendar:partial_cards"] if malformed else [],
        })

    async def fetch(self, http) -> FetchResult:
        deadline = time.monotonic() + self.max_duration_seconds
        first = self.parse(await asyncio.wait_for(http.get(self.url), max(0, deadline - time.monotonic())), self.url)
        found = {item.id: item for item in first.items}
        inventories = {"month:" + first.metadata["month"]: list(found)}
        errors = list(first.metadata["errors"])
        next_page = first.metadata["next_page"]
        if next_page:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                errors.append("calendar:time_budget_exhausted")
            else:
                try:
                    second = self.parse(await asyncio.wait_for(http.get(next_page), remaining), next_page)
                    expected = (date.fromisoformat(first.metadata["month"] + "-01").replace(day=28) + timedelta(days=4)).strftime("%Y-%m")
                    if second.metadata["month"] != expected:
                        raise ExtractionError("Júpiter Guadalajara: navegación mensual incoherente")
                    inventories["month:" + second.metadata["month"]] = second.metadata["bootstrap_ids"]
                    found.update((item.id, item) for item in second.items)
                    errors.extend(second.metadata["errors"])
                except (ExtractionError, TimeoutError):
                    errors.append("calendar:next_month_unavailable")

        items = list(found.values())
        store = getattr(http, "store", None)
        key = "source_cursor:" + self.id
        try:
            cursor = int(store.get_meta(key, 0)) if store else getattr(self, "_cursor", 0)
        except (ValueError, TypeError):
            cursor = 0
        cursor %= max(1, len(items))
        selected = (items[cursor:] + items[:cursor])[:self.max_items]
        self._cursor = (cursor + len(selected)) % max(1, len(items))
        if store:
            store.set_meta(key, self._cursor)
        return FetchResult(selected, not_modified=not selected, metadata={
            "method": "retailer monthly HTML calendar; at most one visible next-month link",
            "bootstrap_ids": list(found), "discovery_inventories": inventories, "errors": errors,
        })
