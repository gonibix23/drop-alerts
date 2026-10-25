import json
import time
from contextlib import nullcontext

import httpx
import pytest

from drop_alerts.config import Settings
from drop_alerts.detection import DetectionEngine
from drop_alerts.models import FetchResult, Item
from drop_alerts.notifications import DiscordChannel, NotificationWorker
from drop_alerts.rules import RuleEngine
from drop_alerts.storage import Store


def settings(**overrides):
    values = dict(bootstrap_mode="notify", llm_enabled=False, rules=[{"id": "all"}],
                  discord_webhook_url="https://discord.com/api/webhooks/123/private-test-token")
    values.update(overrides)
    return Settings(**values)


def seed(store, config, *, source="one_piece_news", identity="announcement", title="One Piece announcement", data=None, url=None):
    current = Item(identity, source, title, url or f"https://en.onepiece-cardgame.com/topics/2026/{identity}.php",
                   kind="announcement", state="ANNOUNCED", content=title,
                   data=data or {"tcg": "one_piece", "region": "WESTERN"})
    store.ingest(source, FetchResult([current]), DetectionEngine(), RuleEngine(config.rules), config)
    row = store.db.execute("SELECT id FROM events WHERE source=? AND item_id=? ORDER BY created DESC LIMIT 1", (source, identity)).fetchone()
    return current, row[0]


def outbox(store, event_id):
    return dict(store.db.execute("SELECT * FROM outbox WHERE event_id=?", (event_id,)).fetchone())


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["game", "source", "missing_source", "rule"])
async def test_disabled_configuration_closes_existing_delivery_without_http_or_attempt(change):
    config, store = settings(), Store(":memory:")
    _, event_id = seed(store, config)
    store.db.execute("UPDATE outbox SET attempts=2,next_attempt=-500,last_error='discord_network'")
    store.db.commit()
    previous = outbox(store, event_id)
    claims = list(map(tuple, store.db.execute("SELECT * FROM announcement_claims")))
    calls = []
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: calls.append(request) or httpx.Response(200))) as client:
        worker = NotificationWorker(config, store, DiscordChannel(config, store, client))
        if change == "game":
            config.enabled_tcgs = ["magic", "pokemon"]
        elif change == "source":
            config.sources["one_piece_news"]["enabled"] = False
        elif change == "missing_source":
            config.sources.pop("one_piece_news")
        else:
            config.rules = [{"id": "all", "enabled": False}]
        await worker.tick()
    current = outbox(store, event_id)
    assert current["status"] == "skipped" and current["last_error"] == "configuration_disabled"
    assert (current["attempts"], current["next_attempt"], current["delivered"]) == (previous["attempts"], previous["next_attempt"], previous["delivered"])
    assert not calls
    assert [tuple(row) for row in store.db.execute("SELECT attempt,outcome FROM notification_history")] == [(2, "configuration_disabled")]
    assert list(map(tuple, store.db.execute("SELECT * FROM announcement_claims"))) == claims
    assert store.db.execute("SELECT payload FROM events WHERE id=?", (event_id,)).fetchone()[0]
    store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("filter", [{"regions": ["JP"]}, {"cities": ["Madrid"]}, {"tcgs": ["pokemon"]}])
async def test_current_market_city_and_game_rules_apply_to_queued_events(filter):
    config, store = settings(), Store(":memory:")
    _, event_id = seed(store, config, source="local_tcg_events", data={"tcg": "one_piece", "region": "EU", "city": "Alcalá de Henares"})
    config.rules = [{"id": "selected", **filter}]
    calls = []
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: calls.append(request) or httpx.Response(200))) as client:
        await NotificationWorker(config, store, DiscordChannel(config, store, client)).tick()
    assert outbox(store, event_id)["status"] == "skipped" and not calls
    store.close()


