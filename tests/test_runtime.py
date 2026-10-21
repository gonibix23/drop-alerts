import asyncio
import json
import time

from drop_alerts.config import Settings
from drop_alerts.detection import DetectionEngine
from drop_alerts.models import ExtractionError, FetchResult, Item
from drop_alerts.rules import RuleEngine
from drop_alerts.runtime import AnalysisWorker, Monitor
from drop_alerts.storage import Store
from drop_alerts.__main__ import health


def config(**overrides):
    values = dict(bootstrap_mode="notify", rules=[{"id": "all"}], llm_enabled=True)
    values.update(overrides)
    return Settings(**values)


def item(source="news", **overrides):
    values = dict(id="one", source=source, title="Secret Lair announced", url="https://official.test/one", kind="article", state="ANNOUNCED", content="Secret Lair announced for next month.")
    values.update(overrides)
    return Item(**values)


class Source:
    def __init__(self, source_id, result=None, error=None):
        self.id, self.result, self.error = source_id, result, error

    async def fetch(self, http):
        if self.error:
            raise self.error
        return self.result


def test_one_source_failure_does_not_block_others_or_replace_state():
    settings = config(llm_enabled=False)
    store = Store(":memory:")
    first = item("broken", kind="product", state="AVAILABLE")
    store.ingest("broken", FetchResult([first]), DetectionEngine(), RuleEngine(settings.rules), settings)
    sources = [Source("broken", error=ExtractionError("changed markup")), Source("healthy", FetchResult([item("healthy")]))]
    asyncio.run(Monitor(settings, store, sources, object()).tick())
    assert store.item("broken", "one")[0].state == "AVAILABLE"
    assert store.item("healthy", "one")[0] is not None
    stats = {row["id"]: row for row in store.stats()["sources"]}
    assert stats["broken"]["failures"] == 1
    assert stats["healthy"]["last_success"]
    assert not store.db.execute("SELECT 1 FROM events WHERE event_type='availability.changed'").fetchone()
    store.close()


def test_ai_offline_deterministic_alert_remains_ready_and_no_duplicate_on_retry():
    settings = config(analysis_max_attempts=2)
    store = Store(":memory:")
    current = item()
    store.ingest("news", FetchResult([current]), DetectionEngine(), RuleEngine(settings.rules), settings)
    original_event = store.due_notifications(10)[0][0]
    calls = []
    class OfflineAnalyzer:
        async def analyze(self, task, content):
            calls.append(task)
            raise TimeoutError("unavailable")
    worker = AnalysisWorker(settings, store, OfflineAnalyzer())
    asyncio.run(worker.tick())
    assert store.due_notifications(10)[0][0].id == original_event.id
    # Simulate time advancing to make the persisted analysis retry due.
    store.db.execute("UPDATE analysis_jobs SET next_attempt=0")
    store.db.commit()
    asyncio.run(worker.tick())
    assert len(calls) == 2
    assert store.db.execute("SELECT status FROM analysis_jobs").fetchone()[0] == "failed"
    store.ingest("news", FetchResult([current]), DetectionEngine(), RuleEngine(settings.rules), settings)
    assert store.db.execute("SELECT count(*) FROM events").fetchone()[0] == 1
    assert store.db.execute("SELECT count(*) FROM outbox").fetchone()[0] == 1
    store.close()


def test_analysis_result_cannot_override_facts_or_resend_delivered_alert():
    settings = config()
    store = Store(":memory:")
    current = item(state="UNKNOWN", data={"price": 39.99, "currency": "EUR"})
    store.ingest("news", FetchResult([current]), DetectionEngine(), RuleEngine(settings.rules), settings)
    event = store.due_notifications(1)[0][0]
    store.notification_result(event.id, 1)
    class Analyzer:
        async def analyze(self, task, content):
            return {"availability": "AVAILABLE", "price": 1, "title": "fake", "url": "https://evil.test"}
    asyncio.run(AnalysisWorker(settings, store, Analyzer()).tick())
    observed = store.item("news", "one")[0]
    assert observed.state == "UNKNOWN" and observed.title == current.title
    assert observed.data["price"] == 39.99 and observed.url == current.url
    payload = json.loads(store.db.execute("SELECT payload FROM events").fetchone()[0])
    assert payload["data"]["current"]["state"] == "UNKNOWN"
    assert payload["analysis"]["verified"] is False
    assert not store.due_notifications(10)
    assert store.db.execute("SELECT count(*) FROM outbox").fetchone()[0] == 1
    store.close()


