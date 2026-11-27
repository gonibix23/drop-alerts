import json
import time

import httpx
import pytest

from drop_alerts.config import Settings
from drop_alerts.detection import DetectionEngine
from drop_alerts.inspection import PreviewDelivery, inspect_command, preview_payload, send_preview
from drop_alerts.models import Event, FetchResult, Item
from drop_alerts.notifications import DiscordChannel, NotificationWorker
from drop_alerts.rules import RuleEngine
from drop_alerts.storage import Store


URLS = {name: f"https://discord.com/api/webhooks/{index}/test-{name}-secret"
        for index, name in enumerate(("general", "magic", "one_piece", "pokemon"), 100)}


def settings(**overrides):
    values = dict(discord_webhook_url=URLS["general"],
                  discord_webhook_url_magic=URLS["magic"],
                  discord_webhook_url_one_piece=URLS["one_piece"],
                  discord_webhook_url_pokemon=URLS["pokemon"],
                  bootstrap_mode="notify", llm_enabled=False, rules=[{"id": "all"}])
    values.update(overrides)
    return Settings(**values)


def event(source="tabletop_gamers", tcg="magic", identity="drop"):
    current = Item(identity, source, "A Pokémon and One Piece headline", f"https://shop.test/{identity}",
                   "product", "AVAILABLE", {"tcg": tcg} if tcg is not None else {})
    return DetectionEngine().detect(current, None, 1)[0]


def seed(store, config, game, identity):
    current = Item(identity, "tabletop_gamers", f"Drop {identity}", f"https://shop.test/{identity}",
                   "product", "AVAILABLE", {"tcg": game} if game else {})
    store.ingest(current.source, FetchResult([current]), DetectionEngine(), RuleEngine(config.rules), config)
    row = store.db.execute("SELECT id FROM events WHERE item_id=? ORDER BY rowid DESC LIMIT 1", (identity,)).fetchone()
    return current, row[0]


def delivery(store, identity):
    return dict(store.db.execute("SELECT * FROM outbox WHERE event_id=?", (identity,)).fetchone())


@pytest.mark.asyncio
@pytest.mark.parametrize("source,game,target", [
    ("secret_lair_eu", "pokemon", "magic"),
    ("magic_news", None, "magic"),
    ("one_piece_news", "magic", "one_piece"),
    ("pokemon_tcg_news_es", "magic", "pokemon"),
    ("tabletop_gamers", "ONE PIECE", "one_piece"),
    ("jjcollection", "Pokémon TCG", "pokemon"),
    ("carton_peleon", "mtg", "magic"),
    ("tabletop_gamers", None, "general"),
    ("software", None, "general"),
])
async def test_routes_by_deterministic_game_not_title_or_model(source, game, target):
    config, store, calls = settings(), Store(":memory:"), []
    current = event(source, game)
    current.analysis = {"result": {"tcg": "pokemon", "webhook_url": URLS["pokemon"]}}
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: calls.append(request) or httpx.Response(204))) as client:
        await DiscordChannel(config, store, client).send(current)
    assert len(calls) == 1 and str(calls[0].url).split("?")[0] == URLS[target]
    assert calls[0].url.params["wait"] == "true"
    assert json.loads(calls[0].content)["allowed_mentions"]["parse"] == []
    store.close()


@pytest.mark.asyncio
async def test_general_webhook_is_fallback_without_double_delivery():
    config, store, calls = settings(discord_webhook_url_pokemon=""), Store(":memory:"), []
    for game in ("magic", "pokemon", None):
        seed(store, config, game, str(game))
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: calls.append(request) or httpx.Response(204))) as client:
        worker = NotificationWorker(config, store, DiscordChannel(config, store, client))
        await worker.tick()
        await worker.tick()
    assert [request.url.path for request in calls] == [httpx.URL(URLS[name]).path for name in ("magic", "general", "general")]
    assert store.db.execute("SELECT count(*) FROM outbox WHERE status='sent'").fetchone()[0] == 3
    assert store.db.execute("SELECT count(*) FROM notification_history").fetchone()[0] == 3
    store.close()


