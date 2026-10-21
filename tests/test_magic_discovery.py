import asyncio
from pathlib import Path

import pytest

from drop_alerts.models import ExtractionError, Item
from drop_alerts.sources.magic_news import MagicNewsSource


FIXTURES = Path(__file__).parent / "fixtures"
COUNTDOWN = "https://magic.wizards.com/en/news/announcements/secret-lair-countdown-kit-marvels-history-of-heroes"
ZETA = "https://magic.wizards.com/en/news/announcements/an-update-on-the-zeta-set-sale"
OLD = "https://magic.wizards.com/en/news/announcements/proxies-policy-and-communication-2016-01-14"


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


class MemoryStore:
    def __init__(self, items=()):
        self.items = list(items)
        self.meta = {}

    def get_source_items(self, source):
        return [item for item in self.items if item.source == source]

    def get_meta(self, key, default=None):
        return self.meta.get(key, default)

    def set_meta(self, key, value):
        self.meta[key] = value


class SavedHTTP:
    def __init__(self, store=None):
        self.store = store
        source = MagicNewsSource()
        self.responses = {
            source.url: fixture("magic-news.html"),
            source.announcements_url: fixture("magic_expansion_announcements.html"),
            source.sitemap_url: fixture("magic_expansion_sitemap.xml"),
            COUNTDOWN: fixture("magic_expansion_countdown.html"),
        }
        self.calls = []

    async def get(self, url):
        self.calls.append(url)
        response = self.responses.get(url, fixture("magic_expansion_article.html"))
        if isinstance(response, Exception):
            raise response
        return response


def test_saved_announcements_reveal_countdown_outside_homepage():
    source = MagicNewsSource()
    home = source.parse_listing(fixture("magic-news.html"))
    announcements = source.parse_listing(fixture("magic_expansion_announcements.html"))
    assert COUNTDOWN not in {item.id for item in home}
    assert COUNTDOWN in {item.id for item in announcements}
    assert all(item.source == "magic_news" for item in announcements)


def test_sitemap_discovers_topic_urls_without_equating_lastmod_with_news():
    source = MagicNewsSource()
    urls = source.parse_sitemap(fixture("magic_expansion_sitemap.xml"))
    assert COUNTDOWN in urls and ZETA in urls
    assert OLD not in urls
    http = SavedHTTP()
    result = asyncio.run(source.fetch(http))
    item = next(item for item in result.items if item.id == COUNTDOWN)
    assert item.data["published_at"] == "Oct 16, 2026"  # From the article, never sitemap.
    assert "lastmod" not in item.data
    assert item.state == "ANNOUNCED" and not item.data["availability_verified"]
    assert item.data["announcement_url"] == item.url


@pytest.mark.parametrize("body", ["<html>new layout</html>", "<urlset/>",
    '<!DOCTYPE urlset [<!ENTITY x "bad">]><urlset/>',
    '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><sitemap/></sitemapindex>'])
def test_sitemap_structure_changes_fail_closed(body):
    with pytest.raises(ExtractionError):
        MagicNewsSource().parse_sitemap(body)


def test_sitemap_external_links_are_never_candidates():
    body = fixture("magic_expansion_sitemap.xml").replace("https://magic.wizards.com/", "https://attacker.invalid/")
    with pytest.raises(ExtractionError):
        MagicNewsSource().parse_sitemap(body)


def test_valid_sitemap_without_matching_topics_is_not_structure_failure():
    body = (fixture("magic_expansion_sitemap.xml").replace("secret-lair", "ordinary-news")
            .replace("zeta-set", "ordinary-set").replace("countdown-kit", "ordinary-kit"))
    assert MagicNewsSource().parse_sitemap(body) == []


def test_sitemap_has_a_bounded_inventory():
    with pytest.raises(ExtractionError):
        MagicNewsSource(max_sitemap_entries=1).parse_sitemap(fixture("magic_expansion_sitemap.xml"))


def test_discovery_and_detail_requests_are_bounded_and_inventory_is_complete():
    source = MagicNewsSource(max_articles=2)
    http = SavedHTTP()
    result = asyncio.run(source.fetch(http))
    assert len(result.items) == 2
    assert len(http.calls) == 3 + 2
    assert COUNTDOWN in result.metadata["discovery_inventories"]["announcements_v2"]
    assert ZETA in result.metadata["discovery_inventories"]["sitemap_v1"]
    assert len(result.metadata["bootstrap_ids"]) > len(result.items)


