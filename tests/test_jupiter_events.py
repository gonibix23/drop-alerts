"""Saved public Guadalajara calendar responses; no network or Discord calls."""
import asyncio
from dataclasses import asdict
from pathlib import Path

from bs4 import BeautifulSoup
import pytest

from drop_alerts.event_schedule import EventSchedule, validated_event_schedule
from drop_alerts.models import ExtractionError
from drop_alerts.sources.jupiter_events import JupiterGuadalajaraEventsSource
from drop_alerts.storage import Store


FIXTURES = Path(__file__).parent / "fixtures"
ROOT_URL = "https://jupiterjuegos.com/tiendas/guadalajara/"
NEXT_URL = ROOT_URL + "?fecha=01-11-2026"


def calendar(month="october"):
    return (FIXTURES / ("jupiter_guadalajara_" + month + ".html")).read_text(encoding="utf-8")


class HTTP:
    def __init__(self, second=None, store=None):
        self.store, self.calls = store, []
        self.responses = {ROOT_URL: calendar(), NEXT_URL: calendar("november") if second is None else second}

    async def get(self, url):
        self.calls.append(url)
        result = self.responses[url]
        if isinstance(result, Exception):
            raise result
        return result


def test_verified_months_extract_only_dated_target_games():
    source = JupiterGuadalajaraEventsSource()
    october, november = source.parse(calendar()), source.parse(calendar("november"))
    assert len(october.items) == 24 and len(november.items) == 21
    assert {i.data["tcg"] for i in october.items} == {"magic", "one_piece", "pokemon"}
    assert all(i.data["event_schedule"]["start_date"].startswith("2026-10-") for i in october.items)
    assert all(i.data["event_schedule"]["start_date"].startswith("2026-11-") for i in november.items)
    for item in october.items + november.items:
        assert item.source == "jupiter_guadalajara_events" and item.kind == "event" and item.state == "SCHEDULED"
        assert item.data["region"] == "EU" and item.data["country"] == "ES" and item.data["city"] == "Guadalajara"
        assert item.data["venue"] == "Júpiter Guadalajara" and item.data["provenance"] == "retailer"
        assert item.url.startswith("https://jupiterjuegos.com/tiendas/actividad/")
        assert item.data["availability_verified"] is False
        assert "price" not in item.data and "entry_price" not in item.data
        assert not any(word in item.title.lower() for word in ("lorcana", "riftbound", "reserva mesa"))
        schedule = EventSchedule.model_validate(item.data["event_schedule"])
        assert schedule.end_at is None and validated_event_schedule(asdict(item))


def test_shared_activity_url_has_a_separate_identity_for_each_printed_day():
    items = JupiterGuadalajaraEventsSource().parse(calendar()).items
    pokemon = [item for item in items if item.data["activity_id"] == "665"]
    assert len(pokemon) > 1 and len({item.url for item in pokemon}) == 1
    assert len({item.id for item in pokemon}) == len(pokemon)
    assert len({item.data["event_schedule"]["start_date"] for item in pokemon}) == len(pokemon)


def test_multiple_slots_on_a_day_and_time_changes_do_not_merge_occurrences():
    soup = BeautifulSoup(calendar(), "html.parser")
    card = soup.find("a", href="https://jupiterjuegos.com/tiendas/actividad/662/")
    card.insert_after(BeautifulSoup(str(card), "html.parser").find("a"))
    source = JupiterGuadalajaraEventsSource()
    result = source.parse(str(soup))
    first_slots = [item for item in result.items if ":662:2026-10-03:" in item.id]
    assert len(first_slots) == 2 and {item.id.rsplit(":", 1)[-1] for item in first_slots} == {"1", "2"}
    before = source.parse(calendar()).items[0]
    changed = source.parse(calendar().replace("17:15h", "18:15h")).items[0]
    assert before.id == changed.id and before.digest != changed.digest


def test_dst_comes_from_venue_and_missing_time_remains_day_only():
    source = JupiterGuadalajaraEventsSource()
    items = source.parse(calendar()).items
    before = next(i for i in items if ":2026-10-24:" in i.id)
    after = next(i for i in items if ":2026-10-25:" in i.id)
    assert before.data["event_schedule"]["start_at"].endswith("+02:00")
    assert after.data["event_schedule"]["start_at"].endswith("+01:00")
    soup = BeautifulSoup(calendar(), "html.parser")
    card = soup.find("a", href="https://jupiterjuegos.com/tiendas/actividad/662/")
    card.find_all("div", recursive=False)[1].clear()
    day_only = next(i for i in source.parse(str(soup)).items if ":662:2026-10-03:" in i.id)
    assert day_only.data["event_schedule"]["start_at"] is None
    assert day_only.data["event_schedule"]["start_date"] == "2026-10-03"


