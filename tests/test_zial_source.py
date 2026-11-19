"""Zial public responses and explicit simulated state changes; no network."""
import json
from pathlib import Path

from bs4 import BeautifulSoup
import pytest

from drop_alerts.config import Settings
from drop_alerts.detection import DetectionEngine
from drop_alerts.models import ExtractionError, Item
from drop_alerts.rules import RuleEngine
from drop_alerts.sources.common import jsonld
from drop_alerts.sources.zial import ZialTCGSource, CATALOGUES, ORIGIN, SEED_URL, _game, _relevant
from drop_alerts.storage import Store

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name):
    return (FIXTURES / ("zial_" + name + ".html")).read_text(encoding="utf-8")


def candidate(name="seed"):
    soup = BeautifulSoup(fixture(name), "html.parser")
    info = next(row for row in jsonld(soup) if row.get("@type") == "Product")
    identity = soup.select_one("div.product[id]")["id"].removeprefix("product-")
    return Item("product:" + identity, "zial_tcg", info["name"], info["url"], kind="product")


def alter(name="seed", *, stock=None, code=None, price=None, sku=None, labels=None):
    soup = BeautifulSoup(fixture(name), "html.parser")
    script = soup.select_one('script[type="application/ld+json"]')
    raw = json.loads(script.get_text())
    product = raw["@graph"][0]
    if code is not None:
        product["offers"][0]["availability"] = code
    if price is not None:
        product["offers"][0]["price"] = price
    if sku is not None:
        product["sku"] = sku
    if stock is not None:
        soup.select_one(".summary p.stock").string = stock
    if labels is not None:
        root = soup.select_one("div.product[id]")
        root["class"] = [value for value in root["class"] if not value.startswith(("product_cat-", "product_tag-"))] + ["product_cat-" + value for value in labels]
        desc = soup.select_one("#tab-description")
        desc.clear()
        desc.string = "Información del producto."
    script.string = json.dumps(raw)
    return str(soup)


def listing(entries):
    return '<html><h1>Juegos de Cartas</h1><ul class="products">' + "".join(
        '<li class="product type-product post-' + identity + ' product_cat-juegos-cartas product_cat-magic">'
        '<a class="woocommerce-LoopProduct-link" href="' + url + '"><h2 class="woocommerce-loop-product__title">' + title + '</h2></a></li>'
        for identity, url, title in entries) + '</ul></html>'


def sample(identity="1", state="AVAILABLE"):
    url = ORIGIN + "/producto/test-" + identity + "/"
    title = "Magic The Gathering Booster " + identity
    stock = "Hay existencias" if state == "AVAILABLE" else "Sin existencias"
    code = "InStock" if state == "AVAILABLE" else "OutOfStock"
    info = {"@type": "Product", "name": title, "url": url, "sku": "EAN-" + identity,
            "image": ORIGIN + "/wp-content/uploads/sample.jpg", "offers": [{"@type": "Offer", "url": url,
            "price": "25.00", "priceCurrency": "EUR", "availability": "https://schema.org/" + code}]}
    body = '<html><head><script type="application/ld+json">' + json.dumps(info) + '</script></head><body>'
    body += '<div id="product-' + identity + '" class="product type-product post-' + identity + ' product-type-simple product_cat-juegos-cartas product_cat-magic">'
    body += '<div class="summary entry-summary"><h1 class="product_title">' + title + '</h1><p class="price"><span class="woocommerce-Price-amount"><bdi>25,00<span class="woocommerce-Price-currencySymbol">€</span></bdi></span></p><p class="stock">' + stock + '</p></div>'
    body += '<div id="tab-description">Un producto de cartas.</div></div></body></html>'
    return url, body


class FakeHTTP:
    def __init__(self, pages, store=None):
        self.pages, self.store, self.calls = pages, store, []

    async def get(self, url):
        self.calls.append(url)
        result = self.pages.get(url, ExtractionError("HTTP 404"))
        if isinstance(result, BaseException):
            raise result
        return result


def pages(entries=()):
    result = {base: listing(entries) for base in CATALOGUES}
    result[SEED_URL] = fixture("seed")
    for identity, url, _ in entries:
        result[url] = sample(identity)[1]
    return result


def ingest(store, result, config):
    return store.ingest("zial_tcg", result, DetectionEngine(), RuleEngine(config.rules), config)