def test_failed_category_does_not_stop_frontpage_or_baseline_failed_channel():
    source = MagicNewsSource()
    http = SavedHTTP()
    http.responses[source.announcements_url] = ExtractionError("offline")
    result = asyncio.run(source.fetch(http))
    assert result.items
    assert "announcements_v2" not in result.metadata["discovery_inventories"]
    assert "sitemap_v1" in result.metadata["discovery_inventories"]
    assert "announcements_v2:discovery_failed" in result.metadata["errors"]


def test_failed_frontpage_still_discovers_announcements_and_sitemap():
    source = MagicNewsSource()
    http = SavedHTTP()
    http.responses[source.url] = ExtractionError("offline")
    result = asyncio.run(source.fetch(http))
    assert COUNTDOWN in {item.id for item in result.items}
    assert "frontpage:discovery_failed" in result.metadata["errors"]


def test_lastmod_only_changes_do_not_change_items():
    source = MagicNewsSource()
    http = SavedHTTP()
    first = asyncio.run(source.fetch(http))
    http.responses[source.sitemap_url] = http.responses[source.sitemap_url].replace("2026-10-", "2027-10-")
    second = asyncio.run(MagicNewsSource().fetch(http))
    assert {item.id: item.digest for item in first.items} == {item.id: item.digest for item in second.items}


def test_saved_articles_remain_in_rotating_rechecks_after_leaving_listings():
    url = "https://magic.wizards.com/en/news/announcements/secret-lair-previous-announcement"
    saved = Item(id=url, source="magic_news", title="Previous Secret Lair announcement", url=url,
                 kind="article", state="ANNOUNCED")
    store = MemoryStore([saved])
    http = SavedHTTP(store)
    for _ in range(20):
        asyncio.run(MagicNewsSource(max_articles=2).fetch(http))
        if url in http.calls:
            break
    assert url in http.calls
    assert store.get_meta("source_cursor:magic_news") is not None


def test_partial_article_failures_never_emit_listing_only_fallback():
    source = MagicNewsSource(max_articles=3)
    http = SavedHTTP()
    for item in source.parse_listing(http.responses[source.url]):
        http.responses[item.url] = "<html><h1>Partial page</h1></html>"
    # Other discovery channels retain healthy full articles.
    result = asyncio.run(source.fetch(http))
    assert all("published_at" in item.data for item in result.items)
    assert result.metadata["errors"]


def test_all_details_failing_keeps_previous_snapshot():
    class BrokenDetails(SavedHTTP):
        async def get(self, url):
            source = MagicNewsSource()
            if url not in (source.url, source.announcements_url, source.sitemap_url):
                raise ExtractionError("details offline")
            return await super().get(url)
    with pytest.raises(ExtractionError):
        asyncio.run(MagicNewsSource().fetch(BrokenDetails()))


def test_article_image_is_source_metadata_only_and_allowlisted():
    source = MagicNewsSource()
    item = source.parse_listing(fixture("magic-news.html"))[0]
    body = fixture("magic_expansion_article.html")
    accepted = source.parse_article(body, item)
    assert accepted.data.get("image_verified") is True
    assert accepted.data["image_url"].startswith("https://images.ctfassets.net/")
    fresh = source.parse_listing(fixture("magic-news.html"))[0]
    refused = source.parse_article(body.replace("images.ctfassets.net", "attacker.invalid"), fresh)
    assert "image_url" not in refused.data


def test_single_item_budget_still_rotates_to_saved_articles():
    url = "https://magic.wizards.com/en/news/announcements/secret-lair-previous-announcement"
    saved = Item(id=url, source="magic_news", title="Previous Secret Lair announcement", url=url,
                 kind="article", state="ANNOUNCED")
    store = MemoryStore([saved])
    http = SavedHTTP(store)
    for _ in range(20):
        asyncio.run(MagicNewsSource(max_articles=1).fetch(http))
        if url in http.calls:
            break
    assert url in http.calls