@pytest.mark.asyncio
async def test_three_specific_webhooks_work_without_general_and_do_not_repeat_after_restart(tmp_path):
    config = settings(discord_webhook_url="", database_path=str(tmp_path / "alerts.db"))
    store, calls = Store(config.database_path), []
    originals = [seed(store, config, game, game)[0] for game in ("magic", "one_piece", "pokemon")]
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: calls.append(request) or httpx.Response(204))) as client:
        channel = DiscordChannel(config, store, client)
        assert channel.enabled
        await NotificationWorker(config, store, channel).tick()
    store.close()
    store = Store(config.database_path)
    for current in originals:
        store.ingest(current.source, FetchResult([current]), DetectionEngine(), RuleEngine(config.rules), config)
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: calls.append(request) or httpx.Response(204))) as client:
        await NotificationWorker(config, store, DiscordChannel(config, store, client)).tick()
    assert len(calls) == 3
    assert {request.url.path for request in calls} == {httpx.URL(URLS[game]).path for game in ("magic", "one_piece", "pokemon")}
    assert store.db.execute("SELECT count(*) FROM outbox").fetchone()[0] == 3
    store.close()


@pytest.mark.asyncio
async def test_missing_route_remains_pending_without_attempts_or_starving_other_game():
    config = settings(discord_webhook_url="", discord_webhook_url_pokemon="", notification_batch_size=1)
    store, calls = Store(":memory:"), []
    pending = [seed(store, config, "pokemon", str(index))[1] for index in range(15)]
    _, allowed = seed(store, config, "one_piece", "allowed")
    before = time.time()
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: calls.append(request) or httpx.Response(204))) as client:
        await NotificationWorker(config, store, DiscordChannel(config, store, client)).tick()
        assert delivery(store, allowed)["status"] == "sent"
        for identity in pending:
            row = delivery(store, identity)
            assert row["status"] == "pending" and row["attempts"] == 0
            assert row["next_attempt"] >= before + 299
        assert store.db.execute("SELECT count(*) FROM notification_history").fetchone()[0] == 1
        config.discord_webhook_url_pokemon = URLS["pokemon"]
        store.db.execute("UPDATE outbox SET next_attempt=0 WHERE status='pending'")
        store.db.commit()
        await NotificationWorker(config, store, DiscordChannel(config, store, client)).tick()
    assert len(calls) == 2 and calls[-1].url.path == httpx.URL(URLS["pokemon"]).path
    store.close()


@pytest.mark.asyncio
async def test_local_rate_limit_isolated_and_persisted_by_webhook(tmp_path):
    config = settings(database_path=str(tmp_path / "alerts.db"))
    store, calls = Store(config.database_path), []
    _, first = seed(store, config, "magic", "first")
    _, second = seed(store, config, "magic", "second")
    _, other = seed(store, config, "one_piece", "other")
    def handler(request):
        calls.append(request)
        return httpx.Response(429, json={"retry_after": 600, "global": False}) if request.url.path == httpx.URL(URLS["magic"]).path else httpx.Response(204)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await NotificationWorker(config, store, DiscordChannel(config, store, client)).tick()
    assert len(calls) == 2 and delivery(store, other)["status"] == "sent"
    assert delivery(store, first)["attempts"] == 1
    assert delivery(store, second)["attempts"] == 0
    assert delivery(store, second)["next_attempt"] > time.time()
    store.close()
    store = Store(config.database_path)
    store.db.execute("UPDATE outbox SET next_attempt=0 WHERE status='pending'")
    store.db.commit()
    _, third = seed(store, config, "pokemon", "third")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await NotificationWorker(config, store, DiscordChannel(config, store, client)).tick()
    assert len(calls) == 3 and delivery(store, third)["status"] == "sent"
    assert delivery(store, first)["attempts"] == 1 and delivery(store, second)["attempts"] == 0
    metadata = json.dumps([tuple(row) for row in store.db.execute("SELECT * FROM meta")])
    assert all(url not in metadata and "test-" + game + "-secret" not in metadata for game, url in URLS.items())
    store.close()