@pytest.mark.asyncio
async def test_implicit_enabled_and_unknown_generic_sources_preserve_compatibility():
    config, store = settings(), Store(":memory:")
    _, known = seed(store, config)
    generic = Item("v1", "software", "Release v1", "https://software.test/v1", kind="release")
    store.ingest("software", FetchResult([generic]), DetectionEngine(), RuleEngine(config.rules), config)
    config.sources["one_piece_news"] = {"interval_seconds": 900}
    calls = []
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: calls.append(request) or httpx.Response(204))) as client:
        await NotificationWorker(config, store, DiscordChannel(config, store, client)).tick()
    assert len(calls) == 2 and outbox(store, known)["status"] == "sent"
    assert store.db.execute("SELECT count(*) FROM outbox WHERE status='sent'").fetchone()[0] == 2
    store.close()


@pytest.mark.asyncio
async def test_unknown_source_explicitly_disabled_is_not_sent():
    config, store = settings(), Store(":memory:")
    _, event_id = seed(store, config, source="custom_calendar")
    config.sources["custom_calendar"] = {"enabled": False}
    calls = []
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: calls.append(request) or httpx.Response(204))) as client:
        await NotificationWorker(config, store, DiscordChannel(config, store, client)).tick()
    assert not calls and outbox(store, event_id)["status"] == "skipped"
    store.close()


@pytest.mark.asyncio
async def test_disabled_records_do_not_consume_the_http_batch_or_starve_allowed_events():
    config, store = settings(notification_batch_size=1), Store(":memory:")
    for index in range(5):
        seed(store, config, identity=str(index), title="Old One Piece announcement " + str(index),
             data={"tcg": "one_piece", "region": "WESTERN"})
    _, allowed = seed(store, config, source="pokemon_press_es", identity="pokemon", title="Pokémon announcement", data={"region": "GLOBAL"})
    config.enabled_tcgs = ["pokemon"]
    calls = []
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: calls.append(request) or httpx.Response(200))) as client:
        await NotificationWorker(config, store, DiscordChannel(config, store, client)).tick()
    assert len(calls) == 1 and "Pokémon" in json.loads(calls[0].content)["embeds"][0]["title"]
    assert outbox(store, allowed)["status"] == "sent"
    assert store.db.execute("SELECT count(*) FROM outbox WHERE status='skipped'").fetchone()[0] == 5
    store.close()


@pytest.mark.asyncio
async def test_filter_cleanup_is_bounded_and_resumes_on_next_tick():
    config, store = settings(notification_batch_size=1), Store(":memory:")
    for index in range(105):
        seed(store, config, identity=str(index))
    config.enabled_tcgs = ["pokemon"]
    calls = []
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: calls.append(request) or httpx.Response(204))) as client:
        worker = NotificationWorker(config, store, DiscordChannel(config, store, client))
        await worker.tick()
        assert store.db.execute("SELECT count(*) FROM outbox WHERE status='skipped'").fetchone()[0] == 100
        assert store.db.execute("SELECT count(*) FROM outbox WHERE status='pending'").fetchone()[0] == 5
        await worker.tick()
    assert not calls and not store.due_notifications(10)
    store.close()


@pytest.mark.asyncio
async def test_future_backoff_is_never_reset_by_filtering_other_deliveries():
    config, store = settings(), Store(":memory:")
    _, paused = seed(store, config)
    future = time.time() + 5000
    store.db.execute("UPDATE outbox SET attempts=3,next_attempt=? WHERE event_id=?", (future, paused))
    store.db.commit()
    _, allowed = seed(store, config, source="pokemon_press_es", identity="pokemon", data={"region": "GLOBAL"})
    config.enabled_tcgs = ["pokemon"]
    calls = []
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: calls.append(request) or httpx.Response(204))) as client:
        await NotificationWorker(config, store, DiscordChannel(config, store, client)).tick()
    row = outbox(store, paused)
    assert (row["status"], row["attempts"], row["next_attempt"]) == ("pending", 3, future)
    assert outbox(store, allowed)["status"] == "sent" and len(calls) == 1
    store.close()


