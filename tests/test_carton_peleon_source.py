"""Reduced real Odoo captures and explicit simulated changes, always offline."""
import copy
import json
from pathlib import Path

from bs4 import BeautifulSoup
import pytest

from drop_alerts.config import Settings
from drop_alerts.detection import DetectionEngine
from drop_alerts.models import ExtractionError, Item
from drop_alerts.rules import RuleEngine
from drop_alerts.sources.carton_peleon import CartonPeleonSource, CATALOGUES, ORIGIN, SEED_URL, STOCK_URL, _game, _relevant, _url
from drop_alerts.sources.common import jsonld
from drop_alerts.storage import Store

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name):
    return (FIXTURES / ("carton_" + name + ".html")).read_text(encoding="utf-8")


def stock_fixture():
    return json.loads((FIXTURES / "carton_stock.json").read_text(encoding="utf-8"))


def candidate(name="seed"):
    soup = BeautifulSoup(fixture(name), "html.parser")
    info = next(row for row in jsonld(soup) if row.get("@type") == "Product")
    identity = soup.select_one('input[name="product_id"]')["value"]
    return Item("variant:" + identity, "carton_peleon", info["name"], info["url"], kind="product")


def edit(name="available", mutate=lambda soup, info: None):
    soup = BeautifulSoup(fixture(name), "html.parser")
    script = soup.select_one('script[type="application/ld+json"]')
    raw = json.loads(script.get_text())
    info = next(row for row in raw if row.get("@type") == "Product")
    mutate(soup, info)
    script.string = json.dumps(raw)
    return str(soup)


def listing(entries, next_url=None):
    body = '<html><section id="o_wsale_products_grid">'
    for identity, url, title in entries:
        variant = str(1000 + int(identity))
        body += '<form class="oe_product_cart"><h2 class="o_wsale_products_item_title"><a href="' + url + '">' + title + '</a></h2>'
        body += '<button class="o_add_wishlist" data-product-template-id="' + identity + '" data-product-product-id="' + variant + '"></button></form>'
    body += '</section>'
    if next_url:
        body += '<ul class="pagination"><li><a href="' + next_url + '"><span class="oi-chevron-right" title="Siguiente"></span></a></li></ul>'
    return body + '</html>'


def sample(identity="1", state="AVAILABLE"):
    """Synthetic identities and stock, derived from actual single-variant markup."""
    variant, title = str(1000 + int(identity)), "Magic The Gathering Booster " + identity
    url = ORIGIN + "/shop/magic-booster-" + identity

    def mutate(soup, info):
        main = soup.select_one("#o_wsale_product_details_content")
        main.select_one("h1").string = title
        main.select_one('input[name="product_id"]')["value"] = variant
        main.select_one('input[name="product_template_id"]')["value"] = identity
        breadcrumb = soup.select_one(".o_wsale_breadcrumb")
        breadcrumb.clear()
        breadcrumb.append(BeautifulSoup('<a href="/shop/category/juegos-de-cartas-204">Juegos de Cartas</a><a href="/shop/category/juegos-de-cartas-magic-the-gathering-113">Magic</a>', "html.parser"))
        info.update(name=title, url=url)
        info.pop("image", None)
    body = edit(mutate=mutate)
    rpc = stock_fixture()
    rpc["result"].update(product_id=int(variant), product_template_id=int(identity), display_name=title,
                         free_qty=5 if state == "AVAILABLE" else 0)
    return url, body, rpc


class FakeHTTP:
    def __init__(self, pages, store=None, rpc=None):
        self.pages, self.store, self.calls = pages, store, []
        self.rpc, self.posts = rpc or {}, []

    async def get(self, url):
        self.calls.append(url)
        result = self.pages.get(url, ExtractionError("HTTP 404"))
        if isinstance(result, BaseException):
            raise result
        return result

    async def post_json(self, url, payload):
        self.calls.append(url)
        self.posts.append((url, payload))
        result = self.rpc.get(payload["params"]["product_id"], ExtractionError("RPC offline"))
        if isinstance(result, BaseException):
            raise result
        return copy.deepcopy(result)


def http_for(identities=("1", "2", "3"), *, store=None):
    samples = {identity: sample(identity) for identity in identities}
    entries = [(identity, data[0], "Magic The Gathering Booster " + identity) for identity, data in samples.items()]
    pages = {base: listing(entries) for base in CATALOGUES}
    pages[SEED_URL] = fixture("seed")
    pages.update({data[0]: data[1] for data in samples.values()})
    rpc = {1000 + int(identity): data[2] for identity, data in samples.items()}
    return FakeHTTP(pages, store, rpc)


