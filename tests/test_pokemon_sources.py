"""Semantic excerpts from official Pokémon HTML checked 2026-10-25.

These fixtures retain gallery/news cards and short press paragraphs, including
the physical release, prerelease and digital dates. Tests never contact websites.
"""
import asyncio
from dataclasses import replace
from pathlib import Path

from bs4 import BeautifulSoup
import pytest

from drop_alerts.config import Settings
from drop_alerts.detection import DetectionEngine
from drop_alerts.models import ExtractionError, FetchResult
from drop_alerts.rules import RuleEngine
from drop_alerts.sources.pokemon import (
    PokemonProductsSource, PokemonUSProductsSource, PokemonTCGNewsSource,
    PokemonPressSource, PokemonJapanNewsSource,
)
from drop_alerts.storage import Store

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


class HTTP:
    def __init__(self, responses, store=None):
        self.responses, self.store, self.calls = responses, store, []

    async def get(self, url):
        self.calls.append(url)
        result = self.responses(url) if callable(self.responses) else self.responses[url]
        if isinstance(result, Exception):
            raise result
        return result


def test_gallery_identifies_products_without_claiming_price_stock_or_region_from_language():
    items = PokemonProductsSource().parse_listing(fixture("pokemon_products_es.html"))
    assert len(items) == 3
    first = items[0]
    assert first.id == "product:coleccion-artista-de-barajas"
    assert first.data["tcg"] == "pokemon" and first.data["language"] == "es"
    assert first.data["region"] == "GLOBAL" and first.data["provenance"] == "official"
    assert first.kind == "product" and first.state == "UNKNOWN"
    assert first.data["availability_verified"] is False and "price" not in first.data
    assert first.data["image_verified"] and first.data["image_url"].startswith("https://www.pokemon.com/")


def test_us_pokemon_center_exclusive_is_product_announcement_not_verified_center_stock():
    items = PokemonUSProductsSource().parse_listing(fixture("pokemon_products_us.html"))
    exclusive = next(item for item in items if "pokemon-center" in item.url)
    assert exclusive.source == "pokemon_products_us" and exclusive.data["region"] == "US"
    assert exclusive.data["language"] == "en"
    assert exclusive.state == "UNKNOWN" and exclusive.data["availability_verified"] is False


def test_tcg_news_filters_digital_strategy_interviews_and_tournament_results():
    items = PokemonTCGNewsSource().parse_listing(fixture("pokemon_tcg_news_es.html"))
    assert len(items) == 3
    assert all(item.state == "ANNOUNCED" and item.kind == "announcement" for item in items)
    assert all(item.data["published_at"] is None and item.data["coverage"] == "listing_only" for item in items)
    assert not any(word in item.title.casefold() for item in items for word in ["pocket", "entrevista", "estrategia", "campeonato"])


@pytest.mark.parametrize("source,body", [
    (PokemonProductsSource(), "<html><h1>Products</h1><ul></ul></html>"),
    (PokemonTCGNewsSource(), "<html><h1>News</h1><div class='news'></div></html>"),
    (PokemonPressSource(), "<html><h1>Press</h1></html>"),
    (PokemonJapanNewsSource(), "<html><h1>News</h1></html>"),
])
def test_changed_structures_do_not_confirm_empty_snapshots(source, body):
    with pytest.raises(ExtractionError):
        source.parse_listing(body)


@pytest.mark.parametrize("source", [PokemonProductsSource(), PokemonTCGNewsSource(), PokemonPressSource(), PokemonJapanNewsSource()])
def test_real_http_200_block_page_is_rejected(source):
    with pytest.raises(ExtractionError):
        source.parse_listing("<html><title>Pardon Our Interruption</title><h1>Please stand by</h1></html>")


def test_news_cards_missing_headings_are_structure_error():
    body = fixture("pokemon_tcg_news_es.html").replace("news__item-title", "changed-title")
    with pytest.raises(ExtractionError):
        PokemonTCGNewsSource().parse_listing(body)


def test_links_and_images_outside_allowlist_are_not_accepted():
    body = fixture("pokemon_products_es.html").replace('href="/es/jcc-pokemon/galeria-de-productos/', 'href="https://evil.test/es/jcc-pokemon/galeria-de-productos/')
    with pytest.raises(ExtractionError):
        PokemonProductsSource().parse_listing(body)
    body = fixture("pokemon_products_es.html").replace('src="/static-assets/', 'src="https://evil.test/static-assets/')
    assert all("image_url" not in item.data for item in PokemonProductsSource().parse_listing(body))
    body = fixture("pokemon_tcg_news_es.html").replace("https://www.pokemon.com/", "https://evil.test/")
    assert PokemonTCGNewsSource().parse_listing(body) == []


def test_press_filters_nonphysical_tcg_headlines_and_preserves_publication_date():
    items = PokemonPressSource().parse_listing(fixture("pokemon_press_listing.html"))
    assert len(items) == 2
    assert not any("Pocket" in item.title for item in items)
    item = next(item for item in items if "nueva-expansion" in item.url)
    assert item.data["published_at"] == "2026-08-20"


