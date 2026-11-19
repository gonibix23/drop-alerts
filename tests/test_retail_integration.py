"""Retail adapters share durable detection without sharing a shop's inventory."""
from dataclasses import asdict

import pytest

from drop_alerts.config import Settings
from drop_alerts.detection import DetectionEngine
from drop_alerts.models import FetchResult, Item
from drop_alerts.notifications import discord_payload
from drop_alerts.profiles import event_profile
from drop_alerts.registry import build_sources
from drop_alerts.rules import RuleEngine
from drop_alerts.storage import Store


def product(source, *, identity="card-42", state="UNAVAILABLE", price="29.95", tcg="pokemon"):
    host = {"tabletop_gamers": "tabletopgamers.es", "jjcollection": "www.jjcollection.es", "zial_tcg": "www.zialtcg.com"}[source]
    data = {"region": "EU", "country": "ES", "language": "es", "channel": "retail",
            "availability_verified": True, "price_verified": True, "price": price, "currency": "EUR"}
    if tcg is not None:
        data["tcg"] = tcg
    return Item(identity, source, "Caja de cartas · variante español", f"https://{host}/products/card-42",
                kind="product", state=state, data=data, content="Oferta de la tienda.")


def ingest(store, settings, item):
    return store.ingest(item.source, FetchResult([item]), DetectionEngine(), RuleEngine(settings.rules), settings)


@pytest.mark.parametrize("source", ["tabletop_gamers", "jjcollection", "zial_tcg"])
def test_store_bootstrap_restart_restock_and_repeat_are_durable(tmp_path, source):
    config = Settings(llm_enabled=False)
    path = str(tmp_path / "retail.db")
    store = Store(path)
    assert ingest(store, config, product(source)) == 1
    assert not store.due_notifications(10)
    store.close()
    store = Store(path)
    assert ingest(store, config, product(source, state="AVAILABLE")) == 1
    queued = store.due_notifications(10)
    assert len(queued) == 1 and queued[0][0].event_type == "availability.changed"
    store.notification_result(queued[0][0].id, 1)
    store.close()
    store = Store(path)
    assert ingest(store, config, product(source, state="AVAILABLE")) == 0
    assert not store.due_notifications(10)
    assert store.db.execute("SELECT count(*) FROM analysis_jobs").fetchone()[0] == 0
    store.close()


def test_equal_product_names_at_two_shops_keep_independent_stock_and_prices():
    store = Store(":memory:")
    config = Settings(llm_enabled=False, bootstrap_mode="notify")
    ingest(store, config, product("tabletop_gamers", state="AVAILABLE", price="29.95"))
    ingest(store, config, product("jjcollection", state="UNAVAILABLE", price="25.00"))
    events = [row[0] for row in store.due_notifications(10)]
    assert len(events) == 2
    assert {event.source for event in events} == {"tabletop_gamers", "jjcollection"}
    assert {event.data["current"]["state"] for event in events} == {"AVAILABLE", "UNAVAILABLE"}
    store.close()


def test_stock_quantity_wording_does_not_notify_without_a_state_or_price_change():
    store = Store(":memory:")
    config = Settings(llm_enabled=False)
    current = product("tabletop_gamers", state="AVAILABLE")
    current.content = "Solo quedan 3 disponibles"
    ingest(store, config, current)
    current.content = "Solo quedan 2 disponibles"
    assert ingest(store, config, current) == 1  # Retain the observation, without a delivery.
    assert not store.due_notifications(10)
    assert store.db.execute("SELECT count(*) FROM analysis_jobs").fetchone()[0] == 0
    current.data["price"] = "25.00"
    ingest(store, config, current)
    assert store.due_notifications(1)[0][0].event_type == "price.changed"
    store.close()


@pytest.mark.parametrize("source", ["tabletop_gamers", "jjcollection", "zial_tcg"])
def test_retail_preorder_price_and_source_are_rendered_from_verified_data(source):
    store = Store(":memory:")
    config = Settings(llm_enabled=False, bootstrap_mode="notify")
    current = product(source, state="UPCOMING")
    ingest(store, config, current)
    event = store.due_notifications(1)[0][0]
    payload = discord_payload(event)
    fields = {row["name"]: row["value"] for row in payload["embeds"][0]["fields"]}
    assert fields["📦 Disponibilidad"] == "Próximamente"
    assert fields["💶 Precio observado"] == "29.95 EUR"
    assert fields["🃏 Juego"] == "Pokémon TCG"
    assert fields["🌍 Región"] == "Europa"
    assert "Tienda online" in fields["📡 Fuente"]
    assert payload["allowed_mentions"]["parse"] == []
    store.close()


def test_retail_selection_filters_games_but_retains_generic_card_supplies():
    config = Settings(llm_enabled=False, bootstrap_mode="notify", enabled_tcgs=["pokemon"])
    store = Store(":memory:")
    for game in ("pokemon", "one_piece", "riftbound", None):
        ingest(store, config, product("jjcollection", identity=game or "card-sleeves", tcg=game))
    queued = store.due_notifications(10)
    assert {event_profile(row[0].data["current"]).get("tcg") for row in queued} == {"pokemon", None}
    # A mixed retailer is consulted even if only one of its games is selected.
    assert {source.id for source in build_sources(config, store)} >= {"tabletop_gamers", "jjcollection"}
    store.close()


@pytest.mark.parametrize("alias,canonical,label", [("Riftbound", "riftbound", "Riftbound"),
    ("Disney Lorcana", "lorcana", "Disney Lorcana"), ("DragonBall", "dragon_ball", "Dragon Ball"),
    ("Yu-Gi-Oh!", "yugioh", "Yu-Gi-Oh!"), ("SWU", "star_wars_unlimited", "Star Wars: Unlimited"),
    ("Gundam Card Game", "gundam", "Gundam Card Game"),
    ("Jurassic Park TCG", "jurassic_park", "Jurassic Park TCG")])
def test_other_store_games_can_be_selected_and_rendered(alias, canonical, label):
    config = Settings.from_env({"ENABLED_TCGS": alias})
    assert config.enabled_tcgs == [canonical]
    current = product("tabletop_gamers", tcg=canonical)
    event = DetectionEngine().detect(current, None, 1)[0]
    assert event_profile(asdict(current))["tcg"] == canonical
    values = {row["name"]: row["value"] for row in discord_payload(event)["embeds"][0]["fields"]}
    assert values["🃏 Juego"] == label


def test_custom_configuration_keeps_unlisted_stores_disabled(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[sources.secret_lair_eu]\nenabled=true\n', encoding="utf-8")
    settings = Settings.from_env({"CONFIG_PATH": str(path)})
    assert [source.id for source in build_sources(settings, None)] == ["secret_lair_eu"]
