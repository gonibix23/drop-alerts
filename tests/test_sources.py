import asyncio
import json
from pathlib import Path

import httpx
import pytest

from drop_alerts.http import SourceHTTP
from drop_alerts.models import ExtractionError, Item
from drop_alerts.sources import MagicNewsSource, SecretLairSource
from drop_alerts.sources.secret_lair import CATALOG_ORIGIN


FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_secret_lair_real_home_announcements_and_catalog_configuration():
    announcements, urls, config, feeds = SecretLairSource().parse_home(fixture("secret-lair-home.html"))
    assert len(announcements) == 3
    assert all(item.kind == "announcement" and item.state == "UPCOMING" for item in announcements)
    assert all(not item.data["availability_verified"] for item in announcements)
    assert config["searchUrl"] == CATALOG_ORIGIN
    assert "73824" in feeds
    assert "https://secretlair.wizards.com/eu/product/1253140" in urls


def test_secret_lair_real_product_jsonld():
    item = SecretLairSource().parse_product(fixture("secret-lair-product.html"),
                                           "https://secretlair.wizards.com/eu/product/1253140")
    assert item.id == "product:1253140"
    assert item.state == "AVAILABLE"
    assert item.data["price"] == "144"
    assert item.data["currency"] == "EUR"
    assert item.data["price_verified"] is True
    assert item.data["availability_verified"] is True


@pytest.mark.parametrize("availability,expected", [("OutOfStock", "UNAVAILABLE"),
                         ("PreOrder", "UPCOMING"), ("Bogus", "UNKNOWN")])
def test_explicit_availability_changes(availability, expected):
    body = fixture("secret-lair-product.html").replace("schema.org/InStock", "schema.org/" + availability)
    item = SecretLairSource().parse_product(body, "https://secretlair.wizards.com/eu/product/1253140")
    assert item.state == expected


def test_unknown_availability_never_claims_stock():
    body = fixture("secret-lair-product.html").replace("https://schema.org/InStock", "https://attacker.invalid/InStock")
    item = SecretLairSource().parse_product(body, "https://secretlair.wizards.com/eu/product/1253140")
    assert item.state == "UNKNOWN"
    assert not item.data["availability_verified"]


def test_price_invalid_is_not_exposed_as_verified():
    body = fixture("secret-lair-product.html").replace('"price": "144"', '"price": "NaN"')
    item = SecretLairSource().parse_product(body, "https://secretlair.wizards.com/eu/product/1253140")
    assert "price" not in item.data


def test_price_extreme_exponent_is_not_expanded_into_memory():
    body = fixture("secret-lair-product.html").replace('"price": "144"', '"price": "1e-999999"')
    item = SecretLairSource().parse_product(body, "https://secretlair.wizards.com/eu/product/1253140")
    assert "price" not in item.data


def test_angular_template_does_not_prove_availability():
    with pytest.raises(ExtractionError):
        SecretLairSource().parse_product('<html><button ng-if="product.status === AVAILABLE">Add to cart</button></html>',
                                       "https://secretlair.wizards.com/eu/product/123")


def test_public_catalog_real_saved_response():
    ids, total = SecretLairSource().parse_catalog(fixture("secret-lair-catalog.json"))
    assert len(ids) == total == 6
    assert "1253738" in ids


@pytest.mark.parametrize("body", ["{}", '{"filters":[]}', '{"products":[{"url":"https://evil.invalid"}]}', "<html>error</html>"])
def test_catalog_structure_changes_fail_closed(body):
    with pytest.raises(ExtractionError):
        SecretLairSource().parse_catalog(body)


def test_magic_listing_real_saved_response():
    items = MagicNewsSource().parse_listing(fixture("magic-news.html"))
    assert len({item.id for item in items}) == len(items)
    relevant = next(i for i in items if "Secret Lair" in i.title)
    assert relevant.kind == "article"
    assert relevant.state == "ANNOUNCED"
    assert not relevant.data["availability_verified"]


def test_magic_article_real_saved_response():
    source = MagicNewsSource()
    item = next(i for i in source.parse_listing(fixture("magic-news.html")) if "Secret Lair" in i.title)
    source.parse_article(fixture("magic-article.html"), item)
    assert "delayed globally" in item.content
    assert item.data["published_at"] == "Oct 19, 2026"


def test_structure_and_block_pages_do_not_generate_disappearance():
    for body in ('<html><title>Access Denied</title></html>', '<html>new layout without products</html>'):
        with pytest.raises(ExtractionError):
            SecretLairSource().parse_home(body)
        with pytest.raises(ExtractionError):
            MagicNewsSource().parse_listing(body)