def ingest(store, result, config):
    return store.ingest("carton_peleon", result, DetectionEngine(), RuleEngine(config.rules), config)


def test_real_catalogues_verify_template_variant_and_newest_pagination():
    source = CartonPeleonSource()
    for name, base in zip(("catalogue", "accessories"), CATALOGUES):
        items, next_url, complete = source.parse_listing(fixture(name), base)
        assert len(items) == 6 and complete
        assert all(item.id.startswith("variant:") and item.id != "variant:" + item.data["template_id"] for item in items)
        assert next_url == base.replace("?", "/page/2?")
        assert all("?" not in item.url and item.url.startswith(ORIGIN + "/shop/") for item in items)


def test_seed_is_not_yet_reservable_and_hidden_zero_and_editor_price_are_ignored():
    item = CartonPeleonSource().parse_detail(fixture("seed"), candidate())
    assert item.id == "variant:23219" and item.data["template_id"] == "19822"
    assert item.state == "UPCOMING" and item.data["tcg"] == "magic"
    assert not item.data["price_verified"] and "price" not in item.data
    assert "31/01/2027" not in item.content and "FECHA POR DETERMINAR" in item.content
    assert item.data["image_verified"] and item.data["availability_verified"]
    assert "para reservar" in item.data["availability_evidence"]


@pytest.mark.parametrize("name,state,price,game", [("available", "UNKNOWN", "4.49", None),
    ("preorder", "UPCOMING", "20.99", "magic"), ("unavailable", "UNAVAILABLE", "4.50", "magic"),
    ("reserve_card", "UPCOMING", "29.99", "magic")])
def test_real_prices_reservations_and_online_soldout(name, state, price, game):
    item = CartonPeleonSource().parse_detail(fixture(name), candidate(name))
    assert (item.state, item.data.get("price"), item.data.get("tcg")) == (state, price, game)
    assert item.data["price_verified"] and item.data["currency"] == "EUR"
    assert item.data["availability_verified"] == (state != "UNKNOWN")


def test_sku_is_not_template_or_variant_identity():
    item = CartonPeleonSource().parse_detail(fixture("available"), candidate("available"))
    assert item.id == "variant:23236" and item.data["template_id"] == "19839"
    assert item.data["sku"] == "8437028641748"


@pytest.mark.parametrize("title", ["Figura Pokemon Pikachu", "Estatua One Piece", "Entrada torneo Magic", "Tarjeta regalo", "Juego de mesa Pokemon"])
def test_outside_tcg_products_are_excluded(title):
    assert not _relevant(title, ["204", "160"])


def test_game_uses_product_categories_and_generic_accessories_remain_unassigned():
    assert _game("Pokemon illustration Magic", ["113"]) == "magic"
    assert _game("Fundas opacas standard", ["160"]) is None
    assert _game("Pokemon y One Piece", ["204"]) is None
    assert _game("Sobre Weiß Schwarz", ["204"]) == "weiss_schwarz"
    assert not _relevant("Figura Magic", ["113"])


def test_accessory_category_does_not_admit_unrelated_boardgame_accessories():
    assert _relevant("Fundas opacas standard", ["160"])
    assert _relevant("Tapete Playmat Mox Emerald Magic", ["160"])
    assert not _relevant("Bolsa de dados de rol", ["160"])
    assert not _relevant("Set dados Chessex", ["160"])
    assert not _relevant("Baraja Tarot", ["204"])


@pytest.mark.parametrize("url", ["https://evil.test/shop/product-1", ORIGIN + "/shop/cart", ORIGIN + "/shop/test-1?add_qty=1",
    ORIGIN + "/shop/test-1#other", ORIGIN + "/shop/test%2fshop-1", ORIGIN + "/my/account"])
def test_product_allowlist_rejects_actions_external_and_ambiguous_paths(url):
    assert _url(url, product=True) is None


def test_unicode_product_slug_is_supported_and_queries_only_allow_observed_sort():
    assert _url("/shop/juegos-de-cartas-204/sobre-weiß-schwarz-12", product=True) == ORIGIN + "/shop/sobre-wei%C3%9F-schwarz-12"
    assert _url(CATALOGUES[0], catalogue=True) == CATALOGUES[0]
    assert _url(CATALOGUES[0] + "&search=all", catalogue=True) is None