@pytest.mark.parametrize("mutation", ["heading", "month", "day", "weekday", "missing_cell", "missing_week", "wrong_venue"])
def test_structure_and_date_mismatch_preserve_stored_state_by_raising(mutation):
    soup = BeautifulSoup(calendar(), "html.parser")
    first = soup.select_one("div.calendario_igualar_alturas")
    if mutation == "heading":
        soup.select_one(".fecha_en_grande").decompose()
    elif mutation == "month":
        soup.select_one(".fecha_en_grande span").string = "Mes no confirmado"
    elif mutation == "day":
        first.parent.find("div", recursive=False).find_all("div", recursive=False)[0].string = "29"
    elif mutation == "weekday":
        first.parent.find("div", recursive=False).find_all("div", recursive=False)[1].string = "MARTES"
    elif mutation == "missing_cell":
        first.parent.decompose()
    elif mutation == "missing_week":
        for cell in soup.select("div.calendario_igualar_alturas")[-7:]:
            cell.parent.decompose()
    else:
        soup.find("h1").string = "Júpiter México"
    with pytest.raises(ExtractionError):
        JupiterGuadalajaraEventsSource().parse(str(soup))


def test_unknown_games_form_a_healthy_empty_calendar():
    soup = BeautifulSoup(calendar(), "html.parser")
    for cell in soup.select("div.calendario_igualar_alturas"):
        for card in cell.find_all("a", href=True, recursive=False):
            card.find("div").string = "Disney Lorcana"
    result = JupiterGuadalajaraEventsSource().parse(str(soup))
    assert result.items == [] and result.not_modified


def test_invalid_hour_or_offsite_activity_is_not_used_as_an_event_or_fetch_target():
    soup = BeautifulSoup(calendar(), "html.parser")
    target = soup.find("a", href="https://jupiterjuegos.com/tiendas/actividad/662/")
    target["href"] = "https://attacker.example/tiendas/actividad/662/"
    result = JupiterGuadalajaraEventsSource().parse(str(soup))
    assert len(result.items) == 23 and result.metadata["errors"] == ["calendar:partial_cards"]
    assert all("attacker" not in item.url for item in result.items)
    result = JupiterGuadalajaraEventsSource().parse(calendar().replace("17:15h", "29:99h"))
    assert len(result.items) == 14 and all(item.data["tcg"] != "magic" for item in result.items)


def test_fetch_uses_only_one_visible_month_link_and_has_full_bootstrap_inventory():
    http = HTTP()
    result = asyncio.run(JupiterGuadalajaraEventsSource(max_items=3).fetch(http))
    assert http.calls == [ROOT_URL, NEXT_URL]
    assert len(result.items) == 3 and len(result.metadata["bootstrap_ids"]) == 45
    assert set(result.metadata["discovery_inventories"]) == {"month:2026-10", "month:2026-11"}
    assert result.metadata["errors"] == []


def test_rotating_limit_survives_restart_without_changing_item_digests(tmp_path):
    store = Store(str(tmp_path / "state.sqlite3"))
    http = HTTP(store=store)
    first = asyncio.run(JupiterGuadalajaraEventsSource(max_items=3).fetch(http))
    second = asyncio.run(JupiterGuadalajaraEventsSource(max_items=3).fetch(http))
    assert {i.id for i in first.items}.isdisjoint({i.id for i in second.items})
    a = asyncio.run(JupiterGuadalajaraEventsSource().fetch(HTTP()))
    b = asyncio.run(JupiterGuadalajaraEventsSource().fetch(HTTP()))
    assert {i.id: i.digest for i in a.items} == {i.id: i.digest for i in b.items}
    store.close()


@pytest.mark.parametrize("second", [ExtractionError("HTTP 503"), calendar()])
def test_next_month_failure_keeps_current_month_and_reports_partial_coverage(second):
    result = asyncio.run(JupiterGuadalajaraEventsSource().fetch(HTTP(second=second)))
    assert len(result.items) == 24
    assert result.metadata["errors"] == ["calendar:next_month_unavailable"]
    assert set(result.metadata["discovery_inventories"]) == {"month:2026-10"}


def test_first_month_failure_is_an_extraction_error():
    http = HTTP()
    http.responses[ROOT_URL] = ExtractionError("HTTP 503")
    with pytest.raises(ExtractionError):
        asyncio.run(JupiterGuadalajaraEventsSource().fetch(http))


def test_slow_next_month_is_bounded_and_does_not_lose_current_month():
    class Slow(HTTP):
        async def get(self, url):
            if url == NEXT_URL:
                await asyncio.sleep(.05)
            return await super().get(url)
    result = asyncio.run(JupiterGuadalajaraEventsSource(max_duration_seconds=.03).fetch(Slow()))
    assert len(result.items) == 24
    assert result.metadata["errors"] in (["calendar:next_month_unavailable"], ["calendar:time_budget_exhausted"])


def test_calendar_navigation_cannot_fetch_an_offsite_or_unpublished_url():
    for bad in ("https://attacker.example/?fecha=01-11-2026", ROOT_URL + "?fecha=01-11-2026&token=private", ROOT_URL + "?fecha=01-12-2026"):
        http = HTTP()
        http.responses[ROOT_URL] = calendar().replace(NEXT_URL, bad)
        result = asyncio.run(JupiterGuadalajaraEventsSource().fetch(http))
        assert http.calls == [ROOT_URL] and len(result.items) == 24
