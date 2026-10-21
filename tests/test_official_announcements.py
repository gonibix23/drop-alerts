"""Tests against trimmed semantic fragments captured from official pages.

Capture date: 2026-10-21. Listings: WPN /en/news, MagicCon
/global/en-us/magiccon-news.html and Secret Lair EU /chaosvault.
Article fragments: WPN /en/news/reality-fracture-secret-lair-bundle-delayed
and MagicCon /global/en-us/magiccon-news/2026/the-magiccon-las-vegas-merch-preview.html.
Chaos catalog: observed Scalefast StoreSearch with feedID:72765. Advertising,
navigation, images and unrelated article prose are omitted from fixtures.
"""
import asyncio
from copy import deepcopy
import json
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from drop_alerts.config import Settings
from drop_alerts.detection import DetectionEngine
from drop_alerts.models import ExtractionError
from drop_alerts.models import FetchResult
from drop_alerts.rules import RuleEngine
from drop_alerts.sources.official_announcements import (
    ChaosVaultSource, MagicConNewsSource, WPNNewsSource, is_special_announcement,
)
from drop_alerts.storage import Store


FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


class FakeHTTP:
    def __init__(self, responses, store=None):
        self.responses, self.store, self.calls = responses, store, []

    async def get(self, url):
        self.calls.append(url)
        response = self.responses(url) if callable(self.responses) else self.responses[url]
        if isinstance(response, Exception):
            raise response
        return response


def test_wpn_listing_uses_card_heading_instead_of_read_more():
    items = WPNNewsSource().parse_listing(fixture("announcements_wpn_listing.html"))
    assert len(items) == 3
    assert items[0].title == "Reality Fracture Secret Lair Bundle Delayed"
    assert items[0].url == "https://wpn.wizards.com/en/news/reality-fracture-secret-lair-bundle-delayed"
    assert items[0].data["announcement_url"] == items[0].url
    assert all(i.state == "ANNOUNCED" and i.kind == "announcement" for i in items)


def test_wpn_article_isolated_from_related_articles_and_stock_claims():
    source = WPNNewsSource()
    item = source.parse_listing(fixture("announcements_wpn_listing.html"))[0]
    source.parse_article(fixture("announcements_wpn_article.html"), item)
    assert "delayed globally" in item.content
    assert item.data["published_at"] == "Oct 20, 2026"
    assert item.data["image_verified"]
    assert not item.data["availability_verified"]
    assert item.data["channel"] == "retail"


def test_magiccon_listing_and_article_detect_relevant_body_even_generic_title():
    source = MagicConNewsSource()
    items = source.parse_listing(fixture("announcements_magiccon_listing.html"))
    item = next(i for i in items if "merch-preview" in i.url)
    assert "Secret Lair" not in item.title
    source.parse_article(fixture("announcements_magiccon_article.html"), item)
    assert "Secret Lair Roadshow" in item.content
    assert is_special_announcement(item.content)
    assert "Festival in a Box" in item.data["summary"]
    assert item.data["published_at"] == "Apr 16, 2026"
    assert item.data["image_verified"]
    assert item.data["channel"] == "event"
    assert item.state == "ANNOUNCED"


@pytest.mark.parametrize("source", [WPNNewsSource(), MagicConNewsSource(), ChaosVaultSource()])
@pytest.mark.parametrize("body", ["<html><title>Login</title><a href='/login'>Login</a></html>",
                                  "<html><h1>Temporarily unavailable</h1></html>",
                                  "<html><title>Access denied</title><main></main></html>"])
def test_structure_or_block_pages_fail_closed(source, body):
    with pytest.raises(ExtractionError):
        source.parse_listing(body)


