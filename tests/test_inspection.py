import asyncio
import json
import logging
from pathlib import Path
import sqlite3

import httpx
import pytest

from drop_alerts.config import Settings
from drop_alerts.detection import DetectionEngine
from drop_alerts.inspection import InspectionError, PreviewDelivery, event_record, format_events, inspect_command, preview_payload, select_events, send_preview, tcg_filter
from drop_alerts.models import FetchResult, Item
from drop_alerts.rules import RuleEngine
from drop_alerts.storage import Store


@pytest.fixture
def saved(tmp_path):
    sources = ["magic_news", "one_piece_products", "one_piece_news", "pokemon_tcg_news_es", "pokemon_products_es"]
    config = Settings(database_path=str(tmp_path / "events.db"), llm_enabled=False, bootstrap_mode="silent",
                      discord_webhook_url="https://discord.com/api/webhooks/123/private-webhook-token",
                      sources={name: {"enabled": True} for name in sources}, rules=[{"id": "all"}])
    store = Store(config.database_path)
    values = [
        ("magic_news", "Standard deck strategy", "article", {}),
        ("one_piece_products", "One Piece new booster", "announcement", {"tcg": "pokemon"}),
        ("one_piece_news", "One Piece local event", "event", {"tcg": "one_piece"}),
        ("pokemon_tcg_news_es", "Pokémon nueva colección", "article", {}),
        ("pokemon_products_es", "Pokémon producto", "product", {}),
    ]
    ids = []
    for index, (source, title, kind, data) in enumerate(values):
        current = Item(str(index), source, title, f"https://official.test/{index}", kind=kind, state="ANNOUNCED",
                       data=data, content=title, observed_at=f"2026-10-25T20:0{index}:00+00:00")
        store.ingest(source, FetchResult([current]), DetectionEngine(), RuleEngine(config.rules), config)
        row = store.db.execute("SELECT id FROM events ORDER BY rowid DESC LIMIT 1").fetchone()
        ids.append(row[0])
        store.db.execute("UPDATE events SET created=? WHERE id=?", (index + 1, row[0]))
        store.db.commit()
    assert not store.due_notifications(100)
    store.close()
    return config, ids


def snapshot(path):
    db = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
    try:
        return "\n".join(db.iterdump())
    finally:
        db.close()


def test_latest_matching_game_and_kind_respects_registered_game_identity(saved):
    config, ids = saved
    records = select_events(config, tcg="ONE PIECE", limit=10)
    assert [event.id for event in records] == [ids[2], ids[1]]
    assert event_record(records[1])["tcg"] == "one_piece"
    assert select_events(config, tcg="onepiece", kind="event", limit=1)[0].id == ids[2]
    assert select_events(config, tcg="Pokémon", kind="article", limit=1)[0].id == ids[3]


def test_rule_filter_omits_irrelevant_magic_and_includes_bootstrap_records(saved):
    config, ids = saved
    config.rules = [{"id": "magic", "sources": ["magic_news"], "keywords": ["secret lair"]},
                    {"id": "other", "tcgs": ["one_piece", "pokemon"]}]
    records = select_events(config, limit=100)
    assert len(records) == 4 and ids[0] not in {event.id for event in records}


def test_current_analysis_requirement_hides_unanalyzed_records_and_keeps_completed_results(saved):
    config, ids = saved
    config.rules = [{"id": "all", "require_analysis": True}]
    assert select_events(config, tcg="pokemon") == []
    db = sqlite3.connect(config.database_path)
    raw = db.execute("SELECT payload FROM events WHERE id=?", (ids[3],)).fetchone()[0]
    payload = json.loads(raw)
    payload["analysis"] = {"engine": "model", "task": "classification", "result": {"category": "article", "needs_review": False}, "verified": False}
    db.execute("UPDATE events SET payload=? WHERE id=?", (json.dumps(payload), ids[3]))
    db.commit()
    db.close()
    assert [event.id for event in select_events(config, tcg="pokemon")] == [ids[3]]


def test_disabled_game_and_source_are_not_returned(saved):
    config, ids = saved
    config.sources["one_piece_news"]["enabled"] = False
    assert [event.id for event in select_events(config, tcg="one_piece")] == [ids[1]]
    config.enabled_tcgs = ["magic", "pokemon"]
    assert select_events(config, tcg="one_piece") == []


def test_source_with_implicit_enabled_and_future_game_name_is_supported(saved):
    config, ids = saved
    config.sources["one_piece_news"] = {"interval_seconds": 900}
    assert select_events(config, tcg="One Piece", kind="event")[0].id == ids[2]
    assert tcg_filter("Digimon Cards") == "digimon_cards"
    assert select_events(config, tcg="Digimon Cards") == []


