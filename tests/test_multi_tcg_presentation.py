"""Discord identifies the game and market without inferring stock or card language."""
from dataclasses import asdict
import json

import pytest

from drop_alerts.models import Event, Item
from drop_alerts.notifications import discord_payload
from drop_alerts.event_schedule import normalize_event_schedule


def event(tcg=None, region="GLOBAL", language=None, channel=None, source="custom_news", **overrides):
    data = {"summary": "Ejemplo ficticio de una próxima colección.", "availability_verified": False, "region": region}
    if tcg is not None:
        data["tcg"] = tcg
    if language:
        data["language"] = language
    if channel:
        data["channel"] = channel
    data.update(overrides.pop("data", {}))
    item = Item("preview", source, overrides.pop("title", "EJEMPLO FICTICIO · próximo producto"),
                "https://official.test/example", kind="announcement", state="ANNOUNCED", data=data,
                content="Available November 2, 2026.")
    item.state = overrides.pop("state", item.state)
    item.kind = overrides.pop("kind", item.kind)
    return Event("multi-tcg-preview", source, item.id, overrides.pop("event_type", "announcement.new"),
                 "2026-10-25T12:00:00+00:00", item.title, item.url, "preview",
                 {"current": asdict(item), "previous": None}, overrides.pop("analysis", None))


def fields(payload):
    return {field["name"]: field["value"] for field in payload["embeds"][0]["fields"]}


@pytest.mark.parametrize("tcg,label,color", [
    ("magic", "Magic: The Gathering", 0x9B6DFF),
    ("one_piece", "One Piece Card Game", 0xE75B56),
    ("pokemon", "Pokémon TCG", 0xF2C94C),
])
def test_each_game_has_a_clear_label_and_editorial_accent(tcg, label, color):
    payload = discord_payload(event(tcg))
    assert fields(payload)["🃏 Juego"] == label
    assert payload["embeds"][0]["color"] == color
    assert fields(payload)["📍 Estado"] == "Anunciado"
    assert "🗓️ Venta prevista" in fields(payload)


def test_legacy_magic_source_is_identified_without_mutating_persisted_event():
    sample = event(source="magic_news")
    original = json.dumps(asdict(sample), sort_keys=True)
    assert fields(discord_payload(sample))["🃏 Juego"] == "Magic: The Gathering"
    assert json.dumps(asdict(sample), sort_keys=True) == original


def test_unknown_source_is_not_magic_because_title_mentions_it():
    payload = discord_payload(event(source="software_releases", title="Magic compiler release"))
    assert "🃏 Juego" not in fields(payload) or fields(payload)["🃏 Juego"] != "Magic: The Gathering"


def test_explicit_game_identity_does_not_come_from_title_words():
    payload = discord_payload(event("one_piece", title="EJEMPLO FICTICIO · Pokémon discussion"))
    assert fields(payload)["🃏 Juego"] == "One Piece Card Game"


def test_japanese_announcement_does_not_claim_european_stock_or_spanish_cards():
    payload = discord_payload(event("one_piece", region="JP", language="ja", channel="catalog"))
    values = fields(payload)
    assert values["🌍 Región"] == "Japón"
    assert values["🌐 Idioma de la fuente"] == "Japonés"
    assert values["🏷️ Canal"] == "Catálogo"
    assert "📦 Disponibilidad" not in values
    assert "España" not in json.dumps(payload, ensure_ascii=False)


def test_western_market_is_described_as_including_europe_not_as_exclusively_eu():
    values = fields(discord_payload(event("one_piece", region="WESTERN", language="en")))
    assert values["🌍 Región"] == "Occidente · incluye Europa"
    assert values["🌐 Idioma de la fuente"] == "Inglés"


def test_us_price_remains_usd_and_region_is_explicit():
    payload = discord_payload(event("pokemon", region="US", data={"price": "49.99", "currency": "USD", "price_verified": True}))
    values = fields(payload)
    assert values["🌍 Región"] == "Estados Unidos"
    assert values["💶 Precio observado"] == "49.99 USD"
    assert "EUR" not in json.dumps(payload)


@pytest.mark.parametrize("tcg", ["one_piece", "pokemon"])
def test_uncertainty_and_availability_semantics_override_brand_color(tcg):
    uncertain = discord_payload(event(tcg, event_type="change.uncertain"))["embeds"][0]
    assert uncertain["color"] == 0xF59E0B
    unavailable = discord_payload(event(tcg, event_type="availability.changed", kind="product", state="UNAVAILABLE",
                                         data={"availability_verified": True}))["embeds"][0]
    assert unavailable["color"] == 0xF87171


@pytest.mark.parametrize("tcg", ["one_piece", "pokemon"])
def test_date_change_keeps_event_style_and_game_identity(tcg):
    payload = discord_payload(event(tcg, event_type="release_date.changed"))
    assert payload["embeds"][0]["author"]["name"] == "🗓️ Cambio de fecha"
    assert payload["embeds"][0]["color"] == 0xFBBF24
    assert "🃏 Juego" in fields(payload)


def test_model_cannot_switch_the_game_region_or_language():
    sample = event("pokemon", region="US", language="en", analysis={"task": "classification", "result": {
        "tcg": "magic", "region": "EU", "language": "es", "summary": "@everyone https://evil.test", "needs_review": False}})
    payload = discord_payload(sample)
    values = fields(payload)
    assert values["🃏 Juego"] == "Pokémon TCG"
    assert values["🌍 Región"] == "Estados Unidos"
    assert values["🌐 Idioma de la fuente"] == "Inglés"
    assert "evil.test" not in json.dumps(payload)
    assert payload["allowed_mentions"]["parse"] == []