def test_untrusted_listing_urls_are_not_visited():
    body = '<html><a href="https://evil.invalid/en/news/announcements/launch">Secret Lair</a></html>'
    with pytest.raises(ExtractionError):
        MagicNewsSource().parse_listing(body)


def test_endpoint_from_page_is_allowlisted():
    class HTTP:
        calls = []
        async def get(self, url):
            self.calls.append(url)
            return fixture("secret-lair-home.html").replace(CATALOG_ORIGIN, "https://evil.invalid/steal")
    http = HTTP()
    with pytest.raises(ExtractionError):
        asyncio.run(SecretLairSource().fetch(http))
    assert len(http.calls) == 1


def test_http_conditional_cache_304_survives_transport_recreation():
    class Store:
        data = {}
        def get_http_cache(self, url): return self.data.get(url)
        def set_http_cache(self, url, **data): self.data[url] = data
    store = Store()
    calls = []
    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(200, text="<html>snapshot</html>", headers={"ETag": '"v1"', "Last-Modified": "Wed, 21 Oct 2026 12:00:00 GMT"})
        assert request.headers["If-None-Match"] == '"v1"'
        assert "If-Modified-Since" in request.headers
        return httpx.Response(304)
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            assert await SourceHTTP(client, store, min_request_interval=0).get("https://example.test/") == "<html>snapshot</html>"
            assert await SourceHTTP(client, store, min_request_interval=0).get("https://example.test/") == "<html>snapshot</html>"
    asyncio.run(run())


def test_http_network_error_and_size_limit(monkeypatch):
    async def no_sleep(_): pass
    monkeypatch.setattr("drop_alerts.http.asyncio.sleep", no_sleep)
    async def run():
        def timeout(request): raise httpx.ConnectTimeout("unavailable", request=request)
        async with httpx.AsyncClient(transport=httpx.MockTransport(timeout)) as client:
            with pytest.raises(ExtractionError):
                await SourceHTTP(client, min_request_interval=0).get("https://example.test/")
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, text="12345"))) as client:
            with pytest.raises(ExtractionError):
                await SourceHTTP(client, max_bytes=4).get("https://example.test/")
    asyncio.run(run())


def test_http_retries_rate_limit_bounded(monkeypatch):
    sleeps, calls = [], []
    async def sleep(delay): sleeps.append(delay)
    monkeypatch.setattr("drop_alerts.http.asyncio.sleep", sleep)
    def handler(request):
        calls.append(request)
        return httpx.Response(429, headers={"Retry-After": "2"}) if len(calls) == 1 else httpx.Response(200, text="ok")
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            assert await SourceHTTP(client, min_request_interval=0).get("https://example.test/") == "ok"
    asyncio.run(run())
    assert len(calls) == 2
    assert sleeps == [2]


def test_http_long_retry_after_persists_cooldown_without_early_retry():
    class Store:
        data = {}
        def get_http_cache(self, url): return None
        def get_meta(self, key, default=None): return self.data.get(key, default)
        def set_meta(self, key, value): self.data[key] = value
    store, calls = Store(), []
    def handler(request):
        calls.append(request)
        return httpx.Response(429, headers={"Retry-After": "9999"})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            for _ in range(2):
                with pytest.raises(ExtractionError):
                    await SourceHTTP(client, store, min_request_interval=0).get("https://example.test/")
    asyncio.run(run())
    assert len(calls) == 1
    assert store.data["http_cooldown:example.test"] > 0


def test_http_redirects_not_followed():
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(302, headers={"Location": "https://evil.invalid/"})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(ExtractionError):
                await SourceHTTP(client).get("https://example.test/")
    asyncio.run(run())
    assert len(calls) == 1


def test_same_origin_redirect_followed_and_final_etag_reused():
    calls = []
    def handler(request):
        calls.append(request)
        if request.url.path == "/product/1":
            return httpx.Response(302, headers={"Location": "/product/1/name"})
        return httpx.Response(200, text="<html>product</html>", headers={"ETag": '"one"'})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            assert await SourceHTTP(client, min_request_interval=0).get("https://example.test/product/1") == "<html>product</html>"
    asyncio.run(run())
    assert len(calls) == 2