@pytest.mark.asyncio
async def test_reenabling_game_does_not_revive_skips_or_duplicate_claimed_announcement():
    config, store = settings(), Store(":memory:")
    original, event_id = seed(store, config)
    config.enabled_tcgs = ["pokemon"]
    calls = []
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: calls.append(request) or httpx.Response(200))) as client:
        worker = NotificationWorker(config, store, DiscordChannel(config, store, client))
        await worker.tick()
        config.enabled_tcgs = ["one_piece", "pokemon", "magic"]
        store.ingest(original.source, FetchResult([original]), DetectionEngine(), RuleEngine(config.rules), config)
        seed(store, config, source="one_piece_products", identity="same-primary-announcement", url=original.url)
        await worker.tick()
        assert not calls and outbox(store, event_id)["status"] == "skipped"
        original.content += " A later real update."
        store.ingest(original.source, FetchResult([original]), DetectionEngine(), RuleEngine(config.rules), config)
        await worker.tick()
    assert len(calls) == 1
    assert store.db.execute("SELECT count(*) FROM outbox WHERE status='sent'").fetchone()[0] == 1
    store.close()


def test_skipping_is_idempotent_and_preserves_terminal_deliveries():
    config, store = settings(), Store(":memory:")
    _, event_id = seed(store, config)
    store.notification_skipped(event_id, "configuration_disabled")
    store.notification_skipped(event_id, "configuration_disabled")
    assert store.db.execute("SELECT count(*) FROM notification_history").fetchone()[0] == 1
    assert outbox(store, event_id)["attempts"] == 0
    _, sent_id = seed(store, config, source="pokemon_press_es", identity="sent", data={"region": "GLOBAL"})
    store.notification_result(sent_id, 1)
    before = outbox(store, sent_id)
    store.notification_skipped(sent_id, "configuration_disabled")
    assert outbox(store, sent_id) == before
    store.close()


@pytest.mark.parametrize("result", [None, {"category": "announcement"}])
def test_finishing_analysis_never_reopens_skipped_delivery_or_resets_backoff(result):
    config, store = settings(llm_enabled=True), Store(":memory:")
    _, event_id = seed(store, config)
    store.db.execute("UPDATE analysis_jobs SET task='release_schedule'")
    store.db.execute("UPDATE outbox SET status='waiting_analysis',next_attempt=1234567890,attempts=2")
    store.db.commit()
    store.notification_skipped(event_id, "configuration_disabled")
    before = outbox(store, event_id)
    store.finish_analysis(store.due_analysis(1)[0], result, 1)
    assert outbox(store, event_id) == before
    assert not store.due_notifications(10)
    store.close()


def test_retry_notifications_command_does_not_revive_skipped_deliveries(monkeypatch):
    import drop_alerts.__main__ as cli
    config, store = settings(), Store(":memory:")
    _, event_id = seed(store, config)
    store.notification_skipped(event_id, "configuration_disabled")
    monkeypatch.setattr(cli.Settings, "from_env", lambda: config)
    monkeypatch.setattr(cli, "Store", lambda *args: store)
    monkeypatch.setattr(cli, "ProcessLock", lambda *args: nullcontext())
    monkeypatch.setattr(store, "close", lambda: None)
    monkeypatch.setattr("sys.argv", ["drop-alerts", "retry-notifications"])
    assert cli.main() == 0
    assert outbox(store, event_id)["status"] == "skipped" and not store.due_notifications(10)


@pytest.mark.asyncio
@pytest.mark.parametrize("with_analysis", [False, True])
async def test_strengthened_rule_requires_existing_valid_analysis_before_delivery(with_analysis):
    config, store = settings(llm_enabled=with_analysis), Store(":memory:")
    _, event_id = seed(store, config)
    if with_analysis:
        store.finish_analysis(store.due_analysis(1)[0], {"category": "announcement", "needs_review": False}, 1)
    config.rules = [{"id": "all", "require_analysis": True}]
    calls = []
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: calls.append(request) or httpx.Response(200))) as client:
        await NotificationWorker(config, store, DiscordChannel(config, store, client)).tick()
    assert len(calls) == int(with_analysis)
    assert outbox(store, event_id)["status"] == ("sent" if with_analysis else "skipped")
    store.close()