@pytest.mark.parametrize("value,expected", [
    ("Secret Lair X Artist", True), ("CHAOS VAULT opens", True),
    ("Festival in a Box", True), ("Secret Gallery", True),
    ("Roadshow drop", True), ("Exclusive promotional card", True),
    ("MagicCon tickets on sale", False), ("Exclusive shirts at MagicCon", False),
    ("Weekly league tournament", False), ("Magic | Star Trek dates and details", False),
])
def test_special_product_filter(value, expected):
    assert is_special_announcement(value) is expected


async def test_wpn_fetch_filters_irrelevant_articles_and_preserves_bootstrap_inventory():
    source = WPNNewsSource(max_articles=3)
    listing = fixture("announcements_wpn_listing.html")
    items = source.parse_listing(listing)
    article = fixture("announcements_wpn_article.html")
    irrelevant = article.replace("Secret Lair", "Draft")
    responses = {source.url: listing, **{i.url: irrelevant for i in items}}
    responses[items[0].url] = article
    result = await source.fetch(FakeHTTP(responses))
    assert len(result.items) == 1
    assert result.items[0].id == items[0].id
    assert len(result.metadata["bootstrap_ids"]) == 3


async def test_valid_no_relevant_articles_is_healthy_empty_not_broken_structure():
    source = WPNNewsSource(max_articles=3)
    listing = fixture("announcements_wpn_listing.html")
    article = fixture("announcements_wpn_article.html").replace("Secret Lair", "Draft")
    responses = {source.url: listing, **{i.url: article for i in source.parse_listing(listing)}}
    result = await source.fetch(FakeHTTP(responses))
    assert result.not_modified and not result.items
    assert len(result.metadata["bootstrap_ids"]) == 3


async def test_failed_articles_do_not_establish_empty_baseline():
    source = WPNNewsSource(max_articles=3)
    listing = fixture("announcements_wpn_listing.html")
    responses = {source.url: listing, **{i.url: ExtractionError("network") for i in source.parse_listing(listing)}}
    with pytest.raises(ExtractionError):
        await source.fetch(FakeHTTP(responses))


async def test_article_window_rotates_persistently_across_adapter_restarts():
    listing = fixture("announcements_wpn_listing.html")
    source = WPNNewsSource(max_articles=1)
    candidates = source.parse_listing(listing)
    responses = {source.url: listing, **{i.url: fixture("announcements_wpn_article.html") for i in candidates}}
    store = Store(":memory:")
    try:
        first_http = FakeHTTP(responses, store)
        await source.fetch(first_http)
        second_http = FakeHTTP(responses, store)
        await WPNNewsSource(max_articles=1).fetch(second_http)
        assert first_http.calls[1] == candidates[0].url
        assert second_http.calls[1] == candidates[1].url
    finally:
        store.close()


async def test_budget_bounds_a_stalled_announcement_source():
    class StalledHTTP:
        async def get(self, url):
            await asyncio.Event().wait()
    with pytest.raises(ExtractionError):
        await WPNNewsSource(max_duration_seconds=0.01).fetch(StalledHTTP())


def test_untrusted_external_article_or_image_urls_are_not_accepted():
    source = WPNNewsSource()
    listing = fixture("announcements_wpn_listing.html")
    external = listing.replace('href="/en/news/', 'href="https://evil.invalid/en/news/')
    with pytest.raises(ExtractionError):
        source.parse_listing(external)
    item = source.parse_listing(listing)[0]
    body = fixture("announcements_wpn_article.html").replace("images.ctfassets.net", "evil.invalid")
    source.parse_article(body, item)
    assert "image_url" not in item.data


def test_chaos_uses_observed_filter_and_structured_catalog_identity():
    source = ChaosVaultSource()
    assert source.parse_listing(fixture("announcements_chaos_listing.html")) == ["72765"]
    items, total = source.parse_catalog(fixture("announcements_chaos_catalog.json"), "72765")
    assert len(items) == total == 2
    assert items[0].id == "product:1246222"
    assert items[0].title == "The Oddlands: Plains Foil Edition"
    assert items[0].state == "ANNOUNCED" and items[0].kind == "announcement"
    assert items[0].data["region"] == "EU"
    assert items[0].data["announcement_url"] == items[0].url
    assert not items[0].data["availability_verified"]
    assert "price" not in items[0].data and "stock" not in items[0].data


