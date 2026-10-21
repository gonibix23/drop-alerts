import asyncio
import json
import time

import httpx
import pytest

from drop_alerts.config import Settings
from drop_alerts.detection import DetectionEngine
from drop_alerts.models import FetchResult, Item
from drop_alerts.notifications import DeliveryError, DiscordChannel, NotificationWorker, discord_payload
from drop_alerts.rules import RuleEngine
from drop_alerts.storage import Store


def config(**overrides):
    values = dict(discord_webhook_url="https://discord.com/api/webhooks/123/not-a-real-secret", bootstrap_mode="notify", llm_enabled=False, rules=[{"id": "all"}])
    values.update(overrides)
    return Settings(**values)


def seed(store, settings, count=1):
    items = [Item(str(n), "test", f"Drop {n}", f"https://official.test/{n}", "product", "AVAILABLE", {"price": 39.99, "currency": "EUR"}) for n in range(count)]
    store.ingest("test", FetchResult(items), DetectionEngine(), RuleEngine(settings.rules), settings)
    return items


def test_discord_payload_mentions_facts_and_uncertainty():
    settings = config()
    store = Store(":memory:")
    seed(store, settings)
    event = store.due_notifications(1)[0][0]
    event.analysis = {"task": "classification", "result": {"category": "product", "price": 999, "availability": "UNAVAILABLE", "summary": "@everyone compra en https://evil.test", "needs_review": True}}
    payload = discord_payload(event)
    assert payload["allowed_mentions"]["parse"] == []
    assert payload["allowed_mentions"]["users"] == []
    encoded = json.dumps(payload, ensure_ascii=False)
    assert "39.99 EUR" in encoded and "AVAILABLE" in encoded
    assert "999" not in encoded and "UNAVAILABLE" not in encoded and "evil.test" not in encoded
    assert "incierta" in encoded
    assert "sin verificar" in encoded
    assert payload["embeds"][0]["url"] == event.url
    store.close()


def test_429_is_persisted_and_respected_after_restart(tmp_path):
    settings = config()
    path = str(tmp_path / "alerts.db")
    store = Store(path)
    seed(store, settings, 2)
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(429, json={"retry_after": 10.5})
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            worker = NotificationWorker(settings, store, DiscordChannel(settings, store, client))
            await worker.tick()
            await worker.tick()
    asyncio.run(scenario())
    assert len(calls) == 1
    assert store.db.execute("SELECT sum(attempts) FROM outbox").fetchone()[0] == 1
    store.close()
    reopened = Store(path)
    async def after_restart():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            channel = DiscordChannel(settings, reopened, client)
            assert channel.blocked_until > time.time()
            await NotificationWorker(settings, reopened, channel).tick()
    asyncio.run(after_restart())
    assert len(calls) == 1
    reopened.close()


def test_progressive_retry_then_success_and_no_duplicate_after_restart(tmp_path):
    settings = config()
    path = str(tmp_path / "alerts.db")
    store = Store(path)
    original = seed(store, settings)
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(503) if len(calls) == 1 else httpx.Response(200, json={"id": "message-1"})
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            worker = NotificationWorker(settings, store, DiscordChannel(settings, store, client))
            before = time.time()
            await worker.tick()
            row = store.db.execute("SELECT * FROM outbox").fetchone()
            assert row["status"] == "pending" and row["attempts"] == 1
            assert row["next_attempt"] >= before + 60
            await worker.tick()
            assert len(calls) == 1
            store.db.execute("UPDATE outbox SET next_attempt=0")
            store.db.commit()
            await worker.tick()
            await worker.tick()
            assert len(calls) == 2
            assert store.db.execute("SELECT status FROM outbox").fetchone()[0] == "sent"
    asyncio.run(scenario())
    store.close()
    store = Store(path)
    store.ingest("test", FetchResult(original), DetectionEngine(), RuleEngine(settings.rules), settings)
    assert not store.due_notifications(10)
    assert store.db.execute("SELECT count(*) FROM outbox").fetchone()[0] == 1
    assert len(calls) == 2
    assert calls[0].url.params["wait"] == "true"
    store.close()


def test_permanent_webhook_error_stops_retry():
    settings = config()
    store = Store(":memory:")
    seed(store, settings)
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(404))) as client:
            await NotificationWorker(settings, store, DiscordChannel(settings, store, client)).tick()
    asyncio.run(scenario())
    row = store.db.execute("SELECT status,last_error FROM outbox").fetchone()
    assert tuple(row) == ("dead", "discord_404")
    assert not store.due_notifications(10)
    store.close()


def test_network_error_is_redacted_and_bounded_by_attempt_limit():
    settings = config(notification_max_attempts=1)
    store = Store(":memory:")
    seed(store, settings)
    def handler(request):
        raise httpx.ConnectError("secret-webhook-token", request=request)
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await NotificationWorker(settings, store, DiscordChannel(settings, store, client)).tick()
    asyncio.run(scenario())
    assert store.db.execute("SELECT status FROM outbox").fetchone()[0] == "dead"
    assert "secret-webhook-token" not in json.dumps(store.stats())
    store.close()


def test_discord_total_wall_clock_timeout_is_retryable():
    settings = config(http_timeout_seconds=0.001)
    store = Store(":memory:")
    seed(store, settings)
    event = store.due_notifications(1)[0][0]
    async def handler(request):
        await asyncio.sleep(0.1)
        return httpx.Response(200, json={"id": "late-message"})
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(DeliveryError) as error:
                await DiscordChannel(settings, store, client).send(event)
            assert error.value.code == "discord_network"
            assert error.value.retry_after == 30
            assert error.value.permanent is False
    asyncio.run(scenario())
    store.close()


def test_success_remaining_zero_blocks_next_send():
    settings = config()
    store = Store(":memory:")
    seed(store, settings, 2)
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset-after": "20"}, json={"id": "message"})
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await NotificationWorker(settings, store, DiscordChannel(settings, store, client)).tick()
    asyncio.run(scenario())
    assert len(calls) == 1
    assert store.db.execute("SELECT count(*) FROM outbox WHERE status='sent'").fetchone()[0] == 1
    store.close()


@pytest.mark.parametrize("retry_after", ["not-a-number", -10, float("inf"), float("nan")])
def test_malformed_rate_limit_delays_are_finite(retry_after):
    settings = config()
    store = Store(":memory:")
    seed(store, settings)
    event = store.due_notifications(1)[0][0]
    # httpx's JSON encoder rejects non-finite floats; real hostile responses can contain them.
    body = json.dumps({"retry_after": retry_after}).encode()
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(429, content=body))) as client:
            with pytest.raises(DeliveryError) as error:
                await DiscordChannel(settings, store, client).send(event)
            assert 1 <= error.value.retry_after <= 86400
    asyncio.run(scenario())
    store.close()