def test_press_article_omits_digital_and_prerelease_sections_in_physical_release_input():
    source = PokemonPressSource()
    item = next(item for item in source.parse_listing(fixture("pokemon_press_listing.html")) if "nueva-expansion" in item.url)
    source.parse_article(fixture("pokemon_press_article.html"), item)
    assert "6 de noviembre de 2026" in item.content
    assert "5 de noviembre" not in item.content and "24 de octubre" not in item.content
    assert "formato digital" not in item.content and "Prelanzamiento" not in item.content
    assert item.data["omitted_nonphysical_sections"] == 2
    assert item.data["published_at"] == "2026-08-20"
    assert item.data["image_verified"] and "imgeucdn.gamespress.com" in item.data["image_url"]
    assert item.state == "ANNOUNCED" and item.data["availability_verified"] is False


def test_press_article_rejects_missing_identity_or_body():
    source = PokemonPressSource()
    item = source.parse_listing(fixture("pokemon_press_listing.html"))[0]
    with pytest.raises(ExtractionError):
        source.parse_article("<html><h1>News</h1><main>Incomplete</main></html>", item)


def test_japanese_release_announcements_do_not_become_european_stock_or_figure_alerts():
    items = PokemonJapanNewsSource().parse_listing(fixture("pokemon_jp_news.html"))
    assert len(items) == 2
    assert all(item.data["tcg"] == "pokemon" and item.data["region"] == "JP" and item.data["language"] == "ja" for item in items)
    assert all(item.state == "ANNOUNCED" and item.data["published_at"].startswith("2026-") for item in items)
    assert not any("フィギュア" in item.title for item in items)


@pytest.mark.asyncio
async def test_listing_source_makes_one_request_and_never_fetches_blocked_product_details():
    source = PokemonProductsSource(max_items=2)
    http = HTTP({source.url: fixture("pokemon_products_es.html")})
    result = await source.fetch(http)
    assert len(result.items) == 2
    assert len(result.metadata["bootstrap_ids"]) == 3
    assert http.calls == [source.url]


@pytest.mark.asyncio
async def test_valid_news_without_product_scope_is_a_healthy_empty_result():
    source = PokemonTCGNewsSource()
    body = fixture("pokemon_tcg_news_es.html").replace("allNews products", "allNews strategy")
    result = await source.fetch(HTTP({source.url: body}))
    assert result.not_modified and not result.items


@pytest.mark.asyncio
async def test_listing_rotation_and_bootstrap_persist_without_historical_flood(tmp_path):
    source = PokemonProductsSource(max_items=2)
    path = str(tmp_path / "state.db")
    store = Store(path)
    config = Settings(llm_enabled=False, rules=[{"id": "all"}])
    http = HTTP({source.url: fixture("pokemon_products_es.html")}, store)
    first = await source.fetch(http)
    store.ingest(source.id, first, DetectionEngine(), RuleEngine(config.rules), config)
    store.close()
    store = Store(path)
    source = PokemonProductsSource(max_items=2)
    http = HTTP({source.url: fixture("pokemon_products_es.html")}, store)
    later = await source.fetch(http)
    store.ingest(source.id, later, DetectionEngine(), RuleEngine(config.rules), config)
    assert len(store.get_source_items(source.id)) == 3
    assert not store.due_notifications(10)
    store.close()


@pytest.mark.asyncio
async def test_new_product_receives_priority_without_stopping_rotating_history():
    source = PokemonProductsSource(max_items=2)
    store = Store(":memory:")
    original = source.parse_listing(fixture("pokemon_products_es.html"))
    config = Settings(llm_enabled=False, rules=[{"id": "all"}])
    store.ingest(source.id, FetchResult(original), DetectionEngine(), RuleEngine(config.rules), config)
    soup = BeautifulSoup(fixture("pokemon_products_es.html"), "html.parser")
    new_card = BeautifulSoup(str(soup.select_one("li.match")), "html.parser").select_one("li.match")
    new_card.find("a")["href"] += "-new"
    new_card.select_one(".season-info").string = "Nuevo producto de prueba"
    soup.select_one("ul.match-height").append(new_card)
    result = await source.fetch(HTTP({source.url: str(soup)}, store))
    assert len(result.items) == 2 and any(item.id.endswith("-new") for item in result.items)
    assert any(item.id in {item.id for item in original} for item in result.items)
    store.close()


@pytest.mark.asyncio
async def test_press_detail_failure_keeps_valid_siblings_and_full_bootstrap_inventory():
    source = PokemonPressSource()
    candidates = source.parse_listing(fixture("pokemon_press_listing.html"))
    wanted = next(item for item in candidates if "nueva-expansion" in item.url)
    responses = {source.url: fixture("pokemon_press_listing.html"),
                 wanted.url: fixture("pokemon_press_article.html")}
    responses.update({item.url: ExtractionError("temporary") for item in candidates if item.url != wanted.url})
    result = await source.fetch(HTTP(responses))
    assert len(result.items) == 1 and result.items[0].id == wanted.id
    assert len(result.metadata["errors"]) == 1
    assert set(result.metadata["bootstrap_ids"]) == {item.id for item in candidates}


@pytest.mark.asyncio
async def test_press_all_detail_failures_or_time_budget_do_not_confirm_a_baseline():
    source = PokemonPressSource(max_duration_seconds=0)
    with pytest.raises(ExtractionError):
        await source.fetch(HTTP({source.url: fixture("pokemon_press_listing.html")}))
    source = PokemonPressSource()
    candidates = source.parse_listing(fixture("pokemon_press_listing.html"))
    responses = {source.url: fixture("pokemon_press_listing.html"), **{item.url: ExtractionError("temporary") for item in candidates}}
    with pytest.raises(ExtractionError):
        await source.fetch(HTTP(responses))