@pytest.mark.asyncio
async def test_same_webhook_shared_between_games_respects_same_bucket():
    config = settings(discord_webhook_url_one_piece=URLS["magic"])
    store, calls = Store(":memory:"), []
    seed(store, config, "magic", "first")
    _, other = seed(store, config, "one_piece", "other")
    _, allowed = seed(store, config, "pokemon", "allowed")
    def handler(request):
        calls.append(request)
        return httpx.Response(429, json={"retry_after": 600}) if request.url.path == httpx.URL(URLS["magic"]).path else httpx.Response(204)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await NotificationWorker(config, store, DiscordChannel(config, store, client)).tick()
    assert len(calls) == 2 and delivery(store, other)["attempts"] == 0
    assert delivery(store, other)["status"] == "pending" and delivery(store, allowed)["status"] == "sent"
    store.close()


@pytest.mark.asyncio
async def test_exhausted_success_bucket_does_not_block_other_channel():
    config, store, calls = settings(), Store(":memory:"), []
    seed(store, config, "magic", "first")
    _, deferred = seed(store, config, "magic", "second")
    _, allowed = seed(store, config, "pokemon", "other")
    def handler(request):
        calls.append(request)
        return httpx.Response(204, headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset-after": "600"})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await NotificationWorker(config, store, DiscordChannel(config, store, client)).tick()
    assert len(calls) == 2
    assert delivery(store, deferred)["status"] == "pending" and delivery(store, deferred)["attempts"] == 0
    assert delivery(store, allowed)["status"] == "sent"
    store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("body,headers", [
    ({"retry_after": 600, "global": True}, {}),
    ({"retry_after": 600}, {"x-ratelimit-global": "true"}),
])
async def test_global_rate_limit_blocks_all_channels_after_restart(tmp_path, body, headers):
    config = settings(database_path=str(tmp_path / "alerts.db"))
    store, calls = Store(config.database_path), []
    seed(store, config, "magic", "first")
    _, other = seed(store, config, "one_piece", "other")
    def handler(request):
        calls.append(request)
        return httpx.Response(429, json=body, headers=headers)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await NotificationWorker(config, store, DiscordChannel(config, store, client)).tick()
    assert len(calls) == 1 and delivery(store, other)["attempts"] == 0
    store.close()
    store = Store(config.database_path)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await NotificationWorker(config, store, DiscordChannel(config, store, client)).tick()
    assert len(calls) == 1 and delivery(store, other)["status"] == "pending"
    store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("status,expected", [(404, "dead"), (503, "pending")])
async def test_webhook_failure_does_not_reroute_or_prevent_other_channel(status, expected):
    config, store, calls = settings(), Store(":memory:"), []
    _, failed = seed(store, config, "magic", "first")
    _, allowed = seed(store, config, "pokemon", "other")
    def handler(request):
        calls.append(request)
        return httpx.Response(status if request.url.path == httpx.URL(URLS["magic"]).path else 204)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await NotificationWorker(config, store, DiscordChannel(config, store, client)).tick()
    assert len(calls) == 2 and delivery(store, failed)["status"] == expected
    assert delivery(store, allowed)["status"] == "sent"
    assert all(request.url.path != httpx.URL(URLS["general"]).path for request in calls)
    store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("game", ["magic", "one_piece", "pokemon"])
async def test_manual_preview_uses_same_specific_route_without_general(game):
    config, current, calls = settings(discord_webhook_url=""), event(tcg=game), []
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: calls.append(request) or httpx.Response(204))) as client:
        result = await send_preview(config, preview_payload(current, config.timezone), event=current, client=client)
    assert result.sent and len(calls) == 1 and calls[0].url.path == httpx.URL(URLS[game]).path


@pytest.mark.asyncio
async def test_preview_cli_passes_selected_event_to_route_resolver(tmp_path, monkeypatch):
    config = settings(discord_webhook_url="", database_path=str(tmp_path / "alerts.db"))
    store = Store(config.database_path)
    _, selected = seed(store, config, "one_piece", "last-drop")
    store.close()
    captured = []
    async def send(configured, payload, *, event=None, **kwargs):
        captured.append(event)
        return PreviewDelivery(True, 204)
    monkeypatch.setattr("drop_alerts.inspection.send_preview", send)
    assert await inspect_command(config, "preview", tcg="one_piece", send=True) == 0
    assert len(captured) == 1 and isinstance(captured[0], Event) and captured[0].id == selected
