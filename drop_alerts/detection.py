from __future__ import annotations

from dataclasses import asdict

from .models import Event, Item, fingerprint
from .schedule_enrichment import effective_release_schedule, schedule_identity, source_text


class DetectionEngine:
    """Compare explicit source data. Model outputs never change source facts."""

    def detect(self, current: Item, previous: Item | None, revision: int) -> list[Event]:
        if previous and previous.digest == current.digest:
            return []
        types: list[str] = []
        if previous is None:
            types = [{"product": "product.new", "collection": "collection.new", "announcement": "announcement.new", "article": "publication.new"}.get(current.kind, "item.new")]
        else:
            if previous.state != current.state:
                if current.state == "UNKNOWN":
                    types.append("change.uncertain")
                else:
                    types.append("availability.changed")
            old_price, new_price = previous.data.get("price"), current.data.get("price")
            if old_price is not None and new_price is not None and (old_price, previous.data.get("currency")) != (new_price, current.data.get("currency")):
                types.append("price.changed")
            if (current.kind in ("article", "announcement", "product", "collection")
                    and source_text(asdict(current)) != source_text(asdict(previous))):
                old_date = schedule_identity(effective_release_schedule(asdict(previous)))
                new_date = schedule_identity(effective_release_schedule(asdict(current)))
                if old_date is not None and new_date is not None and old_date != new_date:
                    types.append("release_date.changed")
            if not types:
                types.append("content.changed")
        events = []
        for event_type in types:
            digest = fingerprint({"source": current.source, "item": current.id, "revision": revision, "type": event_type, "previous": previous.digest if previous else None, "current": current.digest})
            events.append(Event(digest, current.source, current.id, event_type, current.observed_at, current.title, current.url, digest, {"previous": asdict(previous) if previous else None, "current": asdict(current), "engine": "deterministic"}))
        return events
