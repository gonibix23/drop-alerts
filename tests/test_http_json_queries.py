"""Read-only source RPCs share HTTP safeguards without caching stock responses."""
import asyncio
import json
import time

import httpx
import pytest

from drop_alerts.http import SourceHTTP
from drop_alerts.models import ExtractionError
from drop_alerts.storage import Store

URL = "https://store.test/public-stock"
QUERY = {"jsonrpc": "2.0", "method": "call", "params": {"product_id": 42}}


@pytest.mark.asyncio
async def test_rpc_queries_are_fresh_and_never_consume_or_replace_get_cache():
    store, calls = Store(":memory:"), []
    store.set_http_cache(URL, '{"old":true}', '"old-etag"')
    async def handle(request):
        calls.append(request)
        assert request.method == "POST"
        assert json.loads(request.content) == QUERY
        assert request.headers["Content-Type"] == "application/json"
        assert "If-None-Match" not in request.headers and "If-Modified-Since" not in request.headers
        return httpx.Response(200, json={"result": {"free_qty": len(calls)}}, headers={"ETag": '"new-etag"'})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        http = SourceHTTP(client, store, min_request_interval=0, retries=0)
        assert (await http.post_json(URL, QUERY))["result"]["free_qty"] == 1
        assert (await http.post_json(URL, QUERY))["result"]["free_qty"] == 2
    assert len(calls) == 2
    assert store.get_http_cache(URL)["body"] == '{"old":true}'
    assert store.get_http_cache(URL)["etag"] == '"old-etag"'
    store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [[], "query", {"invalid": float("nan")}, {"large": "x" * 65537}])
async def test_invalid_or_oversized_queries_make_no_request(payload):
    calls = []
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: calls.append(request) or httpx.Response(200))) as client:
        with pytest.raises(ExtractionError, match="Consulta JSON"):
            await SourceHTTP(client).post_json(URL, payload)
    assert not calls


@pytest.mark.asyncio
@pytest.mark.parametrize("body", ['<html>challenge</html>', '[]', '{"partial":', '{"free_qty":NaN}', '{"free_qty":1e999}', '{"free_qty":0,"free_qty":5}'])
async def test_rpc_responses_require_unambiguous_finite_json_objects(body):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, text=body))) as client:
        with pytest.raises(ExtractionError, match="Respuesta JSON"):
            await SourceHTTP(client, retries=0).post_json(URL, QUERY)


@pytest.mark.asyncio
@pytest.mark.parametrize("destination", ["https://elsewhere.test/private", "https://store.test/cart"])
async def test_rpc_never_follows_even_same_origin_redirects(destination):
    calls = []
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: calls.append(request) or httpx.Response(302, headers={"Location": destination}))) as client:
        with pytest.raises(ExtractionError, match="Redirección"):
            await SourceHTTP(client, retries=1).post_json(URL, QUERY)
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_rpc_304_cannot_reuse_a_stale_get_response():
    store = Store(":memory:")
    store.set_http_cache(URL, '{"free_qty":99}', '"etag"')
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(304))) as client:
        with pytest.raises(ExtractionError, match="304"):
            await SourceHTTP(client, store, retries=0).post_json(URL, QUERY)
    store.close()


@pytest.mark.asyncio
async def test_rpc_rate_limit_persists_and_also_blocks_get_after_restart():
    store, calls = Store(":memory:"), []
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: calls.append(request) or httpx.Response(429, headers={"Retry-After": "120"}))) as client:
        with pytest.raises(ExtractionError, match="429"):
            await SourceHTTP(client, store, retries=0).post_json(URL, QUERY)
        with pytest.raises(ExtractionError, match="pausa"):
            await SourceHTTP(client, store, retries=0).get("https://store.test/shop")
    assert len(calls) == 1 and float(store.get_meta("http_cooldown:store.test")) > time.time()
    store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["network", "server"])
async def test_transient_rpc_failures_retry_with_the_same_read_only_payload(monkeypatch, failure):
    calls, pauses = [], []
    async def pause(delay):
        pauses.append(delay)
    monkeypatch.setattr("drop_alerts.http.asyncio.sleep", pause)
    async def handle(request):
        calls.append(json.loads(request.content))
        if len(calls) == 1:
            if failure == "network":
                raise httpx.ConnectError("private detail must not escape", request=request)
            return httpx.Response(502)
        return httpx.Response(200, json={"result": {"free_qty": 1}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        assert await SourceHTTP(client, retries=1, min_request_interval=0).post_json(URL, QUERY) == {"result": {"free_qty": 1}}
    assert calls == [QUERY, QUERY] and pauses == [1]


@pytest.mark.asyncio
async def test_rpc_http_errors_are_bounded_and_do_not_expose_response_text():
    calls = []
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: calls.append(request) or httpx.Response(401, text="private-token-and-content"))) as client:
        with pytest.raises(ExtractionError, match="401") as error:
            await SourceHTTP(client, retries=1).post_json(URL, QUERY)
    assert len(calls) == 1 and "private-token" not in str(error.value)


@pytest.mark.asyncio
async def test_rpc_streams_obey_response_byte_and_content_type_limits():
    for response in (httpx.Response(200, json={"oversized": "x" * 50}), httpx.Response(200, content=b"image", headers={"Content-Type": "image/png"})):
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: response)) as client:
            with pytest.raises(ExtractionError):
                await SourceHTTP(client, max_bytes=10, retries=0).post_json(URL, QUERY)


@pytest.mark.asyncio
async def test_rpc_total_timeout_is_bounded():
    async def slow(request):
        await asyncio.sleep(0.1)
        return httpx.Response(200, json={"result": {}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(slow)) as client:
        with pytest.raises(ExtractionError, match="Tiempo total"):
            await SourceHTTP(client, timeout=0.01, retries=0).post_json(URL, QUERY)


@pytest.mark.asyncio
async def test_get_and_rpc_share_per_host_request_slots():
    starts = []
    async def handle(request):
        starts.append(time.monotonic())
        return httpx.Response(200, json={"ok": True}) if request.method == "POST" else httpx.Response(200, text="html")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        http = SourceHTTP(client, min_request_interval=0.025, retries=0)
        await asyncio.gather(http.get("https://store.test/shop"), http.post_json(URL, QUERY), http.post_json(URL, QUERY))
    assert len(starts) == 3
    assert all(later - earlier >= 0.020 for earlier, later in zip(starts, starts[1:]))