@pytest.mark.parametrize("source,label", [
    ("one_piece_news", "One Piece · Noticias oficiales"),
    ("one_piece_products", "One Piece · Catálogo oficial"),
    ("pokemon_products_es", "Pokémon TCG · Galería oficial en español"),
    ("pokemon_tcg_news_es", "Pokémon TCG · Noticias oficiales en español"),
    ("pokemon_press_es", "Pokémon · Prensa oficial en español"),
    ("pokemon_products_us", "Pokémon TCG · Galería oficial de Estados Unidos"),
    ("pokemon_news_jp", "Pokémon Card Game · Noticias oficiales de Japón"),
])
def test_new_sources_have_legible_labels(source, label):
    assert fields(discord_payload(event(source=source)))["📡 Fuente"] == label


def test_multigame_payloads_keep_discord_character_limits_and_safe_mentions():
    sample = event("pokemon", source="@everyone " + "x" * 3000, data={"summary": "🚀" * 10000})
    sample.title = "@everyone **" + "🚀" * 5000
    payload = discord_payload(sample)
    embed = payload["embeds"][0]
    units = lambda value: len(value.encode("utf-16-le")) // 2
    assert units(embed["title"]) <= 256
    assert units(embed["description"]) <= 4096
    assert len(embed["fields"]) <= 25
    assert all(units(field["name"]) <= 256 and units(field["value"]) <= 1024 for field in embed["fields"])
    total = sum(units(value) for value in [embed["title"], embed["description"], embed["author"]["name"], embed["footer"]["text"],
                                          *(part for field in embed["fields"] for part in (field["name"], field["value"]))])
    assert total <= 6000
    assert "@everyone" not in json.dumps(payload, ensure_ascii=False)


def scheduled_event(**extra_data):
    start = "2026-11-08T16:00:00+01:00"
    data = {"event_schedule": normalize_event_schedule(start), "venue": "Tienda de ejemplo",
            "address": "Dirección ficticia", "city": "Madrid", "entry_price": "5.00",
            "entry_currency": "EUR", "entry_price_verified": True, **extra_data}
    sample = event("one_piece", region="ES", language="es", channel="event", source="local_tcg_events_madrid",
                   kind="event", state="SCHEDULED", event_type="event.new", data=data)
    sample.data["current"]["content"] = "Fecha publicada: " + start
    return sample


def test_local_tournament_has_its_own_schedule_venue_and_entry_cost_not_product_availability():
    payload = discord_payload(scheduled_event())
    values = fields(payload)
    assert payload["embeds"][0]["author"]["name"] == "📅 Nuevo evento"
    assert values["📍 Estado"] == "Programado"
    assert "08/11/2026 · 16:00 CET" in values["📅 Fecha del evento"]
    assert "Madrid" in values["📍 Lugar"] and "Tienda de ejemplo" in values["📍 Lugar"]
    assert values["🎟️ Inscripción"] == "5.00 EUR"
    assert "📦 Disponibilidad" not in values
    assert "💶 Precio observado" not in values
    assert not any("prevista" in name or "previsto" in name for name in values)
    assert "Abrir evento" in values["🔗 Detalles"]


def test_unverified_entry_cost_is_hidden_even_if_a_product_price_was_supplied():
    values = fields(discord_payload(scheduled_event(entry_price_verified=False, price="39.99", currency="EUR", price_verified=True)))
    assert "🎟️ Inscripción" not in values and "💶 Precio observado" not in values


def test_event_without_exact_schedule_can_show_literal_period_without_calling_it_drop_sale():
    period = "November 20 – December 17, 2026"
    sample = event("one_piece", kind="event", state="ANNOUNCED", source="one_piece_news", event_type="event.new",
                   data={"event_period_text": period})
    sample.data["current"]["content"] = "Official event period: " + period
    values = fields(discord_payload(sample))
    assert values["📅 Período publicado del evento"] == period
    assert not any("prevista" in name or "previsto" in name for name in values)


def test_model_cannot_supply_tournament_date_or_convert_ticket_opening_to_a_drop():
    sample = event("pokemon", kind="event", state="SCHEDULED", event_type="event.new",
                   analysis={"task": "release_schedule", "result": {"date": "2099-01-01", "needs_review": False}})
    sample.data["current"]["content"] = "Tickets available November 2, 2026."
    payload = discord_payload(sample)
    assert fields(payload)["📅 Fecha del evento"] == "Fecha u horario por confirmar"
    assert "2099" not in json.dumps(payload)
    assert not any("prevista" in name or "previsto" in name for name in fields(payload))


def test_cancelled_tournament_is_red_and_never_marked_unavailable_product():
    sample = scheduled_event()
    sample.event_type = "event.cancelled"
    sample.data["current"]["state"] = "CANCELLED"
    payload = discord_payload(sample)
    assert payload["embeds"][0]["color"] == 0xF87171
    assert fields(payload)["📍 Estado"] == "Cancelado"
    assert "📦 Disponibilidad" not in fields(payload)


def test_date_only_event_does_not_invent_midnight_or_venue_hours():
    sample = scheduled_event(event_schedule=normalize_event_schedule("2026-11-08"))
    sample.data["current"]["content"] = "Fecha publicada: 2026-11-08"
    value = fields(discord_payload(sample))["📅 Fecha del evento"]
    assert "08/11/2026" in value and "hora sin confirmar" in value
    assert "00:00" not in value
