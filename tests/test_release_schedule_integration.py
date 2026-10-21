from dataclasses import asdict, replace
import json
from pathlib import Path
import time

import pytest

from drop_alerts.config import Settings
from drop_alerts.detection import DetectionEngine
from drop_alerts.models import FetchResult, Item
from drop_alerts.notifications import discord_payload
from drop_alerts.release_dates import extract_release_schedule
from drop_alerts.rules import RuleEngine
from drop_alerts.schedule_enrichment import effective_release_schedule, enrich_item, should_analyze_schedule
from drop_alerts.storage import Store
from drop_alerts.sources.magic_news import MagicNewsSource


def item(content="Secret Lair goes on sale on November 2, 2026 at 9 a.m. PT.", **overrides):
    values = dict(id="example", source="news", title="Secret Lair example", url="https://official.test/example",
                  kind="announcement", state="ANNOUNCED", content=content,
                  data={"published_at": "2026-10-16T16:00:00Z", "availability_verified": False})
    values.update(overrides)
    return Item(**values)


def settings(**overrides):
    values = dict(rules=[{"id": "all"}], bootstrap_mode="notify", llm_enabled=False)
    values.update(overrides)
    return Settings(**values)


def ingest(store, current, config):
    return store.ingest(current.source, FetchResult([current]), DetectionEngine(), RuleEngine(config.rules), config)


def analysis(quote, **overrides):
    result = dict(date_kind="sale", date_quote=quote, evidence=[quote], confidence=0.7, needs_review=False)
    result.update(overrides)
    return {"task": "release_schedule", "engine": "model", "verified": False, "result": result}


def test_extracted_date_persists_and_is_present_in_notification_without_model(tmp_path):
    path = str(tmp_path / "state.db")
    store = Store(path)
    original = item()
    ingest(store, original, settings())
    saved, _ = store.item("news", original.id)
    assert saved.data["release_schedule"]["date"] == "2026-11-02"
    assert saved.state == "ANNOUNCED" and saved.data["availability_verified"] is False
    assert "18:00 CET" in json.dumps(discord_payload(store.due_notifications(1)[0][0]))
    assert not store.due_analysis(10)
    store.close()
    store = Store(path)
    assert ingest(store, item(), settings()) == 0
    assert len(store.due_notifications(10)) == 1
    store.close()


def test_real_saved_article_to_database_and_discord_uses_launch_not_card_legality():
    url = "https://magic.wizards.com/en/news/announcements/secret-lair-countdown-kit-marvels-history-of-heroes"
    current = Item(url, "magic_news", "Countdown Kit", url, kind="article", state="ANNOUNCED")
    body = (Path(__file__).parent / "fixtures/magic_expansion_countdown.html").read_text(encoding="utf-8")
    current = MagicNewsSource().parse_article(body, current)
    store = Store(":memory:")
    ingest(store, current, settings())
    event = store.due_notifications(1)[0][0]
    schedule = event.data["current"]["data"]["release_schedule"]
    assert schedule["date"] == "2026-11-02" and schedule["time"] is None
    rendered = json.dumps(discord_payload(event), ensure_ascii=False)
    assert "02/11/2026" in rendered and "hora sin confirmar" in rendered
    assert event.data["current"]["state"] == "ANNOUNCED"
    store.close()


def test_parser_upgrade_backfills_metadata_without_new_revision_or_historical_message():
    store = Store(":memory:")
    current = item()
    config = settings(bootstrap_mode="silent")
    ingest(store, current, config)
    saved, revision = store.item("news", current.id)
    saved.data.pop("release_schedule")
    saved.data.pop("release_schedule_version")
    store.db.execute("UPDATE items SET payload=?", (json.dumps(asdict(saved)),))
    store.db.commit()
    assert ingest(store, item(), config) == 0
    refreshed, new_revision = store.item("news", current.id)
    assert refreshed.data["release_schedule"]["date"] == "2026-11-02"
    assert new_revision == revision
    assert not store.due_notifications(10)
    assert store.db.execute("SELECT count(*) FROM events").fetchone()[0] == 1


def test_real_reschedule_has_one_date_event_and_does_not_change_stock():
    store = Store(":memory:")
    config = settings()
    ingest(store, item(), config)
    old_event = store.due_notifications(1)[0][0]
    store.notification_result(old_event.id, 1)
    moved = item("Secret Lair goes on sale on November 9, 2026 at 9 a.m. PT.")
    assert ingest(store, moved, config) == 1
    event = store.due_notifications(1)[0][0]
    assert event.event_type == "release_date.changed"
    assert event.data["current"]["state"] == event.data["previous"]["state"] == "ANNOUNCED"
    rendered = json.dumps(discord_payload(event), ensure_ascii=False)
    assert "02/11/2026" in rendered and "09/11/2026" in rendered and "→" in rendered
    assert ingest(store, item(moved.content), config) == 0


def test_parser_alone_never_changes_event_identity_or_turns_unknown_into_availability():
    original = item("Coming soon.")
    before = original.digest
    enrich_item(original)
    assert original.digest == before
    assert original.data["release_schedule"]["certainty"] == "unknown"
    assert original.state == "ANNOUNCED"


def test_publication_year_metadata_correction_is_not_a_categorical_reschedule():
    old = item("Available November 2.")
    new = item("Available November 2.", data={**old.data, "published_at": "2027-10-16T16:00:00Z"})
    assert "release_date.changed" not in {event.event_type for event in DetectionEngine().detect(new, old, 2)}