@pytest.mark.parametrize("value", [0, 101, -1, True, "5"])
def test_limits_are_strict_and_bounded(saved, value):
    with pytest.raises(ValueError):
        select_events(saved[0], limit=value)


def test_readonly_queries_do_not_construct_store_or_change_database(saved, monkeypatch):
    config, _ = saved
    before = snapshot(config.database_path)
    def forbidden(*args, **kwargs):
        raise AssertionError("Production Store must not open")
    monkeypatch.setattr(Store, "__init__", forbidden)
    events = select_events(config, tcg="pokemon")
    payload = preview_payload(events[0], config.timezone)
    assert payload["allowed_mentions"]["parse"] == []
    assert "VISTA PREVIA" in payload["content"]
    assert payload["embeds"][0]["timestamp"] == events[0].occurred_at
    assert snapshot(config.database_path) == before


def test_sqlite_is_opened_explicitly_readonly(saved, monkeypatch):
    import drop_alerts.inspection as module
    original = sqlite3.connect
    calls = []
    def connect(database_uri, **kwargs):
        calls.append((database_uri, kwargs))
        assert database_uri.endswith("?mode=ro") and kwargs["uri"] is True
        return original(database_uri, **kwargs)
    monkeypatch.setattr(module.sqlite3, "connect", connect)
    assert select_events(saved[0], limit=1)
    assert len(calls) == 1


def test_malformed_historical_payload_is_skipped_without_hiding_valid_events(saved):
    config, ids = saved
    db = sqlite3.connect(config.database_path)
    db.execute("UPDATE events SET payload='invalid json' WHERE id=?", (ids[4],))
    db.commit()
    db.close()
    assert select_events(config, tcg="pokemon", limit=1)[0].id == ids[3]


def test_missing_database_is_not_created(tmp_path):
    config = Settings(database_path=str(tmp_path / "missing.db"))
    with pytest.raises(InspectionError) as error:
        select_events(config)
    assert error.value.code == "database_missing"
    assert not Path(config.database_path).exists()


def test_unreadable_schema_is_a_redacted_error(tmp_path):
    path = tmp_path / "bad.db"
    path.write_text("not SQLite")
    with pytest.raises(InspectionError) as error:
        select_events(Settings(database_path=str(path)))
    assert error.value.code == "database_unreadable"


@pytest.mark.asyncio
async def test_preview_without_send_is_only_json_and_never_network(saved, monkeypatch, capsys):
    config, _ = saved
    before = snapshot(config.database_path)
    async def forbidden(*args, **kwargs):
        raise AssertionError("No network without --send")
    monkeypatch.setattr("drop_alerts.inspection.send_preview", forbidden)
    assert await inspect_command(config, "preview", tcg="pokemon", kind="article") == 0
    payload = json.loads(capsys.readouterr().out)
    assert "VISTA PREVIA" in payload["content"]
    assert "Pokémon nueva colección" in payload["embeds"][0]["title"]
    assert snapshot(config.database_path) == before


@pytest.mark.asyncio
async def test_events_json_and_human_listing_are_operator_friendly(saved, capsys):
    config, _ = saved
    assert await inspect_command(config, "events", tcg="one_piece", kind="event", as_json=True) == 0
    rows = json.loads(capsys.readouterr().out)
    assert rows[0]["tcg"] == "one_piece" and rows[0]["source"] == "one_piece_news"
    assert rows[0]["kind"] == "event" and rows[0]["url"].startswith("https://")
    assert await inspect_command(config, "events", tcg="one_piece", limit=1) == 0
    assert "One Piece Card Game" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_empty_filters_or_missing_database_never_send(saved, tmp_path, monkeypatch, capsys):
    async def forbidden(*args, **kwargs):
        raise AssertionError("Empty preview cannot send")
    monkeypatch.setattr("drop_alerts.inspection.send_preview", forbidden)
    assert await inspect_command(saved[0], "preview", tcg="digimon", send=True) == 1
    assert "Todavía no hay" in capsys.readouterr().out
    config = Settings(database_path=str(tmp_path / "missing.db"))
    assert await inspect_command(config, "events") == 2
    assert "todavía no existe" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_explicit_send_does_one_post_without_modifying_queue_or_history(saved):
    config, _ = saved
    event = select_events(config, tcg="one_piece", limit=1)[0]
    payload = preview_payload(event, config.timezone)
    before = snapshot(config.database_path)
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"id": "preview-only"})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await send_preview(config, payload, client=client)
    assert result.sent and result.http_status == 200
    assert len(calls) == 1 and calls[0].url.params["wait"] == "true"
    assert json.loads(calls[0].content)["allowed_mentions"]["parse"] == []
    assert snapshot(config.database_path) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("retry", [2.5, "invalid", -1, float("nan"), float("inf")])
