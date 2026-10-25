from pathlib import Path
import json

import pytest

from drop_alerts.event_schedule import validated_event_schedule
from drop_alerts.models import ExtractionError
from drop_alerts.sources.store_calendars import Arte9EventsSource, GladiusEventsSource, LudotecaEventsSource, NextDiceEventsSource

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name):
    return (FIXTURES / ("store_calendar_" + name)).read_text(encoding="utf-8")


class MemoryStore:
    def __init__(self):
        self.meta = {}
        self.items = {}
    def get_meta(self, key, default=None):
        return self.meta.get(key, default)
    def set_meta(self, key, value):
        self.meta[key] = value
    def get_source_items(self, source):
        return list(self.items.get(source, {}).values())


class HTTP:
    def __init__(self, responses, store=None):
        self.responses, self.store, self.calls = responses, store, []
    async def get(self, url):
        self.calls.append(url)
        result = self.responses[url]
        if isinstance(result, Exception):
            raise result
        return result


def test_gladius_saved_ticket_is_an_event_with_date_only_and_entry_price():
    source = GladiusEventsSource()
    candidates = source.parse_listing(fixture("gladius_listing.html"))
    candidate = next(item for item in candidates if "pokemon" in item.url)
    item = source.parse_detail(fixture("gladius_detail.html"), candidate)
    assert item.id == "product:8573" and item.kind == "event"
    assert item.data["tcg"] == "pokemon" and item.data["region"] == "EU"
    schedule = item.data["event_schedule"]
    assert schedule["start_date"] == "2026-11-14" and schedule["start_at"] is None
    assert item.data["entry_price"] == "6" and item.data["entry_currency"] == "EUR"
    assert item.data["entry_price_verified"] is True
    assert "price" not in item.data and item.data["availability_verified"] is False
    assert "Gladius Games" == item.data["venue"] and "Alcalá" in item.data["city"]
    assert validated_event_schedule({"data": item.data, "content": item.content})


def test_gladius_reschedule_keeps_the_prestashop_product_identity_and_never_uses_stock():
    source = GladiusEventsSource()
    candidate = next(item for item in source.parse_listing(fixture("gladius_listing.html")) if "pokemon" in item.url)
    original = source.parse_detail(fixture("gladius_detail.html"), candidate)
    changed = source.parse_detail(fixture("gladius_detail.html").replace("14/11/2026", "21/11/2026").replace("InStock", "OutOfStock"), candidate)
    assert changed.id == original.id
    assert changed.data["event_schedule"]["start_date"] == "2026-11-21"
    assert changed.state == original.state == "SCHEDULED"


@pytest.mark.parametrize("body", ["<html>Maintenance</html>", '<html><script type="application/ld+json">{"@type":"ItemList","itemListElement":[{"name":"Magic","url":"https://evil.test/event"}]}</script></html>'])
def test_gladius_rejects_changed_listing_or_external_calendar_links(body):
    with pytest.raises(ExtractionError):
        GladiusEventsSource().parse_listing(body)


def test_gladius_invalid_date_does_not_overwrite_prior_schedule():
    source = GladiusEventsSource()
    candidate = next(item for item in source.parse_listing(fixture("gladius_listing.html")) if "pokemon" in item.url)
    with pytest.raises(ExtractionError):
        source.parse_detail(fixture("gladius_detail.html").replace("14/11/2026", "31/02/2026"), candidate)


@pytest.mark.asyncio
async def test_gladius_partial_detail_failure_keeps_successful_events_and_full_bootstrap_inventory():
    source = GladiusEventsSource(max_details=8)
    candidates = source.parse_listing(fixture("gladius_listing.html"))
    responses = {source.url: fixture("gladius_listing.html")}
    responses.update({item.url: fixture("gladius_detail.html") if "pokemon" in item.url else ExtractionError("network") for item in candidates})
    result = await source.fetch(HTTP(responses))
    assert len(result.items) == 1 and result.metadata["errors"]
    assert set(result.metadata["bootstrap_ids"]) == {item.id for item in candidates}