def test_chaos_commercial_changes_are_not_false_announcement_changes():
    source = ChaosVaultSource()
    body = fixture("announcements_chaos_catalog.json")
    previous = source.parse_catalog(body, "72765")[0]
    data = json.loads(body)
    data["filters"][0]["products"][0]["stock"]["stock"] = "0"
    data["filters"][0]["products"][0]["price_info"] = {"price": "999"}
    current = source.parse_catalog(json.dumps(data), "72765")[0]
    assert current[0].digest == previous[0].digest


def chaos_http(source, catalog=None):
    def respond(url):
        if url == source.url:
            return fixture("announcements_chaos_listing.html")
        if url == "https://secretlair.wizards.com/eu/":
            return fixture("secret-lair-home.html")
        assert url.startswith("https://storesearch.eu.scalefast.com/StoreSearch?")
        assert "filters=feedID%3A72765" in url
        return catalog if catalog is not None else fixture("announcements_chaos_catalog.json")
    return FakeHTTP(respond)


async def test_chaos_fetch_discovers_transport_config_without_browser_or_product_requests():
    source = ChaosVaultSource()
    http = chaos_http(source)
    result = await source.fetch(http)
    assert len(result.items) == 2 and len(http.calls) == 3
    assert result.metadata["bootstrap_ids"] == [i.id for i in result.items]


async def test_chaos_valid_empty_catalog_is_not_product_disappearance():
    source = ChaosVaultSource()
    result = await source.fetch(chaos_http(source, '{"filters":[{"products":[],"total":0}]}'))
    assert result.not_modified and not result.items


async def test_chaos_repeated_catalog_pagination_is_extraction_error():
    source = ChaosVaultSource()
    data = json.loads(fixture("announcements_chaos_catalog.json"))
    data["filters"][0]["total"] = 25
    with pytest.raises(ExtractionError):
        await source.fetch(chaos_http(source, json.dumps(data)))


async def test_chaos_refuses_source_provided_unapproved_catalog_origin():
    source = ChaosVaultSource()
    root = "https://secretlair.wizards.com/eu/"
    http = FakeHTTP({source.url: fixture("announcements_chaos_listing.html"),
                     root: fixture("secret-lair-home.html").replace(
                         "https://storesearch.eu.scalefast.com/StoreSearch", "https://evil.invalid/search")})
    with pytest.raises(ExtractionError):
        await source.fetch(http)
    assert http.calls == [source.url, root]


def test_chaos_missing_title_is_failure_not_a_removed_product():
    source = ChaosVaultSource()
    data = json.loads(fixture("announcements_chaos_catalog.json"))
    data["filters"][0]["products"][0]["descriptions"] = []
    with pytest.raises(ExtractionError):
        source.parse_catalog(json.dumps(data), "72765")


def test_chaos_image_is_limited_to_observed_cdn():
    source = ChaosVaultSource()
    data = json.loads(fixture("announcements_chaos_catalog.json"))
    data["filters"][0]["products"][0]["image"] = "https://evil.invalid/image.png"
    items, _ = source.parse_catalog(json.dumps(data), "72765")
    assert "image_url" not in items[0].data


def test_malformed_optional_images_do_not_discard_source_facts():
    source = WPNNewsSource()
    item = source.parse_listing(fixture("announcements_wpn_listing.html"))[0]
    body = fixture("announcements_wpn_article.html").replace("//images.ctfassets.net", "https://[broken")
    parsed = source.parse_article(body, item)
    assert parsed.title and "image_url" not in parsed.data
    data = json.loads(fixture("announcements_chaos_catalog.json"))
    data["filters"][0]["products"][0]["image"] = "https://[broken"
    items, _ = ChaosVaultSource().parse_catalog(json.dumps(data), "72765")
    assert items and "image_url" not in items[0].data