@pytest.mark.parametrize("change", ["variant", "template", "multi", "options", "metadata", "offers", "price", "notice", "stock"])
def test_incomplete_contradictory_and_multi_variant_details_fail_closed(change):
    def mutate(soup, info):
        if change == "variant":
            soup.select_one('input[name="product_id"]')["value"] = "1"
        elif change == "template":
            soup.select_one('input[name="product_template_id"]')["value"] = "1"
        elif change == "multi":
            soup.select_one(".js_add_cart_variants")["data-attribute-exclusions"] = '{"mapped_attribute_names":{"1":"Idioma"}}'
        elif change == "options":
            soup.select_one(".js_add_cart_variants").append(BeautifulSoup('<li><select><option>English</option></select></li>', "html.parser"))
        elif change == "metadata":
            info["url"] = "https://evil.test/shop/test-1"
        elif change == "offers":
            info["offers"] = [info["offers"], {}]
        elif change == "price":
            info["offers"]["price"] = "99.00"
        elif change == "notice":
            soup.select_one(".cp-dispo")["data-pid"] = "2"
        elif change == "stock":
            info["offers"]["availability"] = "https://schema.org/InStock"
    name = "unavailable" if change in ("notice", "stock") else "available"
    with pytest.raises(ExtractionError):
        CartonPeleonSource().parse_detail(edit(name, mutate=mutate), candidate(name))


def test_hidden_price_and_deposit_words_do_not_become_full_price():
    def hidden(soup, info):
        soup.select_one(".product_price")["class"] = ["product_price", "d-none"]
    item = CartonPeleonSource().parse_detail(edit(mutate=hidden), candidate("available"))
    assert not item.data["price_verified"]
    def deposit(soup, info):
        soup.select_one(".product_price").append(BeautifulSoup('<span>Señal / depósito de reserva</span>', "html.parser"))
    item = CartonPeleonSource().parse_detail(edit(mutate=deposit), candidate("available"))
    assert not item.data["price_verified"]


def test_hidden_main_product_is_not_a_public_price():
    def hidden(soup, info):
        soup.select_one("#o_wsale_product_details_content")["hidden"] = "hidden"
    item = CartonPeleonSource().parse_detail(edit(mutate=hidden), candidate("available"))
    assert not item.data["price_verified"] and "price" not in item.data


def test_incomplete_variant_attribute_contract_is_not_treated_as_single_variant():
    def mutate(soup, info):
        soup.select_one(".js_add_cart_variants")["data-attribute-exclusions"] = '{}'
    with pytest.raises(ExtractionError):
        CartonPeleonSource().parse_detail(edit(mutate=mutate), candidate("available"))


def test_related_stock_and_generic_instock_never_prove_main_availability():
    def mutate(soup, info):
        soup.body.append(BeautifulSoup('<aside class="related"><div class="ecp-stock-aviso">Solo quedan 5 unidades</div></aside>', "html.parser"))
    item = CartonPeleonSource().parse_detail(edit(mutate=mutate), candidate("available"))
    assert item.state == "UNKNOWN" and not item.data["availability_verified"]


def test_actual_readonly_rpc_confirms_normal_stock_without_using_its_price():
    source = CartonPeleonSource()
    item = source.parse_detail(fixture("available"), candidate("available"))
    payload = stock_fixture()
    payload["result"]["price"] = 999
    item = source.parse_stock(payload, item)
    assert item.state == "AVAILABLE" and item.data["price"] == "4.49"
    assert item.data["availability_verified"] and "free_qty" not in item.data
    assert source.stock_request(item)["params"] == {"product_template_id": 19839, "product_id": 23236, "combination": [], "add_qty": 1, "uom_id": None, "context": {}}


@pytest.mark.parametrize("free,allow,state", [(0, False, "UNAVAILABLE"), (0, True, "UNKNOWN"), (1, False, "AVAILABLE"), (0.5, False, "UNAVAILABLE")])
def test_rpc_stock_respects_backorders(free, allow, state):
    source = CartonPeleonSource()
    payload = stock_fixture()
    payload["result"].update(free_qty=free, allow_out_of_stock_order=allow)
    item = source.parse_stock(payload, source.parse_detail(fixture("available"), candidate("available")))
    assert item.state == state


@pytest.mark.parametrize("field,value", [("product_id", 19839), ("product_template_id", "19839"),
    ("is_combination_possible", False), ("is_storable", "true"), ("free_qty", -1), ("free_qty", float("nan")),
    ("free_qty", True), ("free_qty", "18"), ("allow_out_of_stock_order", "false"), ("prevent_zero_price_sale", None),
    ("cart_qty", None), ("max_combo_quantity", -1)])