def test_real_catalogues_have_woo_id_pagination_and_only_product_links():
    source = ZialTCGSource()
    for name, base in zip(("catalogue", "preorder", "accessories"), CATALOGUES):
        items, next_url, complete = source.parse_listing(fixture(name), base)
        assert len(items) == 6 and complete
        assert all(item.id.startswith("product:") and item.source == "zial_tcg" for item in items)
        assert next_url == base + "page/2/"


def test_seed_is_preorder_despite_purchasable_units_and_uses_full_price():
    item = ZialTCGSource().parse_detail(fixture("seed"), candidate())
    assert item.id == "product:11533" and item.url == SEED_URL
    assert item.state == "UPCOMING" and item.data["tcg"] == "magic"
    assert item.data["price"] == "319.95" and item.data["currency"] == "EUR"
    assert item.data["availability_verified"] and "reservables" in item.data["summary"]
    assert item.data["image_verified"]


@pytest.mark.parametrize("name,state,price,game", [("available", "AVAILABLE", "19.95", "pokemon"),
    ("unavailable", "UNAVAILABLE", None, "one_piece"), ("accessory", "UPCOMING", "29.95", "riftbound"),
    ("sale", "UPCOMING", "17.95", "jurassic_park")])
def test_real_available_soldout_accessory_and_discount(name, state, price, game):
    item = ZialTCGSource().parse_detail(fixture(name), candidate(name))
    assert (item.state, item.data.get("price"), item.data.get("tcg")) == (state, price, game)
    assert item.data["price_verified"] == (price is not None)


def test_sku_is_a_merchant_reference_not_the_woo_identity():
    item = ZialTCGSource().parse_detail(alter(sku="5010995555778"), candidate())
    assert item.id == "product:11533" and item.data["sku"] == "5010995555778"


@pytest.mark.parametrize("wording", ["No disponible", "No está disponible", "No hay unidades disponibles", "No hay existencias", "Sin stock"])
def test_negative_stock_does_not_become_available(wording):
    with pytest.raises(ExtractionError):
        ZialTCGSource().parse_detail(alter(stock=wording), candidate())
    item = ZialTCGSource().parse_detail(alter(stock=wording, code="https://schema.org/OutOfStock"), candidate())
    assert item.state == "UNAVAILABLE"


@pytest.mark.parametrize("wording,state", [("Disponible para reserva", "UPCOMING"), ("Disponible bajo pedido", "UNKNOWN"), ("Próximamente", "UPCOMING")])
def test_explicit_stock_context_overrides_generic_instock(wording, state):
    item = ZialTCGSource().parse_detail(alter(stock=wording, labels=["juegos-cartas", "magic"]), candidate())
    assert item.state == state


@pytest.mark.parametrize("title", ["Set de figuras Gundam", "Caja de figuras Pokemon", "Pokemon PVC Figure", "Entrada torneo Magic", "Ruleta One Piece", "Tarjeta regalo"])
def test_figures_events_and_gift_cards_are_outside_tcg_scope(title):
    assert not _relevant(title, ["juegos-cartas", "gundam", "pokemon"])


def test_mixed_card_collection_is_allowed_and_game_ambiguity_remains_unknown():
    assert _relevant("Caja 4 sobres Pokemon con figura", ["juegos-cartas", "pokemon"])
    assert _game("Fundas Magic y Pokemon", ["accesorios"]) is None
    assert _game("Pokemon illustration Magic", ["magic"]) == "magic"


@pytest.mark.parametrize("title", ["Pikachu Limited Edition", "Pikachu Figurine", "One Piece Collector Edition"])
def test_a_franchise_category_does_not_establish_a_tcg_product(title):
    assert not _relevant(title, ["pokemon", "one-piece"])