def test_nextdice_uses_event_attached_category_not_navigation_and_preserves_explicit_offset():
    items, errors = NextDiceEventsSource().parse(fixture("nextdice_listing.html"))
    assert len(items) == 2 and not errors
    magic = next(item for item in items if item.data["tcg"] == "magic")
    assert magic.title == "Friday Night Next Dice"
    assert "Categoría: Magic: The Gathering" in magic.content
    piece = next(item for item in items if item.data["tcg"] == "one_piece")
    assert piece.data["event_schedule"]["start_at"] == "2026-06-13T17:30:00+02:00"
    assert piece.data["entry_price"] == "6.00" and piece.data["entry_price_verified"] is True
    assert all(item.kind == "event" and item.data["country"] == "ES" for item in items)
    assert all("Warhammer" not in item.title for item in items)


def test_nextdice_conflicting_game_labels_are_not_guessed():
    body = fixture("nextdice_listing.html").replace("One Piece Card Game</p>", "Pokémon</p>")
    items, _ = NextDiceEventsSource().parse(body)
    assert all(item.data["tcg"] != "one_piece" for item in items)


def test_nextdice_price_from_is_not_presented_as_fixed_entry_fee():
    body = fixture("nextdice_listing.html").replace("6,00 €", "Desde 6,00 €")
    piece = next(item for item in NextDiceEventsSource().parse(body)[0] if item.data["tcg"] == "one_piece")
    assert "entry_price" not in piece.data


def test_nextdice_missing_card_structure_is_an_error():
    with pytest.raises(ExtractionError):
        NextDiceEventsSource().parse('<html><main><a href="https://nextdice.es/evento/a/">Pokemon</a></main></html>')


@pytest.mark.asyncio
async def test_nextdice_fetch_is_single_bounded_listing_request():
    source = NextDiceEventsSource(max_items=1)
    http = HTTP({source.url: fixture("nextdice_listing.html")})
    first = await source.fetch(http)
    second = await source.fetch(http)
    assert len(first.items) == len(second.items) == 1
    assert first.items[0].id != second.items[0].id
    assert http.calls == [source.url, source.url]
    assert len(first.metadata["bootstrap_ids"]) == 2


def ics(properties):
    return "BEGIN:VCALENDAR\nVERSION:2.0\nBEGIN:VEVENT\nUID:stable@example\nSUMMARY:Torneo One Piece\nURL:https://arte9.com/torneo/12345/\nLOCATION:Arte9\\, Madrid\n" + properties + "\nEND:VEVENT\nEND:VCALENDAR"


def test_arte9_replays_real_declared_ical_under_standard_body_limit():
    items, errors = Arte9EventsSource().parse(fixture("arte9.ics"))
    assert len(items) == 3 and not errors
    assert all(item.kind == "event" and item.data["tcg"] in ("magic", "one_piece", "pokemon") for item in items)
    assert any(item.data.get("title_derived") for item in items)
    assert all(item.data["event_schedule"]["timezone"] == "Europe/Madrid" for item in items)
    assert all(validated_event_schedule({"data": item.data, "content": item.content}) for item in items)


def test_arte9_time_change_keeps_post_identity_even_if_publisher_uid_embeds_timestamp():
    source = Arte9EventsSource()
    old = source.parse(ics("DTSTART;TZID=Europe/Madrid:20261108T160000\nDTEND;TZID=Europe/Madrid:20261108T180000"))[0][0]
    new = source.parse(ics("DTSTART;TZID=Europe/Madrid:20261108T170000\nDTEND;TZID=Europe/Madrid:20261108T190000").replace("stable@example", "timestamp-new@example"))[0][0]
    assert old.id == new.id == "event:12345"
    assert old.data["event_schedule"]["start_at"] != new.data["event_schedule"]["start_at"]


def test_arte9_date_only_does_not_add_midnight_or_end_time():
    item = Arte9EventsSource().parse(ics("DTSTART;VALUE=DATE:20261108\nDTEND;VALUE=DATE:20261109"))[0][0]
    assert item.data["event_schedule"]["start_date"] == "2026-11-08"
    assert item.data["event_schedule"]["start_at"] is None
    assert item.data["event_schedule"]["end_at"] is None