def test_rpc_validates_id_types_quantities_and_flags(field, value):
    source = CartonPeleonSource()
    payload = stock_fixture()
    payload["result"][field] = value
    with pytest.raises(ExtractionError):
        source.parse_stock(payload, source.parse_detail(fixture("available"), candidate("available")))


def test_rpc_combo_limit_restricts_stock_and_non_storable_remains_uncertain():
    source = CartonPeleonSource()
    payload = stock_fixture()
    payload["result"]["max_combo_quantity"] = 0
    item = source.parse_stock(payload, source.parse_detail(fixture("available"), candidate("available")))
    assert item.state == "UNAVAILABLE"
    payload["result"]["is_storable"] = False
    item = source.parse_stock(payload, source.parse_detail(fixture("available"), candidate("available")))
    assert item.state == "UNKNOWN" and not item.data["availability_verified"]


def test_rpc_prevent_zero_price_sale_is_a_purchase_block_even_with_stock():
    source = CartonPeleonSource()
    payload = stock_fixture()
    payload["result"]["prevent_zero_price_sale"] = True
    item = source.parse_stock(payload, source.parse_detail(fixture("available"), candidate("available")))
    assert item.state == "UNKNOWN" and not item.data["availability_verified"]
    assert item.data["price"] == "4.49"


@pytest.mark.asyncio
async def test_seed_first_every_round_even_one_slot_without_catalogue_or_rpc():
    store, source = Store(":memory:"), CartonPeleonSource(max_items=1)
    http = FakeHTTP({SEED_URL: fixture("seed")}, store)
    config = Settings(llm_enabled=False, rules=[{"id": "all"}])
    for _ in range(2):
        result = await source.fetch(http)
        assert [item.id for item in result.items] == ["variant:23219"]
        assert result.metadata["catalogue_pages"] == 0
        ingest(store, result, config)
    assert http.calls == [SEED_URL, SEED_URL] and not http.posts
    assert not store.due_notifications(10)
    store.close()


@pytest.mark.asyncio
async def test_html_stock_with_hidden_price_checks_rpc_purchase_block():
    def mutate(soup, info):
        main = soup.select_one("#o_wsale_product_details_content")
        main.select_one(".product_price")["class"] = ["product_price", "d-none"]
        main.append(BeautifulSoup('<div class="ecp-stock-aviso">Solo quedan 2 unidades</div>', "html.parser"))
    body = edit(mutate=mutate)
    item = candidate("available")
    entries = [("19839", item.url, item.title)]
    catalogue = listing(entries).replace('data-product-product-id="20839"', 'data-product-product-id="23236"')
    rpc = stock_fixture()
    rpc["result"]["prevent_zero_price_sale"] = True
    pages = {SEED_URL: fixture("seed"), item.url: body, **{base: catalogue for base in CATALOGUES}}
    http = FakeHTTP(pages, rpc={23236: rpc})
    result = await CartonPeleonSource(max_items=2, max_pages=1).fetch(http)
    assert result.items[1].state == "UNKNOWN" and not result.items[1].data["price_verified"]
    assert len(http.posts) == 1


@pytest.mark.asyncio
async def test_seed_initial_failure_recovers_silently_after_restart(tmp_path):
    path = str(tmp_path / "state.db")
    config = Settings(llm_enabled=False, rules=[{"id": "all"}])
    store = Store(path)
    http = http_for(("1",), store=store)
    http.pages[SEED_URL] = ExtractionError("HTTP 503")
    ingest(store, await CartonPeleonSource(max_items=2, max_pages=1).fetch(http), config)
    store.close()
    store = Store(path)
    http.store, http.pages[SEED_URL] = store, fixture("seed")
    result = await CartonPeleonSource(max_items=2, max_pages=1).fetch(http)
    assert result.metadata["discovery_inventories"]["seed:commander-warhammer"] == ["variant:23219"]
    ingest(store, result, config)
    assert not store.due_notifications(10)
    store.close()


@pytest.mark.asyncio
async def test_rpc_failure_discards_only_detail_and_preserves_previous_available():
    store = Store(":memory:")
    config = Settings(llm_enabled=False, rules=[{"id": "all"}])
    http = http_for(("1",), store=store)
    source = CartonPeleonSource(max_items=2, max_pages=1)
    ingest(store, await source.fetch(http), config)
    old = store.item(source.id, "variant:1001")[0].digest
    http.rpc[1001] = ExtractionError("RPC 503")
    result = await source.fetch(http)
    assert [item.id for item in result.items] == ["variant:23219"]
    assert result.metadata["errors"] == ["detail:unavailable"]
    ingest(store, result, config)
    assert store.item(source.id, "variant:1001")[0].digest == old
    assert not store.due_notifications(10)
    store.close()


