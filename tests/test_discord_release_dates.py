"""Release dates are independent of detection time and commercial availability."""
from dataclasses import asdict
import json

import pytest

from drop_alerts.models import Event, Item
from drop_alerts.notifications import discord_payload


def schedule(**overrides):
    values = dict(date="2026-11-02", time="09:00", timezone="America/Los_Angeles", end_date=None,
                  certainty="explicit", date_kind="sale", evidence=["On sale November 2, 2026, at 9 a.m. PT."],
                  note="", engine="deterministic", year_inferred=False)
    values.update(overrides)
    return values


def item(value=None, content="On sale November 2, 2026, at 9 a.m. PT."):
    data = {"summary": "Ejemplo ficticio de un anuncio.", "availability_verified": False,
            "published_at": "2026-10-21T16:00:00+00:00"}
    if value is not None:
        data["release_schedule"] = value
    return Item("example", "secret_lair_bluesky", "Ejemplo ficticio", "https://secretlair.wizards.com/eu/",
                "announcement", "ANNOUNCED", data=data, content=content)


def event(current, previous=None, analysis=None):
    return Event("preview-release", current.source, current.id, "announcement.new", "2026-10-21T20:00:00+00:00",
                 current.title, current.url, "digest", {"current": asdict(current), "previous": asdict(previous) if previous else None}, analysis)


def fields(sample, timezone="Europe/Madrid"):
    embed = discord_payload(sample, timezone)["embeds"][0]
    return {field["name"]: field["value"] for field in embed["fields"]}


def test_explicit_sale_time_converts_pacific_to_madrid_in_winter():
    rendered = fields(event(item(schedule())))
    assert "02/11/2026 · 18:00 CET" in rendered["🗓️ Venta prevista"]
    assert "hora de Madrid" in rendered["🗓️ Venta prevista"]
    assert rendered["📍 Estado"] == "Anunciado"
    assert "21/10/2026" in rendered["🕒 Detectado"]
    assert "📦 Disponibilidad" not in rendered


def test_explicit_sale_time_converts_summer_offsets_with_zoneinfo():
    quote = "On sale July 20, 2026, at 9 a.m. PT."
    sample = item(schedule(date="2026-07-20", evidence=[quote]), quote)
    assert "20/07/2026 · 18:00 CEST" in fields(event(sample))["🗓️ Venta prevista"]


def test_date_without_time_does_not_invent_nine_oclock():
    quote = "On sale November 2, 2026."
    sample = item(schedule(time=None, timezone=None, evidence=[quote]), quote)
    value = fields(event(sample))["🗓️ Venta prevista"]
    assert "02/11/2026" in value and "hora sin confirmar" in value
    assert "09:00" not in value and "18:00" not in value


def test_time_without_zone_is_not_converted_to_madrid():
    quote = "On sale November 2, 2026, at 9 a.m."
    sample = item(schedule(timezone=None, evidence=[quote]), quote)
    value = fields(event(sample))["🗓️ Venta prevista"]
    assert "09:00" in value and "zona horaria no especificada" in value
    assert "18:00" not in value


def test_inferred_year_is_marked_as_orientative():
    quote = "On sale November 2."
    sample = item(schedule(time=None, timezone=None, certainty="estimated", year_inferred=True, evidence=[quote]), quote)
    value = fields(event(sample))["🗓️ Venta prevista"]
    assert "Orientativa" in value and "Año inferido" in value


def test_coming_soon_has_no_confirmed_date_without_stock_warning():
    rendered = discord_payload(event(item(content="Secret Lair: coming soon.")))["embeds"][0]
    values = {field["name"]: field["value"] for field in rendered["fields"]}
    assert values["🗓️ Lanzamiento previsto"] == "Sin fecha confirmada"
    assert rendered["color"] == 0x9B6DFF
    assert "Disponibilidad" not in str(values)


def test_conflicting_dates_do_not_show_one_as_confirmed():
    quote = "On sale November 2, 2026. On sale November 9, 2026."
    sample = item(schedule(date=None, time=None, timezone=None, certainty="conflicting", evidence=[quote]), quote)
    value = fields(event(sample))["🗓️ Venta prevista"]
    assert value == "Fechas contradictorias · consultar fuente"
    assert "02/11" not in value and "09/11" not in value


def test_date_change_shows_previous_and_current_schedule():
    old_quote = "On sale October 26, 2026."
    new_quote = "On sale November 2, 2026."
    old = item(schedule(date="2026-10-26", time=None, timezone=None, evidence=[old_quote]), old_quote)
    current = item(schedule(time=None, timezone=None, evidence=[new_quote]), new_quote)
    sample = event(current, old)
    sample.event_type = "release_date.changed"
    payload = discord_payload(sample)
    assert payload["embeds"][0]["author"]["name"] == "🗓️ Cambio de fecha"
    value = fields(sample)["🗓️ Venta prevista"]
    assert "26/10/2026" in value and "→" in value and "02/11/2026" in value


def test_old_event_without_persisted_schedule_is_enriched_for_preview():
    value = fields(event(item()))["🗓️ Venta prevista"]
    assert "02/11/2026" in value and "18:00 CET" in value


def test_free_model_date_is_never_shown_instead_of_source_date():
    sample = event(item(), analysis={"task": "classification", "result": {
        "date": "2099-01-01", "summary": "Buy on 2099-01-01 at https://evil.test", "needs_review": False}})
    encoded = json.dumps(discord_payload(sample), ensure_ascii=False)
    assert "02/11/2026" in encoded and "2099" not in encoded and "evil.test" not in encoded


@pytest.mark.parametrize("value", ["not-a-schedule", {"date": "2026-99-99"}, {"date": "2099-01-01", "certainty": "explicit"}])
def test_malformed_stored_schedule_falls_back_to_literal_source(value):
    rendered = fields(event(item(value)))
    assert "2099" not in str(rendered)
    assert "02/11/2026" in str(rendered)


def test_source_only_shipping_and_legality_do_not_become_a_sale():
    sample = item(content="Ships in December 2027. These cards are legal on April 2, 2027.")
    rendered = fields(event(sample))
    assert rendered["🗓️ Lanzamiento previsto"] == "Sin fecha confirmada"
    assert "2027" not in rendered["🗓️ Lanzamiento previsto"]


def test_ambiguous_and_nonexistent_dst_hours_are_not_presented_as_exact_instants():
    from drop_alerts.notifications import _release_schedule_text
    ambiguous = schedule(date="2026-11-01", time="01:30")
    nonexistent = schedule(date="2026-03-08", time="02:30")
    assert "hora pendiente de confirmar" in _release_schedule_text(ambiguous, "Europe/Madrid")
    assert "hora pendiente de confirmar" in _release_schedule_text(nonexistent, "Europe/Madrid")


def test_end_date_keeps_source_calendar_without_inventing_closing_time():
    from drop_alerts.notifications import _release_schedule_text
    value = _release_schedule_text(schedule(end_date="2026-11-03"), "Europe/Madrid")
    assert "Hasta 03/11/2026" in value and "fecha del Pacífico" in value
    assert "hora de cierre sin confirmar" in value