def test_arte9_unfolds_escaped_and_cancelled_events_without_expanding_recurrences():
    item = Arte9EventsSource().parse(ics("DTSTART:20261108T150000Z\nDESCRIPTION:Entrada: 5 euros\\nDatos\n plegados\nSTATUS:CANCELLED"))[0][0]
    assert item.state == "CANCELLED"
    assert item.data["entry_price"] == "5"
    assert "Datosplegados" in item.content
    with pytest.raises(ExtractionError):
        Arte9EventsSource().parse(ics("DTSTART:20261108T150000Z\nRRULE:FREQ=WEEKLY"))


@pytest.mark.parametrize("property", ["RDATE:20261115T150000Z", "EXDATE:20261108T150000Z"])
def test_arte9_does_not_silently_ignore_recurrence_dates_or_cancelled_instances(property):
    with pytest.raises(ExtractionError):
        Arte9EventsSource().parse(ics("DTSTART:20261108T150000Z\n" + property))


@pytest.mark.parametrize("properties", [
    "DTSTART;TZID=../../untrusted:20261108T150000",
    "DTSTART;TZID=Europe/Madrid:20260329T023000",
    "DTSTART;TZID=Europe/Madrid:20261025T023000",
    "DTSTART:invalid",
    "DTSTART:20261108T150000Z\nDTEND:20261108T140000Z",
])
def test_arte9_invalid_or_ambiguous_calendar_date_is_not_accepted(properties):
    with pytest.raises(ExtractionError):
        Arte9EventsSource().parse(ics(properties))


def test_arte9_never_visits_external_event_links_or_uses_title_from_navigation():
    with pytest.raises(ExtractionError):
        Arte9EventsSource().parse(ics("DTSTART:20261108T150000Z").replace("https://arte9.com/torneo/12345/", "https://evil.test/torneo/12345/"))
    non_tcg = ics("DTSTART:20261108T150000Z").replace("SUMMARY:Torneo One Piece", "SUMMARY:Torneo Warhammer")
    assert not Arte9EventsSource().parse(non_tcg)[0]


@pytest.mark.parametrize("body", ["<html>Login</html>", "BEGIN:VCALENDAR\nBEGIN:VEVENT\nEND:VCALENDAR", "BEGIN:VCALENDAR\nEND:VEVENT\nEND:VCALENDAR"])
def test_arte9_malformed_or_non_calendar_response_is_an_error(body):
    with pytest.raises(ExtractionError):
        Arte9EventsSource().parse(body)


def test_ludoteca_keeps_multi_session_window_without_inventing_continuous_tournament():
    source = LudotecaEventsSource()
    candidate = source.parse_listing(fixture("ludoteca_listing.html"))[0]
    item = source.parse_detail(fixture("ludoteca_detail.html"), candidate)
    assert item.id == "event:81385" and item.data["tcg"] == "pokemon"
    assert item.data["multiple_sessions"] is True
    assert item.data["event_schedule"]["start_at"] is None
    assert item.data["event_period_text"] in item.content
    assert "24/10/2026" in item.data["event_period_text"] and "28/10/2026" in item.data["event_period_text"]
    assert item.data["entry_price"] == "30.00"  # Confirmed by single detail Offer, not the listing's "Price Starts".
    assert item.data["entry_price_verified"] is True


def test_ludoteca_single_session_can_use_its_structured_event_schedule():
    source = LudotecaEventsSource()
    candidate = source.parse_listing(fixture("ludoteca_listing.html"))[0]
    body = fixture("ludoteca_detail.html").replace(" o Miercoles 28 de Octubre a las 18:00", "")
    item = source.parse_detail(body, candidate)
    assert item.data["event_schedule"]["start_at"] == "2026-10-24T10:30:00+02:00"
    assert item.data["event_schedule"]["end_at"] == "2026-10-24T14:00:00+02:00"


def test_ludoteca_changed_detail_does_not_become_unknown_schedule_or_stock_change():
    source = LudotecaEventsSource()
    candidate = source.parse_listing(fixture("ludoteca_listing.html"))[0]
    with pytest.raises(ExtractionError):
        source.parse_detail("<html><main>Login</main></html>", candidate)
