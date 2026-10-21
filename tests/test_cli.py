import json
import time
from types import SimpleNamespace

import httpx
import pytest

from drop_alerts.__main__ import health
from drop_alerts.lock import ProcessLock


def test_health_rejects_missing_stale_and_future_heartbeat(tmp_path):
    path = tmp_path / "health.json"
    settings = SimpleNamespace(heartbeat_path=str(path))
    assert not health(settings)
    for timestamp in (time.time() - 100, time.time() + 100):
        path.write_text(json.dumps({"timestamp": timestamp}))
        assert not health(settings)
    path.write_text(json.dumps({"timestamp": time.time()}))
    assert health(settings)


def test_singleton_lock_releases_for_next_process(tmp_path):
    path = str(tmp_path / "db")
    with ProcessLock(path):
        with pytest.raises(RuntimeError):
            with ProcessLock(path):
                pass
    with ProcessLock(path):
        pass


@pytest.mark.asyncio
async def test_model_probe_does_not_open_service_database_or_send_notifications(monkeypatch, capsys):
    from drop_alerts.__main__ import check_llm
    from drop_alerts.config import Settings
    import drop_alerts.ai
    class FakeAnalyzer:
        def __init__(self, settings, store, client):
            assert store.db.execute("PRAGMA database_list").fetchone()[2] == ""
        async def analyze(self, task, content):
            assert task == "classification"
            assert "Secret Lair" in content
            return {"category": "announcement", "needs_review": True}
    monkeypatch.setattr(drop_alerts.ai, "LLMAnalyzer", FakeAnalyzer)
    assert await check_llm(Settings()) == 0
    assert json.loads(capsys.readouterr().out)["analysis_valid"] is True
