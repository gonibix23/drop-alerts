from dataclasses import asdict
import json
from pathlib import Path

import pytest

from drop_alerts.detection import DetectionEngine
from drop_alerts.event_schedule import normalize_event_schedule, validated_event_schedule
from drop_alerts.models import ExtractionError, Item
from drop_alerts.sources.local_events import LocalTCGEventsSource, MundicomicsEventsSource

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_jsonld_calendar_identifies_games_venue_date_and_published_fee():
    items, inventory = LocalTCGEventsSource().parse(fixture("local_events_jsonld.html"), "https://dondejugartcg.com/es/tiendas/medusa-comics")
    assert items and inventory
    assert all(item.kind == "event" and item.state == "SCHEDULED" for item in items)
    assert {item.data["tcg"] for item in items} <= {"magic", "one_piece", "pokemon"}
    for item in items:
        assert item.data["venue"] == "Medusa Cómics"
        assert item.data["city"] == "Alcalá de Henares"
        assert item.data["provenance"] == "secondary"
        assert "price" not in item.data
        assert item.data["availability_verified"] is False
        assert validated_event_schedule(asdict(item))["start_at"]


def test_aggregator_zero_fee_never_claims_free_entry_or_available_stock():
    body = fixture("local_events_jsonld.html")
    # Preserve real Event shape while making the unreliable default price explicit.
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(body, "html.parser")
    records = json.loads(soup.find("script").get_text())
    for record in records:
        record["offers"] = {"price": 0, "priceCurrency": "EUR", "availability": "https://schema.org/InStock"}
    soup.find("script").string = json.dumps(records)
    items, _ = LocalTCGEventsSource().parse(str(soup), "https://dondejugartcg.com/es/tiendas/medusa-comics")
    assert all("entry_price" not in item.data and item.state != "AVAILABLE" for item in items)


def test_missing_event_does_not_become_cancellation_and_explicit_cancel_is_supported():
    body = fixture("local_events_jsonld.html")
    source = LocalTCGEventsSource()
    old = source.parse(body, source.url)[0][0]
    new = source.parse(body.replace("EventScheduled", "EventCancelled"), source.url)[0][0]
    assert old.id == new.id
    assert [event.event_type for event in DetectionEngine().detect(new, old, 2)] == ["event.cancelled"]


def test_event_time_update_is_not_stock_or_product_release_change():
    source = LocalTCGEventsSource()
    body = fixture("local_events_jsonld.html")
    old = source.parse(body, source.url)[0][0]
    original = old.data["event_schedule"]["evidence"][0]
    changed = original.replace("T17:00", "T18:00")
    assert changed != original
    new = source.parse(body.replace(original, changed), source.url)[0][0]
    assert new.id == old.id
    assert [event.event_type for event in DetectionEngine().detect(new, old, 2)] == ["event.schedule_changed"]


def test_rescheduled_status_and_time_change_produce_one_event_and_missing_end_is_not_reschedule():
    source = LocalTCGEventsSource()
    body = fixture("local_events_jsonld.html")
    old = source.parse(body, source.url)[0][0]
    original = old.data["event_schedule"]["evidence"][0]
    changed = original.replace("T17:00", "T18:00")
    new = source.parse(body.replace(original, changed).replace("EventScheduled", "EventRescheduled"), source.url)[0][0]
    assert new.state == "RESCHEDULED"
    assert [event.event_type for event in DetectionEngine().detect(new, old, 2)] == ["event.schedule_changed"]
    old.data["event_schedule"]["end_at"] = "2026-10-30T19:00:00+01:00"
    old.data["event_schedule"]["evidence"].append("2026-10-30T19:00:00+01:00")
    old.content += "\n2026-10-30T19:00:00+01:00"
    missing_end = source.parse(body, source.url)[0][0]
    assert [event.event_type for event in DetectionEngine().detect(missing_end, old, 2)] == ["event.updated"]


@pytest.mark.parametrize("body", ["<html><h1>Login</h1></html>", '<html><script type="application/ld+json">broken</script></html>'])
def test_unrecognized_or_broken_calendar_fails_closed(body):
    with pytest.raises(ExtractionError):
        LocalTCGEventsSource().parse(body, "https://dondejugartcg.com/es/tiendas/medusa-comics")


def test_mundicomics_replays_real_week_layout_and_marks_year_inference():
    result = MundicomicsEventsSource().parse(fixture("local_events_mundicomics.html"))
    events = [item for item in result.items if item.data["tcg"] == "one_piece"]
    assert len(events) == 3
    tuesday = next(item for item in events if item.data["event_schedule"]["start_date"] == "2026-10-27")
    assert tuesday.data["event_schedule"]["start_at"] == "2026-10-27T17:30:00+01:00"
    assert tuesday.data["event_schedule"]["certainty"] == "estimated"
    assert tuesday.data["entry_price"] == "6.00"
    assert tuesday.data["capacity"] == 16
    assert tuesday.state == "SCHEDULED"
    assert validated_event_schedule(asdict(tuesday)) is not None


def test_mundicomics_uses_source_year_not_system_year_and_rejects_stale_weekday_alignment():
    body = fixture("local_events_mundicomics.html")
    with pytest.raises(ExtractionError):
        MundicomicsEventsSource().parse(body.replace("year-2026", "year-2027"))
    with pytest.raises(ExtractionError):
        MundicomicsEventsSource().parse(body.replace("year-2026", ""))


def test_mundicomics_time_and_fee_changes_preserve_weekly_instance_identity():
    body = fixture("local_events_mundicomics.html")
    source = MundicomicsEventsSource()
    old = source.parse(body).items
    new = source.parse(body.replace("17:30", "18:30").replace("6€", "7€")).items
    assert [item.id for item in old] == [item.id for item in new]
    changes = [(before, after) for before, after in zip(old, new) if before.digest != after.digest]
    assert changes
    before, after = next((a, b) for a, b in changes if a.data["tcg"] == "one_piece")
    assert "event.schedule_changed" in {event.event_type for event in DetectionEngine().detect(after, before, 2)}


@pytest.mark.parametrize("start,zone", [("2026-10-25T02:30:00", "Europe/Madrid"), ("2026-03-29T02:30:00", "Europe/Madrid"), ("not-date", None), (None, None)])
def test_unknown_or_ambiguous_event_clock_never_invents_an_instant(start, zone):
    result = normalize_event_schedule(start, venue_timezone=zone)
    assert result["start_at"] is None and result["certainty"] == "unknown"


def test_date_only_event_keeps_unknown_hour():
    result = normalize_event_schedule("2026-11-14")
    assert result["start_date"] == "2026-11-14" and result["start_at"] is None


@pytest.mark.asyncio
async def test_failure_of_one_store_does_not_initialize_its_inventory_or_block_other_store():
    source = LocalTCGEventsSource(stores=("broken", "medusa-comics"))
    class HTTP:
        async def get(self, url):
            if "/broken" in url:
                raise ExtractionError("network")
            return fixture("local_events_jsonld.html")
    result = await source.fetch(HTTP())
    assert result.items and result.metadata["errors"]
    assert "store:broken" not in result.metadata["discovery_inventories"]
    assert "store:medusa-comics" in result.metadata["discovery_inventories"]
