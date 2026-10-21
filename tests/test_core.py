from dataclasses import replace
import json
import time

import pytest

from drop_alerts.config import Settings
from drop_alerts.detection import DetectionEngine
from drop_alerts.models import FetchResult, Item
from drop_alerts.rules import RuleEngine
from drop_alerts.storage import Store


def config(**kwargs):
    return Settings(rules=[{"id": "all"}], llm_enabled=False, **kwargs)


def product(**kwargs):
    fields = dict(id="p1", source="shop", title="Un producto", url="https://example.com/p1", kind="product", state="AVAILABLE", data={"price": "10.00", "currency": "EUR"}, content="Descripción")
    fields.update(kwargs)
    return Item(**fields)


def ingest(store, items, settings=None):
    settings = settings or config()
    return store.ingest(items[0].source, FetchResult(items), DetectionEngine(), RuleEngine(settings.rules), settings)


def test_silent_baseline_then_new_and_restart(tmp_path):
    path = str(tmp_path / "state.db")
    store = Store(path)
    ingest(store, [product()])
    assert store.due_notifications(10) == []
    ingest(store, [product(), product(id="p2")])
    assert len(store.due_notifications(10)) == 1
    event, _ = store.due_notifications(10)[0]
    store.notification_result(event.id, 1)
    store.close()
    store = Store(path)
    assert ingest(store, [product(), product(id="p2")]) == 0
    assert store.due_notifications(10) == []
    store.close()


def test_notify_baseline_and_explicit_price_state_changes():
    store = Store(":memory:")
    settings = config(bootstrap_mode="notify")
    original = product()
    ingest(store, [original], settings)
    changed = replace(original, state="UNAVAILABLE", data={"price": "12.00", "currency": "EUR"})
    assert ingest(store, [changed], settings) == 2
    types = {e.event_type for e, _ in store.due_notifications(10)}
    assert types == {"product.new", "availability.changed", "price.changed"}
    assert ingest(store, [changed], settings) == 0


def test_repeated_real_transition_has_new_identity():
    store = Store(":memory:")
    ingest(store, [product()])
    ingest(store, [product(state="UNAVAILABLE")])
    ingest(store, [product()])
    ingest(store, [product(state="UNAVAILABLE")])
    rows = store.due_notifications(10)
    assert len(rows) == 3
    assert len({e.id for e, _ in rows}) == 3


def test_missing_items_does_not_mean_unavailable():
    store = Store(":memory:")
    ingest(store, [product(), product(id="p2")])
    ingest(store, [product()])
    assert store.item("shop", "p2")[0].state == "AVAILABLE"
    assert store.due_notifications(10) == []


def test_empty_batch_does_not_initialize_or_remove_state():
    store = Store(":memory:")
    with pytest.raises(ValueError):
        store.ingest("shop", FetchResult([]), DetectionEngine(), RuleEngine([]), config())
    assert store.stats()["sources"] == []


def test_failed_batch_rolls_back_items_events_and_outbox():
    class BrokenRules:
        def decide(self, event):
            raise RuntimeError("simulated crash")
    store = Store(":memory:")
    with pytest.raises(RuntimeError):
        store.ingest("shop", FetchResult([product()]), DetectionEngine(), BrokenRules(), config())
    assert store.item("shop", "p1") == (None, 0)
    assert store.db.execute("SELECT count(*) FROM events").fetchone()[0] == 0
    assert store.due_notifications(10) == []


@pytest.mark.parametrize("kind,event_type,state", [("release", "item.new", "STABLE"), ("article", "publication.new", "PUBLISHED"), ("announcement", "announcement.new", "ANNOUNCED"), ("collection", "collection.new", "UPCOMING")])
def test_generic_domains_and_arbitrary_states(kind, event_type, state):
    item = product(source="software", kind=kind, state=state)
    event = DetectionEngine().detect(item, None, 1)[0]
    assert event.event_type == event_type
    assert event.source == "software"
    assert event.data["current"]["state"] == state


def test_unknown_state_not_categorical_availability_change():
    event = DetectionEngine().detect(product(state="UNKNOWN"), product(), 2)[0]
    assert event.event_type == "change.uncertain"


def test_observation_time_is_not_a_change():
    assert product(observed_at="2026-01-01T00:00:00+00:00").digest == product(observed_at="2026-02-01T00:00:00+00:00").digest


def test_price_missing_does_not_invent_price_change():
    events = DetectionEngine().detect(product(data={}), product(), 2)
    assert "price.changed" not in {x.event_type for x in events}


def test_rules_are_explicit_filters_and_case_insensitive_keywords():
    engine = RuleEngine([{"id": "r", "sources": ["shop"], "kinds": ["product"], "keywords": ["SECRET LAIR"], "event_types": ["product.new"], "states": ["AVAILABLE"], "require_analysis": True}])
    event = DetectionEngine().detect(product(title="Secret Lair Example"), None, 1)[0]
    assert engine.decide(event).notify
    assert engine.decide(event).require_analysis
    event.source = "other"
    assert not engine.decide(event).notify


@pytest.mark.parametrize("rules", [[{"id": "x"}, {"id": "x"}], [{"id": "x", "enabled": "yes"}], [{"id": "x", "keywords": "wrong"}], [{"id": "x", "typo": 1}]])
def test_invalid_rules(rules):
    with pytest.raises(ValueError):
        RuleEngine(rules)


