"""Discord rendering keeps a clear separation between source facts and AI proposals."""
import json
from dataclasses import asdict

import pytest

from drop_alerts.models import Event, Item
from drop_alerts.notifications import discord_payload


def event(kind="announcement", state="ANNOUNCED", source="secret_lair_bluesky", data=None, event_type="announcement.new", previous=None):
    item = Item("example", source, "Ejemplo: un próximo Secret Lair", "https://secretlair.wizards.com/eu/", kind, state,
                {"summary": "Ejemplo ficticio. La fuente anuncia un próximo lanzamiento; consulta sus condiciones.",
                 "availability_verified": False, **(data or {})})
    return Event("preview-example-id", source, item.id, event_type, "2026-10-21T20:00:00+00:00", item.title, item.url, "digest",
                 {"current": asdict(item), "previous": asdict(previous) if previous else None})


def fields(embed):
    return {field["name"]: field["value"] for field in embed["fields"]}


def test_announcement_has_its_own_style_and_is_not_stock_uncertainty():
    embed = discord_payload(event())["embeds"][0]
    encoded = json.dumps(embed, ensure_ascii=False)
    assert embed["author"]["name"] == "📣 Nuevo anuncio"
    assert embed["color"] == 0x9B6DFF
    assert "Bluesky oficial" in encoded
    assert "incierta" not in encoded
    assert "📦 Disponibilidad" not in fields(embed)
    assert fields(embed)["📍 Estado"] == "Anunciado"
    assert "21/10/2026 · 22:00 CEST" in encoded
    assert "Abrir anuncio ↗" in encoded


def test_editorial_unknown_does_not_pretend_missing_stock_is_a_problem():
    embed = discord_payload(event(state="UNKNOWN"))["embeds"][0]
    assert embed["color"] == 0x9B6DFF
    assert "incierta" not in embed["description"]
    assert "📍 Estado" not in fields(embed)


def test_real_product_uncertainty_and_explicit_uncertain_events_are_visible():
    product = discord_payload(event(kind="product", state="UNKNOWN", event_type="product.new"))["embeds"][0]
    change = discord_payload(event(event_type="change.uncertain"))["embeds"][0]
    assert product["color"] == change["color"] == 0xF59E0B
    assert "incierta" in product["description"] and "incierta" in change["description"]


def test_verified_changes_show_translated_states_and_source_prices():
    old = Item("example", "secret_lair_eu", "Un producto", "https://secretlair.wizards.com/eu/", "product", "UNAVAILABLE",
               {"price": "49.99", "currency": "EUR", "price_verified": True, "availability_verified": True})
    availability = event("product", "AVAILABLE", "secret_lair_eu", {"price": "39.99", "currency": "EUR", "price_verified": True,
                          "availability_verified": True}, "availability.changed", old)
    rendered = fields(discord_payload(availability)["embeds"][0])
    assert rendered["📦 Disponibilidad"] == "No disponible → Disponible"
    assert rendered["💶 Precio observado"] == "39.99 EUR"
    availability.event_type = "price.changed"
    assert fields(discord_payload(availability)["embeds"][0])["💶 Precio observado"] == "49.99 EUR → 39.99 EUR"


def test_explicit_unverified_commercial_data_and_model_claims_are_hidden():
    sample = event("product", "AVAILABLE", data={"price": "39.99", "currency": "EUR", "price_verified": False})
    sample.analysis = {"task": "classification", "result": {"summary": "Compra en https://evil.test", "price": 999,
                       "availability": "AVAILABLE", "category": "[clic](https://evil.test)", "needs_review": True}}
    payload = discord_payload(sample)
    encoded = json.dumps(payload, ensure_ascii=False)
    assert "evil.test" not in encoded and "999" not in encoded and "39.99" not in encoded
    assert "📦 Disponibilidad" not in fields(payload["embeds"][0])
    assert "sin verificar" in encoded and "incierta" in encoded


def test_untrusted_mentions_markdown_and_links_are_neutralized():
    sample = event(data={"summary": "@everyone @here <@123> **urgente** [comprar](https://evil.test)"})
    sample.title = "@everyone **NUEVO** [sitio](https://evil.test)"
    payload = discord_payload(sample)
    encoded = json.dumps(payload, ensure_ascii=False)
    assert "@everyone" not in encoded and "@here" not in encoded and "<@123>" not in encoded
    assert payload["allowed_mentions"] == {"parse": [], "users": [], "roles": [], "replied_user": False}
    assert "[comprar](https://evil.test)" not in payload["embeds"][0]["description"]
    assert payload["embeds"][0]["url"] == sample.url


@pytest.mark.parametrize("image_url,verified,shown", [
    ("https://images.wizards.com/example.jpg", True, True),
    ("https://images.wizards.com/example.jpg", False, False),
    ("https://images.wizards.com/example.jpg", None, False),
    ("javascript:alert(1)", True, False),
    ("https://user:secret@images.wizards.com/example.jpg", True, False),
    ("https://images.wizards.com/image\n.jpg", True, False),
])
def test_images_require_an_explicit_adapter_flag_and_a_safe_url(image_url, verified, shown):
    embed = discord_payload(event(data={"image_url": image_url, "image_verified": verified}))["embeds"][0]
    assert ("image" in embed) is shown
    if shown:
        assert embed["image"]["url"] == image_url


@pytest.mark.parametrize("price", ["NaN", "Infinity", "-1", "1000000001", "1e-1000000", "not a number"])
def test_invalid_prices_are_not_rendered(price):
    embed = discord_payload(event(data={"price": price, "currency": "EUR", "price_verified": True}))["embeds"][0]
    assert "💶 Precio observado" not in fields(embed)


def test_generic_events_remain_supported_and_all_embed_limits_hold():
    sample = event(kind="release", state="published", source="software_releases", event_type="release.published",
                   data={"summary": "🚀" * 15000, "region": "🌍" * 2000})
    sample.title = "🚀" * 2000
    sample.event_type = "🚀" * 2000
    embed = discord_payload(sample)["embeds"][0]
    units = lambda value: len(value.encode("utf-16-le")) // 2
    assert units(embed["title"]) <= 256 and units(embed["description"]) <= 4096
    assert units(embed["author"]["name"]) <= 256
    assert len(embed["fields"]) <= 25
    assert all(units(field["name"]) <= 256 and units(field["value"]) <= 1024 for field in embed["fields"])
    total = sum(units(value) for value in [embed["title"], embed["description"], embed["author"]["name"], embed["footer"]["text"],
                                          *(part for field in embed["fields"] for part in (field["name"], field["value"]))])
    assert total <= 6000
    assert "software" in str(embed)


def test_long_url_keeps_the_title_link_without_truncating_markdown_into_a_bad_link():
    sample = event()
    sample.url = "https://official.test/" + "a" * 1500
    embed = discord_payload(sample)["embeds"][0]
    assert embed["url"] == sample.url
    assert fields(embed)["🔗 Detalles"] == "Pulsa el título para consultar la fuente."


@pytest.mark.parametrize("source,label", [
    ("weekly_mtg", "WeeklyMTG · YouTube oficial"),
    ("magicspoiler", "MagicSpoiler · Medio complementario"),
    ("mtggoldfish", "MTGGoldfish · Medio complementario"),
    ("mtgdrops", "MTGDrops · Calendario complementario"),
    ("scg_news", "Star City Games · Medio complementario"),
])
def test_additional_feeds_have_clear_human_source_labels(source, label):
    embed = discord_payload(event(source=source))["embeds"][0]
    assert fields(embed)["📡 Fuente"] == label
