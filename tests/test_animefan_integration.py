from dataclasses import asdict

import httpx
import pytest

from drop_alerts.config import Settings
from drop_alerts.detection import DetectionEngine
from drop_alerts.inspection import select_events
from drop_alerts.models import FetchResult, Item
from drop_alerts.notifications import DiscordChannel, NotificationWorker, discord_payload
from drop_alerts.profiles import event_profile
from drop_alerts.registry import build_sources
from drop_alerts.rules import RuleEngine
from drop_alerts.storage import Store


def figure(identity="figure-one", **data):
    return Item(identity, "animefan", "Figura One Piece", f"https://animefan.es/tienda/coleccion/one-piece/{identity}/",
                kind="product", state="AVAILABLE", data={"domain": "collectibles", "product_category": "figure",
                "franchise": "One Piece", "price": "99.00", "currency": "EUR", "price_verified": True,
                "availability_verified": True, **data}, content="Figura con existencias indicadas por la tienda.")


def ingest(store, config, current):
    store.ingest("animefan", FetchResult([current]), DetectionEngine(), RuleEngine(config.rules), config)


def test_source_scope_defaults_to_cards_and_passes_explicit_collectibles_setting():
    settings = Settings.from_env({})
    source = next(source for source in build_sources(settings, None) if source.id == "animefan")
    assert source.include_collectibles is False
    settings.sources["animefan"]["include_collectibles"] = True
    source = next(source for source in build_sources(settings, None) if source.id == "animefan")
    assert source.include_collectibles is True


@pytest.mark.parametrize("value", ['"true"', "1", "[]", "{}", "0.0"])
def test_collectibles_setting_requires_boolean_in_toml(tmp_path, value):
    path = tmp_path / "config.toml"
    path.write_text('[sources.animefan]\ninclude_collectibles=' + value + '\n', encoding="utf-8")
    with pytest.raises(ValueError, match="include_collectibles"):
        Settings.from_env({"CONFIG_PATH": str(path)})


def test_collectibles_option_cannot_silently_enable_scope_on_other_sources(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[sources.jjcollection]\ninclude_collectibles=true\n', encoding="utf-8")
    with pytest.raises(ValueError, match="fuente"):
        Settings.from_env({"CONFIG_PATH": str(path)})


def test_optional_figure_is_not_notified_or_mislabelled_as_a_card_game():
    config = Settings(llm_enabled=False, bootstrap_mode="notify")
    store = Store(":memory:")
    current = figure()
    ingest(store, config, current)
    assert event_profile(asdict(current)).get("tcg") is None
    assert not store.due_notifications(10)
    event = DetectionEngine().detect(current, None, 1)[0]
    fields = {row["name"]: row["value"] for row in discord_payload(event)["embeds"][0]["fields"]}
    assert "🃏 Juego" not in fields
    assert fields["🗂️ Tipo de producto"] == "Figura"
    assert fields["🎬 Franquicia"] == "One Piece"
    store.close()


def test_real_card_products_follow_game_selection_while_opted_in_figures_are_independent():
    config = Settings(llm_enabled=False, bootstrap_mode="notify", enabled_tcgs=["pokemon"])
    config.sources["animefan"]["include_collectibles"] = True
    store = Store(":memory:")
    ingest(store, config, figure())
    for game in ("pokemon", "one_piece"):
        current = figure(game, domain="tcg", product_category="cards", tcg=game)
        current.title = "Caja de cartas " + game
        ingest(store, config, current)
    events = [row[0] for row in store.due_notifications(10)]
    assert {row.item_id for row in events} == {"figure-one", "pokemon"}
    store.close()


@pytest.mark.asyncio
async def test_turning_off_collectibles_closes_pending_delivery_and_hides_manual_preview(tmp_path):
    config = Settings(llm_enabled=False, bootstrap_mode="notify", database_path=str(tmp_path / "events.db"),
                      discord_webhook_url="https://discord.com/api/webhooks/123/test-token")
    config.sources["animefan"]["include_collectibles"] = True
    store = Store(config.database_path)
    ingest(store, config, figure())
    event = store.due_notifications(1)[0][0]
    assert len(select_events(config, source="animefan")) == 1
    config.sources["animefan"]["include_collectibles"] = False
    assert select_events(config, source="animefan") == []
    calls = []
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: calls.append(request) or httpx.Response(204))) as client:
        worker = NotificationWorker(config, store, DiscordChannel(config, store, client))
        await worker.tick()
        config.sources["animefan"]["include_collectibles"] = True
        await worker.tick()
    assert not calls
    row = store.db.execute("SELECT status,attempts FROM outbox WHERE event_id=?", (event.id,)).fetchone()
    assert tuple(row) == ("skipped", 0)
    store.close()


def test_collectible_metadata_is_escaped_and_malformed_category_cannot_break_rendering():
    current = figure(franchise="@everyone [Aviso](https://evil.test)", product_category={"bad": "value"})
    event = DetectionEngine().detect(current, None, 1)[0]
    payload = discord_payload(event)
    fields = {row["name"]: row["value"] for row in payload["embeds"][0]["fields"]}
    assert fields["🗂️ Tipo de producto"] == "Coleccionable"
    assert "@everyone" not in fields["🎬 Franquicia"]
    assert payload["allowed_mentions"]["parse"] == []
