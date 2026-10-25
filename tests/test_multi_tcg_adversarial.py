"""Regressions found while reviewing untrusted multi-game calendar input."""
import json

import pytest

from drop_alerts.config import Settings
from drop_alerts.detection import DetectionEngine
from drop_alerts.event_schedule import normalize_event_schedule
from drop_alerts.rules import RuleEngine
from drop_alerts.sources.local_events import LocalTCGEventsSource
from drop_alerts.storage import Store


def calendar_event(number, *, location=True):
    record = {"@type": "Event", "name": f"One Piece Tournament {number}",
              "startDate": "2026-11-14T17:00:00+01:00",
              "url": f"https://www.bandai-tcg-plus.com/event/{number}",
              "location": {"name": "Medusa Cómics", "address": {
                  "addressCountry": "ES", "addressLocality": "Alcalá de Henares"}}}
    if not location:
        record["location"] = None
    return record


def calendar_html(records):
    return '<html><script type="application/ld+json">' + json.dumps(records) + '</script></html>'


@pytest.mark.asyncio
async def test_partially_malformed_store_inventory_does_not_notify_recovered_history():
    source = LocalTCGEventsSource(stores=("medusa-comics",))
    store = Store(":memory:")
    config = Settings(llm_enabled=False, bootstrap_mode="silent", rules=[{"id": "all"}])
    class HTTP:
        body = calendar_html([calendar_event(101), calendar_event(102, location=False)])
        async def get(self, url):
            return self.body
    http = HTTP()
    http.store = store
    partial = await source.fetch(http)
    assert len(partial.items) == 1 and partial.metadata["errors"]
    assert "store:medusa-comics" not in partial.metadata["discovery_inventories"]
    store.ingest(source.id, partial, DetectionEngine(), RuleEngine(config.rules), config)
    http.body = calendar_html([calendar_event(101), calendar_event(102)])
    restored = await source.fetch(http)
    assert "store:medusa-comics" in restored.metadata["discovery_inventories"]
    store.ingest(source.id, restored, DetectionEngine(), RuleEngine(config.rules), config)
    assert store.item(source.id, "https://www.bandai-tcg-plus.com/event/102")[0] is not None
    assert not store.due_notifications(10)
    # The now complete inventory is a baseline, not a permanent mute.
    http.body = calendar_html([calendar_event(101), calendar_event(102), calendar_event(103)])
    store.ingest(source.id, await source.fetch(http), DetectionEngine(), RuleEngine(config.rules), config)
    assert [event.item_id for event, _ in store.due_notifications(10)] == ["https://www.bandai-tcg-plus.com/event/103"]
    store.close()


@pytest.mark.parametrize("start,end", [
    ("2026-03-29T01:00:00+01:00", "2026-03-29T02:30:00"),
    ("2026-10-25T01:00:00+02:00", "2026-10-25T02:30:00"),
])
def test_nonexistent_or_ambiguous_naive_end_never_invents_finish_time(start, end):
    schedule = normalize_event_schedule(start, end, "Europe/Madrid")
    assert schedule["start_at"] == start
    assert schedule["end_at"] is None
    assert schedule["evidence"] == [start]