def test_retention_keeps_dedup_tombstones_and_pending_payloads():
    store = Store(":memory:")
    ingest(store, [product()], config(bootstrap_mode="notify"))
    event, _ = store.due_notifications(1)[0]
    store.db.execute("UPDATE events SET created=?", (time.time() - 100 * 86400,))
    store.db.commit()
    store.prune(1)
    assert store.due_notifications(1)[0][0].id == event.id
    store.notification_result(event.id, 1)
    store.prune(1)
    row = store.db.execute("SELECT id,payload FROM events").fetchone()
    assert row[0] == event.id and row[1] is None
    assert ingest(store, [product()]) == 0


def test_duplicate_ids_rejected_before_persistence():
    store = Store(":memory:")
    with pytest.raises(ValueError):
        ingest(store, [product(), product()])
    assert not store.get_source_items("shop")


@pytest.mark.parametrize("env", [{"POLL_INTERVAL_SECONDS": "0"}, {"LLM_ENABLED": "maybe"}, {"LLM_MAX_RETRIES": "9"}, {"LLM_TEMPERATURE": "nan"}, {"BOOTSTRAP_MODE": "bad"}, {"LLM_BASE_URL": "ftp://server"}, {"DISCORD_WEBHOOK_URL": "https://example.com/hook"}, {"LLM_BASE_URL": "https://user:pass@example.com/v1"}])
def test_configuration_validation(env):
    with pytest.raises((ValueError, KeyError)):
        Settings.from_env(env)


def test_defaults_and_secret_files(tmp_path):
    path = tmp_path / "key"
    path.write_text("top-secret\n")
    settings = Settings.from_env({"LLM_API_KEY_FILE": str(path)})
    assert settings.llm_api_key == "top-secret"
    assert settings.llm_model == "qwen3:8b-q4_k_m"
    assert "top-secret" not in repr(settings)
    with pytest.raises(ValueError):
        Settings.from_env({"LLM_API_KEY_FILE": str(path), "LLM_API_KEY": "conflicting"})


def test_toml_config_and_unknown_options(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[sources.magic_news]\nenabled=false\n[[rules]]\nid="all"\n', encoding="utf-8")
    settings = Settings.from_env({"CONFIG_PATH": str(path)})
    assert not settings.sources["magic_news"]["enabled"]
    path.write_text('[unknown]\na=1\n')
    with pytest.raises(ValueError):
        Settings.from_env({"CONFIG_PATH": str(path)})


def test_bounded_analysis_backlog_and_required_analysis_disabled():
    settings = Settings(rules=[{"id": "all", "require_analysis": True}], max_pending_analyses=2, bootstrap_mode="notify")
    store = Store(":memory:")
    ingest(store, [product(id=str(n), kind="article") for n in range(4)], settings)
    assert len(store.due_analysis(100)) == 2
    assert store.db.execute("SELECT count(*) FROM outbox WHERE status='dead'").fetchone()[0] == 2
    disabled = Settings(rules=[{"id": "all", "require_analysis": True}], llm_enabled=False, bootstrap_mode="notify")
    ingest(store, [product(id="no-ai")], disabled)
    assert store.db.execute("SELECT last_error FROM outbox ORDER BY rowid DESC LIMIT 1").fetchone()[0] == "analysis_disabled"


def test_http_cache_and_analysis_persist(tmp_path):
    path = str(tmp_path / "db")
    store = Store(path)
    store.set_http_cache("https://example.com", "body", "etag", "date")
    store.set_analysis_cache("hash", {"test": True})
    store.close()
    store = Store(path)
    assert store.get_http_cache("https://example.com")["etag"] == "etag"
    assert store.get_analysis_cache("hash") == {"test": True}
    store.close()


def test_paginated_bootstrap_does_not_notify_existing_items_later():
    store = Store(":memory:")
    settings = config()
    store.ingest("shop", FetchResult([product()], metadata={"bootstrap_ids": ["p1", "p2"]}), DetectionEngine(), RuleEngine(settings.rules), settings)
    ingest(store, [product(id="p2")], settings)
    assert store.due_notifications(10) == []
    ingest(store, [product(id="p2", state="UNAVAILABLE"), product(id="p3")], settings)
    assert {x.event_type for x, _ in store.due_notifications(10)} == {"availability.changed", "product.new"}


def test_recurring_content_analysis_has_new_job_for_each_real_change():
    store = Store(":memory:")
    settings = Settings(rules=[{"id": "all", "require_analysis": True}], bootstrap_mode="notify")
    item_a = product(kind="article", content="a")
    item_b = product(kind="article", content="b")
    ingest(store, [item_a], settings)
    ingest(store, [item_b], settings)
    for job in store.due_analysis(100):
        store.finish_analysis(job, {"needs_review": True}, 3)
    ingest(store, [item_a], settings)
    ingest(store, [item_b], settings)
    assert len(store.due_analysis(100)) == 2


def test_http_cache_bounded_without_losing_item_state():
    store = Store(":memory:")
    ingest(store, [product()])
    for n in range(140):
        store.set_http_cache(f"https://example.com/{n}", "payload")
    assert store.db.execute("SELECT count(*) FROM http_cache").fetchone()[0] == 128
    assert store.get_http_cache("https://example.com/0") is None
    assert store.item("shop", "p1")[0].title == "Un producto"