async def test_rate_limit_is_bounded_and_not_retried(saved, retry):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(429, content=json.dumps({"retry_after": retry}).encode())
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await send_preview(saved[0], {}, client=client)
    assert result.sent is False and result.http_status == 429
    assert 1 <= result.retry_after <= 86400 and len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 404, 500, 302])
async def test_http_error_statuses_do_not_leak_response_or_redirect(saved, status):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(status, text="private-webhook-token", headers={"Location": "https://evil.test"})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await send_preview(saved[0], {}, client=client)
    assert result.sent is False and result.http_status == status and len(calls) == 1
    assert "private-webhook-token" not in str(result)


@pytest.mark.asyncio
async def test_network_failure_timeout_and_debug_logs_never_expose_webhook(saved, caplog):
    config, _ = saved
    caplog.set_level(logging.DEBUG)
    def offline(request):
        raise httpx.ConnectError("private-webhook-token", request=request)
    async with httpx.AsyncClient(transport=httpx.MockTransport(offline)) as client:
        result = await send_preview(config, {}, client=client)
    assert result.error == "ConnectError"
    config.http_timeout_seconds = 0.001
    async def slow(request):
        await asyncio.sleep(0.05)
        return httpx.Response(200)
    async with httpx.AsyncClient(transport=httpx.MockTransport(slow)) as client:
        result = await send_preview(config, {}, client=client)
    assert result.error == "TimeoutError"
    assert "private-webhook-token" not in caplog.text


@pytest.mark.asyncio
async def test_send_cli_prints_only_safe_outcome(saved, monkeypatch, capsys):
    config, _ = saved
    async def fail(*args, **kwargs):
        return PreviewDelivery(False, error="ConnectError")
    monkeypatch.setattr("drop_alerts.inspection.send_preview", fail)
    assert await inspect_command(config, "preview", tcg="pokemon", send=True) == 1
    output = capsys.readouterr().out
    assert "ConnectError" in output and "private-webhook-token" not in output
    async def limited(*args, **kwargs):
        return PreviewDelivery(False, http_status=429, retry_after=10)
    monkeypatch.setattr("drop_alerts.inspection.send_preview", limited)
    assert await inspect_command(config, "preview", tcg="pokemon", send=True) == 1
    assert "10 segundos" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_missing_webhook_is_only_an_error_for_explicit_sending(saved, capsys):
    config, _ = saved
    config.discord_webhook_url = ""
    assert await inspect_command(config, "preview", tcg="pokemon") == 0
    capsys.readouterr()
    assert await inspect_command(config, "preview", tcg="pokemon", send=True) == 2
    assert "DISCORD_WEBHOOK_URL" in capsys.readouterr().out


@pytest.mark.parametrize("arguments", [["events", "--limit", "0"], ["events", "--limit", "101"],
    ["preview", "--kind", "unknown"], ["run", "--tcg", "pokemon"], ["events", "--send"],
    ["preview", "--limit", "10"], ["events", "--tcg", "!!!"]])
def test_new_arguments_are_validated_and_scoped_to_inspection_commands(arguments, monkeypatch):
    from drop_alerts.__main__ import main
    monkeypatch.setattr("sys.argv", ["drop-alerts", *arguments])
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2


def test_main_dispatches_readonly_inspection_without_store(saved, monkeypatch, capsys):
    import drop_alerts.__main__ as cli
    config, _ = saved
    monkeypatch.setattr(cli.Settings, "from_env", lambda: config)
    def forbidden(*args, **kwargs):
        raise AssertionError("No production Store constructor")
    monkeypatch.setattr(cli, "Store", forbidden)
    monkeypatch.setattr("sys.argv", ["drop-alerts", "events", "--tcg", "One Piece", "--kind", "event", "--limit", "1", "--json"])
    assert cli.main() == 0
    rows = json.loads(capsys.readouterr().out)
    assert len(rows) == 1 and rows[0]["tcg"] == "one_piece"


@pytest.mark.parametrize("arguments,expected_once", [([], False), (["run"], False), (["once"], True)])
def test_existing_service_commands_keep_default_behavior(arguments, expected_once, monkeypatch):
    from contextlib import nullcontext
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    import drop_alerts.__main__ as cli
    import drop_alerts.runtime as runtime
    config = Settings()
    fake_store = SimpleNamespace(close=lambda: None)
    run = AsyncMock()
    monkeypatch.setattr(cli.Settings, "from_env", lambda: config)
    monkeypatch.setattr(cli, "Store", lambda *args: fake_store)
    monkeypatch.setattr(cli, "ProcessLock", lambda *args: nullcontext())
    monkeypatch.setattr(runtime, "run", run)
    monkeypatch.setattr("sys.argv", ["drop-alerts", *arguments])
    assert cli.main() == 0
    run.assert_awaited_once_with(config, fake_store, once=expected_once)