@pytest.mark.parametrize("change", ["price", "foreign_url", "identity", "variable", "offers", "blocked"])
def test_malformed_or_contradictory_product_fails_without_guessing(change):
    soup = BeautifulSoup(fixture("seed"), "html.parser")
    if change == "price":
        body = alter(price="1.00")
    elif change == "blocked":
        body = "<html><title>Just a moment...</title></html>"
    else:
        script = soup.select_one('script[type="application/ld+json"]')
        raw = json.loads(script.get_text())
        if change == "foreign_url":
            raw["@graph"][0]["offers"][0]["url"] = "https://evil.test/producto/test/"
        elif change == "identity":
            soup.select_one("div.product[id]")["id"] = "product-2"
        elif change == "variable":
            root = soup.select_one("div.product[id]")
            root["class"] = [value for value in root["class"] if value != "product-type-simple"] + ["product-type-variable"]
        else:
            raw["@graph"][0]["offers"] = [*raw["@graph"][0]["offers"], {}]
        script.string = json.dumps(raw)
        body = str(soup)
    with pytest.raises(ExtractionError):
        ZialTCGSource().parse_detail(body, candidate())


def test_related_cards_cannot_supply_main_stock_price_or_image():
    soup = BeautifulSoup(fixture("unavailable"), "html.parser")
    related = BeautifulSoup('<ul class="related"><li class="product"><p class="stock">Hay existencias</p><p class="price">1,00 €</p><img src="https://evil.test/fake.jpg"></li></ul>', "html.parser")
    soup.select_one("div.product[id]").append(related)
    item = ZialTCGSource().parse_detail(str(soup), candidate("unavailable"))
    assert item.state == "UNAVAILABLE" and "price" not in item.data
    assert item.data["image_url"].startswith(ORIGIN + "/wp-content/uploads/")


def test_deposit_and_non_eur_amounts_are_not_claimed_as_full_price():
    soup = BeautifulSoup(fixture("seed"), "html.parser")
    soup.select_one(".summary").append(BeautifulSoup('<div class="awcdp-deposits-wrapper">Señal 50%</div>', "html.parser"))
    item = ZialTCGSource().parse_detail(str(soup), candidate())
    assert not item.data["price_verified"] and "price" not in item.data
    soup = BeautifulSoup(fixture("seed"), "html.parser")
    script = soup.select_one('script[type="application/ld+json"]')
    info = json.loads(script.get_text())
    info["@graph"][0]["offers"][0]["priceCurrency"] = "USD"
    script.string = json.dumps(info)
    item = ZialTCGSource().parse_detail(str(soup), candidate())
    assert not item.data["price_verified"] and "price" not in item.data and "currency" not in item.data


@pytest.mark.asyncio
async def test_seed_is_checked_every_round_even_with_one_slot_and_no_catalogues():
    store, source = Store(":memory:"), ZialTCGSource(max_items=1)
    http = FakeHTTP({SEED_URL: fixture("seed")}, store)
    config = Settings(llm_enabled=False, rules=[{"id": "all"}])
    for _ in range(2):
        result = await source.fetch(http)
        ingest(store, result, config)
        assert [item.id for item in result.items] == ["product:11533"]
        assert result.metadata["catalogue_pages"] == 0
    assert http.calls == [SEED_URL, SEED_URL] and not store.due_notifications(10)
    store.close()


@pytest.mark.asyncio
async def test_seed_failure_recovers_silently_after_catalogue_initialized_and_restart(tmp_path):
    path = str(tmp_path / "state.db")
    config = Settings(llm_enabled=False, rules=[{"id": "all"}])
    entries = [("1", sample()[0], "Magic The Gathering Booster")]
    responses = pages(entries)
    responses[SEED_URL] = ExtractionError("HTTP 503")
    store = Store(path)
    first = await ZialTCGSource(max_items=3, max_pages=1).fetch(FakeHTTP(responses, store))
    assert first.metadata["errors"] == ["seed:unavailable"]
    ingest(store, first, config)
    store.close()
    store = Store(path)
    responses[SEED_URL] = fixture("seed")
    second = await ZialTCGSource(max_items=3, max_pages=1).fetch(FakeHTTP(responses, store))
    ingest(store, second, config)
    assert second.metadata["discovery_inventories"]["seed:commander-warhammer"] == ["product:11533"]
    assert not store.due_notifications(10)
    responses[SEED_URL] = alter(stock="Sin existencias", code="https://schema.org/OutOfStock")
    changed = await ZialTCGSource(max_items=3, max_pages=1).fetch(FakeHTTP(responses, store))
    ingest(store, changed, config)
    assert store.due_notifications(1)[0][0].event_type == "availability.changed"
    store.close()