def test_persistent_rotation_bootstrap_ids_and_partial_product_failure():
    class Store:
        meta = {}
        def get_meta(self, key, default=None): return self.meta.get(key, default)
        def set_meta(self, key, value): self.meta[key] = value
        def get_source_items(self, source):
            return [Item("product:777", source, "Saved", "https://secretlair.wizards.com/eu/product/777", kind="product")]
    class HTTP:
        store = Store()
        async def get(self, url):
            if url.endswith("/eu/"):
                return fixture("secret-lair-home.html")
            if url.startswith(CATALOG_ORIGIN):
                return fixture("secret-lair-catalog.json")
            if url.endswith("1253140"):
                raise ExtractionError("temporarily unavailable")
            return fixture("secret-lair-product.html")
    async def run():
        http = HTTP()
        first = await SecretLairSource(max_products=1).fetch(http)
        assert "product:1253738" in first.metadata["bootstrap_ids"]
        assert "product:777" in first.metadata["bootstrap_ids"]
        assert first.metadata["errors"] == ["product:1253140:extraction_failed"]
        assert not any(i.id == "product:1253140" for i in first.items)
        assert http.store.meta["source_cursor:secret_lair_eu"] == 1
        second = await SecretLairSource(max_products=1).fetch(http)
        assert any(i.id == "product:1250053" for i in second.items)
        assert http.store.meta["source_cursor:secret_lair_eu"] == 2
    asyncio.run(run())


def test_real_thing_product_preserves_identity_without_commercial_claims():
    item = SecretLairSource().parse_product(fixture("secret-lair-thing.html"),
                                           "https://secretlair.wizards.com/eu/product/1254818")
    assert item.id == "product:1254818"
    assert item.title == "Festival in a Box: Atlanta 2026"
    assert item.kind == "product" and item.state == "UNKNOWN"
    assert item.data["identity_verified"] is True
    assert item.data["availability_verified"] is False
    assert "price" not in item.data


def test_thing_with_inconsistent_heading_is_extraction_error():
    body = fixture("secret-lair-thing.html").replace('<h1 class="product-title">Festival in a Box: Atlanta 2026</h1>', '<h1>Unrelated page</h1>')
    with pytest.raises(ExtractionError):
        SecretLairSource().parse_product(body, "https://secretlair.wizards.com/eu/product/1254818")


@pytest.mark.parametrize("retry_after", ["inf", "NaN", "1e300"])
def test_http_nonfinite_or_huge_retry_after_bounded(retry_after):
    class Store:
        data = {}
        def get_http_cache(self, url): return None
        def get_meta(self, key, default=None): return self.data.get(key, default)
        def set_meta(self, key, value): self.data[key] = value
    store = Store()
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(429, headers={"Retry-After": retry_after}))) as client:
            with pytest.raises(ExtractionError):
                await SourceHTTP(client, store).get("https://example.test/")
    asyncio.run(run())
    import time
    assert 0 < store.data["http_cooldown:example.test"] - time.time() <= 86400


def test_new_product_priority_also_rechecks_old_catalog():
    class Store:
        def get_meta(self, key, default=None): return 50
        def set_meta(self, key, value): pass
        def get_source_items(self, source):
            return [Item("product:" + str(i), source, "Saved", "https://secretlair.wizards.com/eu/product/" + str(i), kind="product") for i in range(1, 101)]
    class HTTP:
        store = Store()
        async def get(self, url):
            return '<html><a href="/eu/product/999">New</a></html>' if url.endswith("/eu/") else fixture("secret-lair-product.html")
    result = asyncio.run(SecretLairSource(max_products=2).fetch(HTTP()))
    assert any(i.id == "product:999" for i in result.items)
    assert any(i.id != "product:999" for i in result.items)


def test_global_source_budget_returns_verified_partial_and_advances_attempted_cursor():
    class Store:
        data = {}
        def get_meta(self, key, default=None): return self.data.get(key, default)
        def set_meta(self, key, value): self.data[key] = value
        def get_source_items(self, source):
            return [Item("product:" + str(i), source, "Saved", "https://secretlair.wizards.com/eu/product/" + str(i), kind="product") for i in range(1, 4)]
    class HTTP:
        store = Store()
        calls = []
        async def get(self, url):
            self.calls.append(url)
            if url.endswith("/eu/"):
                return '<html><a href="/eu/product/1">One</a></html>'
            if url.endswith("/2"):
                await asyncio.sleep(1)
            return fixture("secret-lair-product.html")
    http = HTTP()
    result = asyncio.run(SecretLairSource(max_products=3, max_duration_seconds=0.05).fetch(http))
    assert [i.id for i in result.items] == ["product:1"]
    assert result.metadata["products_checked"] == 2
    assert result.metadata["errors"] == ["details:time_budget_exhausted"]
    assert http.store.data["source_cursor:secret_lair_eu"] == 2
    assert not any(url.endswith("/3") for url in http.calls)
