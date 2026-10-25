from dataclasses import asdict
import json

import pytest

from drop_alerts.config import Settings
from drop_alerts.detection import DetectionEngine
from drop_alerts.models import FetchResult, Item
from drop_alerts.profiles import event_profile, enrich_game
from drop_alerts.registry import build_sources
from drop_alerts.rules import RuleEngine
from drop_alerts.storage import Store


def item(source="one_piece_products", **overrides):
    values = dict(id="product-one", source=source, title="Anuncio de producto", url="https://en.onepiece-cardgame.com/products/boosters/op-18.php",
                  kind="announcement", state="ANNOUNCED", data={"tcg": "one_piece", "region": "WESTERN", "regions": ["NA", "EU"]})
    values.update(overrides)
    return Item(**values)


def event(current):
    return DetectionEngine().detect(current, None, 1)[0]


def test_global_game_selection_builds_only_selected_game_and_mixed_calendars():
    config = Settings.from_env({"ENABLED_TCGS": "One Piece, Pokémon"})
    ids = {source.id for source in build_sources(config, None)}
    assert "secret_lair_eu" not in ids and "magic_news" not in ids
    assert {"one_piece_products", "one_piece_news", "pokemon_tcg_news_es", "pokemon_press_es", "local_tcg_events"} <= ids


def test_toml_games_and_environment_override_are_validated(tmp_path):
    path = tmp_path / "games.toml"
    path.write_text('[games]\nenabled=["pokemon"]\n[sources.pokemon_press_es]\nenabled=true\n', encoding="utf-8")
    config = Settings.from_env({"CONFIG_PATH": str(path)})
    assert config.enabled_tcgs == ["pokemon"]
    assert [source.id for source in build_sources(config, None)] == ["pokemon_press_es"]
    assert Settings.from_env({"CONFIG_PATH": str(path), "ENABLED_TCGS": "magic"}).enabled_tcgs == ["magic"]
    path.write_text('[games]\nenabled="pokemon"\n', encoding="utf-8")
    with pytest.raises(ValueError):
        Settings.from_env({"CONFIG_PATH": str(path)})


def test_filters_combine_tcg_region_city_channel_and_preserve_generic_domain_rules():
    current = item(data={"tcg": "one_piece", "region": "EU", "country": "ES", "city": "Alcalá de Henares", "channel": "event"}, kind="event")
    rule = {"id": "nearby", "tcgs": ["one piece"], "regions": ["EU"], "cities": ["alcala de henares"], "channels": ["event"]}
    assert RuleEngine([rule]).decide(event(current)).notify
    assert not RuleEngine([{**rule, "tcgs": ["pokemon"]}]).decide(event(current)).notify
    assert not RuleEngine([{**rule, "regions": ["JP"]}]).decide(event(current)).notify
    assert not RuleEngine([{**rule, "cities": ["Madrid"]}]).decide(event(current)).notify
    software = item(source="software", kind="release", data={}, url="https://example.com/release")
    assert RuleEngine([{"id": "generic"}]).decide(event(software)).notify
    assert "tcg" not in event_profile(asdict(software))


def test_language_does_not_create_european_stock_or_sales_region():
    spanish = item(source="pokemon_press_es", data={"tcg": "pokemon", "language": "es", "region": "GLOBAL"})
    assert event_profile(asdict(spanish))["region"] == "GLOBAL"
    assert not RuleEngine([{"id": "eu", "regions": ["EU"]}]).decide(event(spanish)).notify
    assert RuleEngine([{"id": "eu", "regions": ["EU"]}]).decide(event(item())).notify


def test_primary_region_and_explicit_markets_are_both_filterable():
    current = event(item())
    for region in ("WESTERN", "EU", "NA"):
        assert RuleEngine([{"id": "market", "regions": [region]}]).decide(current).notify
    assert not RuleEngine([{"id": "market", "regions": ["JP"]}]).decide(current).notify


def test_source_identity_cannot_be_relabelled_by_model_or_untrusted_game_metadata():
    current = item(source="secret_lair_eu", data={"tcg": "pokemon"})
    assert event_profile(asdict(current))["tcg"] == "magic"


def test_game_metadata_backfill_is_silent_and_does_not_change_dedup_identity():
    store = Store(":memory:")
    config = Settings(llm_enabled=False, bootstrap_mode="notify", rules=[{"id": "all"}])
    current = item(source="secret_lair_eu", data={})
    before_digest = current.digest
    enrich_game(current)
    assert current.digest == before_digest
    store.ingest(current.source, FetchResult([current]), DetectionEngine(), RuleEngine(config.rules), config)
    first = store.due_notifications(1)[0][0]
    store.notification_result(first.id, 1)
    saved, revision = store.item(current.source, current.id)
    saved.data.pop("tcg")
    store.db.execute("UPDATE items SET payload=?", (json.dumps(asdict(saved)),))
    store.db.commit()
    assert store.ingest(current.source, FetchResult([current]), DetectionEngine(), RuleEngine(config.rules), config) == 0
    assert store.item(current.source, current.id)[0].data["tcg"] == "magic"
    assert store.item(current.source, current.id)[1] == revision
    assert not store.due_notifications(10)


def test_disabled_game_is_persisted_without_dispatch_and_different_regions_do_not_merge():
    store = Store(":memory:")
    config = Settings(llm_enabled=False, bootstrap_mode="notify", enabled_tcgs=["pokemon"], rules=[{"id": "all"}])
    current = item()
    store.ingest(current.source, FetchResult([current]), DetectionEngine(), RuleEngine(config.rules), config)
    assert store.item(current.source, current.id)[0] is not None
    assert not store.due_notifications(10)
    config.enabled_tcgs = ["one_piece"]
    first = event(item(data={"tcg": "one_piece", "region": "US"}))
    second = event(item(data={"tcg": "one_piece", "region": "JP"}))
    assert store.announcement_identity(first) != store.announcement_identity(second)


def test_same_bandai_event_reference_deduplicates_across_calendars(tmp_path):
    store = Store(str(tmp_path / "state.db"))
    config = Settings(llm_enabled=False, bootstrap_mode="notify", rules=[{"id": "all"}])
    reference = "https://www.bandai-tcg-plus.com/event/8110576"
    for source in ("local_tcg_events", "nextdice_events"):
        current = item(source=source, id=source, url=reference, kind="event", state="SCHEDULED",
                       data={"tcg": "one_piece", "region": "EU", "event_reference_url": reference})
        store.ingest(source, FetchResult([current]), DetectionEngine(), RuleEngine(config.rules), config)
    assert len(store.due_notifications(10)) == 1
    assert store.db.execute("SELECT count(*) FROM events").fetchone()[0] == 2
    store.close()