@pytest.mark.asyncio
async def test_seed_survives_catalogue_failures_and_partial_details_do_not_replace_state():
    config = Settings(llm_enabled=False)
    store = Store(":memory:")
    http = FakeHTTP({SEED_URL: fixture("seed")}, store)
    result = await ZialTCGSource(max_items=3, max_pages=1).fetch(http)
    assert [item.id for item in result.items] == ["product:11533"]
    assert result.metadata["errors"] == ["catalogue:unavailable"] * 3
    assert set(result.metadata["discovery_inventories"]) == {"seed:commander-warhammer"}
    ingest(store, result, config)
    before = store.item("zial_tcg", "product:11533")[0].digest
    http.pages[SEED_URL] = ExtractionError("HTTP 404")
    with pytest.raises(ExtractionError):
        await ZialTCGSource(max_items=1).fetch(http)
    assert store.item("zial_tcg", "product:11533")[0].digest == before
    store.close()


@pytest.mark.asyncio
async def test_deferred_catalogue_items_are_silent_and_genuine_new_products_notify_once(tmp_path):
    store = Store(str(tmp_path / "state.db"))
    config = Settings(llm_enabled=False, rules=[{"id": "all"}])
    entries = [(str(index), sample(str(index))[0], "Magic The Gathering Booster") for index in (1, 2, 3)]
    http = FakeHTTP(pages(entries), store)
    for _ in range(4):
        result = await ZialTCGSource(max_items=2, max_pages=1).fetch(http)
        ingest(store, result, config)
    assert not store.due_notifications(20)
    new_entry = ("4", sample("4")[0], "Magic The Gathering New Booster")
    http.pages.update(pages(entries + [new_entry]))
    for _ in range(5):
        result = await ZialTCGSource(max_items=3, max_pages=1).fetch(http)
        ingest(store, result, config)
    assert len(store.due_notifications(20)) == 1
    assert store.due_notifications(1)[0][0].item_id == "product:4"
    store.close()


@pytest.mark.asyncio
async def test_known_products_outside_catalogue_continue_to_detect_restock():
    store = Store(":memory:")
    config = Settings(llm_enabled=False, rules=[{"id": "all"}])
    entry = ("1", sample()[0], "Magic The Gathering Booster")
    responses = pages([entry])
    responses[entry[1]] = sample(state="UNAVAILABLE")[1]
    ingest(store, await ZialTCGSource(max_items=2, max_pages=1).fetch(FakeHTTP(responses, store)), config)
    responses.update({base: listing([]) for base in CATALOGUES})
    responses[entry[1]] = sample()[1]
    ingest(store, await ZialTCGSource(max_items=2, max_pages=1).fetch(FakeHTTP(responses, store)), config)
    assert store.due_notifications(1)[0][0].event_type == "availability.changed"
    store.close()


@pytest.mark.asyncio
async def test_request_timeouts_are_local_and_the_seed_does_not_block_other_products(monkeypatch):
    import drop_alerts.sources.zial as module
    responses = pages([("1", sample()[0], "Magic The Gathering Booster")])
    responses[SEED_URL] = TimeoutError()
    actual = module.asyncio.wait_for
    timeouts = []
    async def bounded(awaitable, timeout):
        timeouts.append(timeout)
        return await actual(awaitable, timeout)
    monkeypatch.setattr(module.asyncio, "wait_for", bounded)
    result = await ZialTCGSource(max_items=2, max_pages=1).fetch(FakeHTTP(responses))
    assert [item.id for item in result.items] == ["product:1"] and max(timeouts) <= 20


@pytest.mark.asyncio
async def test_corrupt_cursors_and_foreign_urls_never_visit_other_origins():
    store = Store(":memory:")
    store.set_meta("zial:cursor", '"invalid"')
    store.set_meta("zial:page:" + CATALOGUES[0], json.dumps("https://evil.test/"))
    http = FakeHTTP(pages(), store)
    result = await ZialTCGSource(max_items=2).fetch(http)
    assert result.items and all(url.startswith(ORIGIN + "/") and "?" not in url for url in http.calls)
    store.close()


@pytest.mark.asyncio
async def test_zero_budget_and_all_failures_are_extraction_errors():
    with pytest.raises(ExtractionError):
        await ZialTCGSource(max_duration_seconds=0).fetch(FakeHTTP({}))
    with pytest.raises(ExtractionError):
        await ZialTCGSource().fetch(FakeHTTP({}))