@pytest.mark.asyncio
async def test_deferred_initial_inventory_is_silent_and_true_new_product_notifies_once(tmp_path):
    store = Store(str(tmp_path / "state.db"))
    config = Settings(llm_enabled=False, rules=[{"id": "all"}])
    http = http_for(store=store)
    for _ in range(5):
        ingest(store, await CartonPeleonSource(max_items=2, max_pages=1).fetch(http), config)
    assert not store.due_notifications(20)
    http = http_for(("1", "2", "3", "4"), store=store)
    for _ in range(6):
        ingest(store, await CartonPeleonSource(max_items=3, max_pages=1).fetch(http), config)
    notifications = store.due_notifications(20)
    assert len(notifications) == 1 and notifications[0][0].item_id == "variant:1004"
    store.close()


@pytest.mark.asyncio
async def test_known_item_outside_current_catalogue_still_detects_restock():
    store = Store(":memory:")
    config = Settings(llm_enabled=False, rules=[{"id": "all"}])
    http = http_for(("1",), store=store)
    http.rpc[1001]["result"]["free_qty"] = 0
    ingest(store, await CartonPeleonSource(max_items=2, max_pages=1).fetch(http), config)
    http.pages.update({base: listing([]) for base in CATALOGUES})
    http.rpc[1001]["result"]["free_qty"] = 2
    ingest(store, await CartonPeleonSource(max_items=2, max_pages=1).fetch(http), config)
    notification = store.due_notifications(1)[0][0]
    assert notification.event_type == "availability.changed" and notification.item_id == "variant:1001"
    store.close()


@pytest.mark.asyncio
async def test_catalogue_archive_rotates_persistently_and_cursor_is_not_foreign(tmp_path):
    store = Store(str(tmp_path / "state.db"))
    http = http_for(("1",), store=store)
    base = CATALOGUES[0]
    page2, page3 = base.replace("?", "/page/2?"), base.replace("?", "/page/3?")
    entries = [("1", sample()[0], "Magic The Gathering Booster 1")]
    http.pages.update({base: listing(entries, page2), page2: listing(entries, page3), page3: listing(entries)})
    await CartonPeleonSource(max_items=2).fetch(http)
    assert page2 in http.calls
    http.calls.clear()
    await CartonPeleonSource(max_items=2).fetch(http)
    assert page3 in http.calls and page2 not in http.calls
    store.set_meta("carton_peleon:page:" + base, json.dumps("https://evil.test/"))
    store.set_meta("carton_peleon:cursor", '"invalid"')
    http.calls.clear()
    await CartonPeleonSource(max_items=2).fetch(http)
    assert all(url.startswith(ORIGIN + "/") for url in http.calls)
    store.close()


@pytest.mark.asyncio
async def test_partial_catalogue_cards_do_not_close_inventory_and_http_error_is_not_soldout():
    http = http_for(("1",))
    http.pages[CATALOGUES[0]] = listing([("1", sample()[0], "Magic The Gathering Booster")]).replace('data-product-product-id="1001"', '')
    result = await CartonPeleonSource(max_items=2, max_pages=1).fetch(http)
    assert len(result.items) == 2 and result.items[1].state == "AVAILABLE"
    assert "catalogue:/shop/category/juegos-de-cartas-204" not in result.metadata["discovery_inventories"]


@pytest.mark.asyncio
async def test_request_timeouts_are_bounded_and_seed_timeout_is_isolated(monkeypatch):
    import drop_alerts.sources.carton_peleon as module
    http = http_for(("1",))
    http.pages[SEED_URL] = TimeoutError()
    original = module.asyncio.wait_for
    timeouts = []
    async def bounded(awaitable, timeout):
        timeouts.append(timeout)
        return await original(awaitable, timeout)
    monkeypatch.setattr(module.asyncio, "wait_for", bounded)
    result = await CartonPeleonSource(max_items=2, max_pages=1).fetch(http)
    assert [item.id for item in result.items] == ["variant:1001"]
    assert max(timeouts) <= 20


@pytest.mark.asyncio
async def test_zero_budget_total_failure_and_structure_change_keep_snapshots():
    for source, http in [(CartonPeleonSource(max_duration_seconds=0), FakeHTTP({})),
                         (CartonPeleonSource(), FakeHTTP({})),
                         (CartonPeleonSource(max_items=1), FakeHTTP({SEED_URL: '<html><main>Layout changed</main></html>'}))]:
        with pytest.raises(ExtractionError):
            await source.fetch(http)
