import asyncio
import time

import httpx
import pytest

from drop_alerts.http import SourceHTTP


@pytest.mark.asyncio
async def test_adapters_sharing_a_host_reserve_separate_request_slots():
    starts = []
    async def handler(request):
        starts.append(time.monotonic())
        return httpx.Response(200, text="<html>source</html>")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        http = SourceHTTP(client, min_request_interval=0.025, retries=0)
        await asyncio.gather(http.get("https://official.test/shop"), http.get("https://official.test/chaos"), http.get("https://official.test/other"))
    assert len(starts) == 3
    assert all(later - earlier >= 0.020 for earlier, later in zip(starts, starts[1:]))