async def test_chaos_prioritizes_new_ids_and_rotates_old_items_after_restart():
    source = ChaosVaultSource(max_products=2)
    data = json.loads(fixture("announcements_chaos_catalog.json"))
    known, _ = source.parse_catalog(json.dumps(data), "72765")
    settings = Settings(rules=[{"id": "all"}], llm_enabled=False)
    store = Store(":memory:")
    try:
        store.ingest(source.id, FetchResult(known), DetectionEngine(), RuleEngine(settings.rules), settings)
        new = deepcopy(data["filters"][0]["products"][0])
        new["productID"] = "9000001"
        data["filters"][0]["products"].append(new)
        data["filters"][0]["total"] = 3
        http = chaos_http(source, json.dumps(data))
        http.store = store
        first = await source.fetch(http)
        assert {i.id for i in first.items} == {known[0].id, "product:9000001"}
        assert len(first.metadata["bootstrap_ids"]) == 3
        store.ingest(source.id, first, DetectionEngine(), RuleEngine(settings.rules), settings)

        restarted = ChaosVaultSource(max_products=2)
        newer = deepcopy(new)
        newer["productID"] = "9000002"
        data["filters"][0]["products"].append(newer)
        data["filters"][0]["total"] = 4
        http = chaos_http(restarted, json.dumps(data))
        http.store = store
        second = await restarted.fetch(http)
        assert {i.id for i in second.items} == {known[1].id, "product:9000002"}
        assert len(second.metadata["bootstrap_ids"]) == 4
    finally:
        store.close()


async def test_new_failing_article_does_not_starve_rotating_work_after_restart():
    listing = BeautifulSoup(fixture("announcements_wpn_listing.html"), "html.parser")
    source = WPNNewsSource(max_articles=2)
    old = source.parse_listing(str(listing))
    card = deepcopy(listing.find("h2").parent.parent.parent)
    card.find("h2").string = "Secret Lair newly discovered announcement"
    card.find("a")["href"] = "/en/news/newly-discovered-announcement"
    listing.find("div", id="__nuxt").append(card)
    new_url = "https://wpn.wizards.com/en/news/newly-discovered-announcement"
    irrelevant = fixture("announcements_wpn_article.html").replace("Secret Lair", "Draft")
    responses = {source.url: str(listing), new_url: ExtractionError("temporary network failure"),
                 **{item.url: irrelevant for item in old}}
    store = Store(":memory:")
    try:
        store.set_meta("source_discovery_seen:" + source.id, json.dumps([item.id for item in old]))
        store.set_meta("source_cursor:" + source.id, "1")
        first = FakeHTTP(responses, store)
        with pytest.raises(ExtractionError):
            await source.fetch(first)
        assert first.calls[1:] == [old[1].url, new_url]
        second = FakeHTTP(responses, store)
        with pytest.raises(ExtractionError):
            await WPNNewsSource(max_articles=2).fetch(second)
        assert second.calls[1:] == [old[2].url, new_url]
        third = FakeHTTP(responses, store)
        result = await WPNNewsSource(max_articles=2).fetch(third)
        assert third.calls[1:] == [old[0].url, old[1].url]
        assert result.not_modified
        assert len(result.metadata["bootstrap_ids"]) == 4
    finally:
        store.close()


async def test_one_failed_source_does_not_cancel_other_adapters():
    broken = WPNNewsSource()
    chaos = ChaosVaultSource()
    results = await asyncio.gather(broken.fetch(FakeHTTP({broken.url: ExtractionError("network")})),
                                   chaos.fetch(chaos_http(chaos)), return_exceptions=True)
    assert isinstance(results[0], ExtractionError)
    assert len(results[1].items) == 2