def test_strict_semantic_rule_waits_and_fails_without_false_alert():
    settings = config(rules=[{"id": "semantic", "require_analysis": True}], analysis_max_attempts=1)
    store = Store(":memory:")
    store.ingest("news", FetchResult([item()]), DetectionEngine(), RuleEngine(settings.rules), settings)
    assert not store.due_notifications(10)
    class Offline:
        async def analyze(self, task, content):
            return None
    asyncio.run(AnalysisWorker(settings, store, Offline()).tick())
    assert not store.due_notifications(10)
    assert store.db.execute("SELECT status,last_error FROM outbox").fetchone()[0] == "dead"
    store.close()


def test_pending_analysis_survives_restart(tmp_path):
    settings = config()
    path = str(tmp_path / "alerts.db")
    store = Store(path)
    store.ingest("news", FetchResult([item()]), DetectionEngine(), RuleEngine(settings.rules), settings)
    job_id = store.due_analysis(1)[0]["id"]
    store.close()
    reopened = Store(path)
    assert reopened.due_analysis(1)[0]["id"] == job_id
    reopened.close()


def test_secret_settings_repr_and_startup_error_do_not_print_secrets(monkeypatch, capsys):
    from drop_alerts.__main__ import main
    settings = config(llm_api_key="private-api-key", discord_webhook_url="https://discord.com/api/webhooks/123/private-webhook-token")
    assert "private" not in repr(settings)
    def invalid_settings():
        raise ValueError("private-api-key private-webhook-token")
    monkeypatch.setattr("drop_alerts.__main__.Settings.from_env", invalid_settings)
    monkeypatch.setattr("sys.argv", ["drop-alerts", "status"])
    assert main() == 2
    output = capsys.readouterr()
    assert "private" not in output.out + output.err
    assert "ValueError" in output.err


def test_health_reads_configured_heartbeat_and_rejects_stale_or_malformed(tmp_path):
    path = tmp_path / "custom-heartbeat.json"
    settings = config(heartbeat_path=str(path))
    assert not health(settings)
    path.write_text(json.dumps({"timestamp": time.time()}), encoding="utf-8")
    assert health(settings)
    for contents in (json.dumps({"timestamp": time.time() - 120}), "not JSON", '{"timestamp": "not-a-number"}', '{}'):
        path.write_text(contents, encoding="utf-8")
        assert not health(settings)


def test_stale_analysis_changes_only_its_historical_event():
    settings = config()
    store = Store(":memory:")
    earlier = item(state="ANNOUNCED", content="Secret Lair announced.")
    store.ingest("news", FetchResult([earlier]), DetectionEngine(), RuleEngine(settings.rules), settings)
    old_job = store.due_analysis(1)[0]
    earlier_event_id = store.due_notifications(1)[0][0].id
    newer = item(state="AVAILABLE", content="Secret Lair available now.")
    store.ingest("news", FetchResult([newer]), DetectionEngine(), RuleEngine(settings.rules), settings)
    store.finish_analysis(old_job, {"availability": "UNAVAILABLE", "summary": "Older interpretation"}, 3)
    assert store.item("news", "one")[0].state == "AVAILABLE"
    events = store.db.execute("SELECT id,payload FROM events ORDER BY created").fetchall()
    assert len(events) == 2
    old_payload = json.loads(next(row["payload"] for row in events if row["id"] == earlier_event_id))
    current_payload = json.loads(next(row["payload"] for row in events if row["id"] != earlier_event_id))
    assert old_payload["analysis"]["result"]["availability"] == "UNAVAILABLE"
    assert current_payload["analysis"] is None
    assert current_payload["data"]["current"]["state"] == "AVAILABLE"
    assert store.db.execute("SELECT count(*) FROM outbox").fetchone()[0] == 2
    store.close()