def test_same_calendar_date_reclassified_as_sale_is_information_not_rescheduling():
    old = item("Secret Lair launches on November 2, 2026.")
    new = item("Secret Lair goes on sale on November 2, 2026.")
    assert [event.event_type for event in DetectionEngine().detect(new, old, 2)] == ["content.changed"]


def test_equivalent_explicit_timezone_names_do_not_create_fake_reschedule():
    old = item("Secret Lair goes on sale on November 2, 2026 at 9 a.m. PT.")
    new = item("Secret Lair goes on sale on November 2, 2026 at 9 a.m. PST.")
    assert [event.event_type for event in DetectionEngine().detect(new, old, 2)] == ["content.changed"]


@pytest.mark.parametrize("text,published", [
    ("Coming soon.", "2026-10-16"),
    ("Available November 2.", None),
    ("Orders ship on November 2, 2026.", "2026-10-16"),
    ("Available November 2, 2026. Available November 9, 2026.", "2026-10-16"),
])
def test_model_does_not_receive_undated_or_explicitly_conflicting_source(text, published):
    current = item(text, data={"published_at": published})
    enrich_item(current)
    assert not should_analyze_schedule(current)


def test_model_cannot_replace_known_date_or_resolve_actual_source_contradiction():
    current = asdict(item())
    proposed = analysis("Available November 9, 2026.")
    assert effective_release_schedule(current, proposed)["date"] == "2026-11-02"
    content = "Available November 2, 2026. Available November 9, 2026."
    assert effective_release_schedule(asdict(item(content)), analysis("Available November 9, 2026."))["certainty"] == "conflicting"


def test_model_cannot_turn_shipping_legality_or_negated_quote_into_sale_date():
    for text, quote in [
        ("Orders ship on November 2, 2026.", "November 2, 2026"),
        ("Cards become legal on April 2, 2027.", "April 2, 2027"),
        ("Not available November 2, 2026.", "available November 2, 2026"),
    ]:
        assert effective_release_schedule(asdict(item(text)), analysis(quote))["date"] is None


def test_semantic_help_can_classify_a_literal_date_without_claiming_verified_sale():
    text = "The purchasing window: November 2, 2026."
    current = item(text)
    enrich_item(current)
    assert current.data["release_schedule"]["date"] is None
    assert should_analyze_schedule(current)
    effective = effective_release_schedule(asdict(current), analysis(text))
    assert effective["date"] == "2026-11-02"
    assert effective["certainty"] == "estimated" and effective["engine"] == "model"
    assert current.data["release_schedule"]["date"] is None
    assert current.state == "ANNOUNCED" and current.data["availability_verified"] is False


def test_optional_date_analysis_gets_one_slot_and_timeout_falls_back(monkeypatch):
    monkeypatch.setattr("drop_alerts.storage.should_analyze_schedule", lambda current: True)
    store = Store(":memory:")
    config = settings(llm_enabled=True, llm_timeout_seconds=45)
    before = time.time()
    ingest(store, item("Coming soon."), config)
    jobs = store.due_analysis(100)
    assert len(jobs) == 1 and jobs[0]["task"] == "release_schedule"
    row = store.db.execute("SELECT next_attempt,status FROM outbox").fetchone()
    assert row["status"] == "pending" and before < row["next_attempt"] <= time.time() + 60
    assert not store.due_notifications(1)
    # A hung/busy model cannot hold the notification past the grace deadline.
    store.db.execute("UPDATE outbox SET next_attempt=?", (time.time() - 1,))
    store.db.commit()
    event = store.due_notifications(1)[0][0]
    assert "Sin fecha confirmada" in json.dumps(discord_payload(event), ensure_ascii=False)
    assert event.data["current"]["state"] == "ANNOUNCED"


def test_ai_failure_releases_fallback_and_late_success_cannot_resend_or_reset_discord_backoff(monkeypatch):
    monkeypatch.setattr("drop_alerts.storage.should_analyze_schedule", lambda current: True)
    store = Store(":memory:")
    config = settings(llm_enabled=True)
    ingest(store, item("Coming soon."), config)
    job = store.due_analysis(1)[0]
    store.finish_analysis(job, None, 3)
    event = store.due_notifications(1)[0][0]
    store.notification_result(event.id, 1, "discord_429", retry_after=60)
    retry_at = store.db.execute("SELECT next_attempt FROM outbox").fetchone()[0]
    result = analysis(None, date_kind="unknown", evidence=[], needs_review=True, confidence=0.2)["result"]
    store.finish_analysis(job, result, 3)
    assert store.db.execute("SELECT next_attempt FROM outbox").fetchone()[0] == retry_at
    store.notification_result(event.id, 2)
    store.finish_analysis(job, result, 3)
    assert not store.due_notifications(10)
    assert store.db.execute("SELECT count(*) FROM outbox").fetchone()[0] == 1


def test_strict_analysis_rule_does_not_gain_optional_timeout_fallback(monkeypatch):
    monkeypatch.setattr("drop_alerts.storage.should_analyze_schedule", lambda current: True)
    store = Store(":memory:")
    config = settings(llm_enabled=True, rules=[{"id": "strict", "require_analysis": True}])
    ingest(store, item("Coming soon."), config)
    job = store.due_analysis(1)[0]
    store.finish_analysis(job, None, 1)
    assert store.db.execute("SELECT status FROM outbox").fetchone()[0] == "dead"
    assert not store.due_notifications(10)
