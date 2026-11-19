"""Reduced real Animefan documents and simulated source changes, no network."""
import json
from pathlib import Path

from bs4 import BeautifulSoup
import pytest

from drop_alerts.config import Settings
from drop_alerts.detection import DetectionEngine
from drop_alerts.models import ExtractionError, Item
from drop_alerts.rules import RuleEngine
from drop_alerts.sources.animefan import AnimefanSource, CARD_CATALOGUES, ORIGIN, SHOP
from drop_alerts.storage import Store

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name):
    return (FIXTURES / ("animefan_" + name + ".html")).read_text(encoding="utf-8")


def candidate(name):
    soup = BeautifulSoup(fixture(name), "html.parser")
    data = json.loads(soup.find("script", type="application/ld+json").get_text())["@graph"][0]
    root = soup.select_one("div.product.type-product")
    identity = next(value.removeprefix("post-") for value in root["class"] if value.startswith("post-"))
    return Item("product:" + identity, "animefan", data["name"], data["offers"]["url"], kind="product")


def alter(name="tcg2", *, code=None, stock=None, price=None, labels=None):
    soup = BeautifulSoup(fixture(name), "html.parser")
    script = soup.find("script", type="application/ld+json")
    data = json.loads(script.get_text())
    main = data["@graph"][0]
    if code is not None:
        main["offers"]["availability"] = code
    if price is not None:
        main["offers"]["price"] = price
    if stock is not None:
        soup.select_one(".elementor-widget-woocommerce-product-add-to-cart .stock").string = stock
    if labels is not None:
        root = soup.select_one("div.product.type-product")
        root["class"] = [value for value in root["class"] if not value.startswith(("product_cat-", "product_tag-"))] + ["product_cat-" + value for value in labels]
    script.string = json.dumps(data)
    return str(soup)


def test_real_card_catalogues_are_tcg_scoped_and_keep_paging_and_woo_ids():
    source = AnimefanSource()
    pokemon, next_page, complete = source.parse_listing(fixture("pokemon_listing"), CARD_CATALOGUES[0])
    assert complete and len(pokemon) == 6 and all(row.id.startswith("product:") for row in pokemon)
    assert "album" in pokemon[0].title.casefold()
    assert next_page == CARD_CATALOGUES[0] + "page/2/"
    magic, _, _ = source.parse_listing(fixture("cards_listing"), CARD_CATALOGUES[1])
    assert any("Magic" in item.title for item in magic)
    figures, _, valid = source.parse_listing(fixture("shop"), SHOP)
    assert valid and figures == []


@pytest.mark.parametrize("name,state,game,price", [("tcg2", "UNAVAILABLE", "pokemon", "43.96"),
    ("magic", "UPCOMING", "magic", "152.05"), ("album_real", "AVAILABLE", "pokemon", "94.09")])
def test_real_tcg_details_keep_own_price_stock_and_game(name, state, game, price):
    current = AnimefanSource().parse_detail(fixture(name), candidate(name))
    assert current.state == state and current.data["tcg"] == game
    assert current.data["domain"] == "tcg" and current.data["price"] == price
    assert current.data["currency"] == "EUR" and current.data["price_verified"]
    assert current.data["image_verified"] and current.data["image_url"].startswith(ORIGIN + "/wp-content/uploads/")


def test_album_is_card_accessory_and_card_with_figure_is_still_card_product():
    current = AnimefanSource().parse_detail(fixture("album_real"), candidate("album_real"))
    assert current.data["product_category"] == "card_accessory"
    body = fixture("tcg2").replace("Blister Cartas 30th Aniversario Pokemon Eevee Español", "Blister Cartas + figura Mewtwo Pokemon Español")
    current = AnimefanSource().parse_detail(body, candidate("tcg2"))
    assert current.data["domain"] == "tcg" and current.data["tcg"] == "pokemon"


def test_poker_or_playing_cards_with_anime_name_are_not_a_tcg():
    soup = BeautifulSoup(alter(labels=["cartas"]), "html.parser")
    title = "Yu-Gi-Oh! Playing Cards Display (12)"
    soup.select_one("h1.product_title").string = title
    data = json.loads(soup.script.get_text()); data["@graph"][0]["name"] = title
    soup.script.string = json.dumps(data)
    body = str(soup)
    assert AnimefanSource().parse_detail(body, candidate("tcg2")) is None
    item = AnimefanSource(include_collectibles=True).parse_detail(body, candidate("tcg2"))
    assert item.data["domain"] == "collectibles" and "tcg" not in item.data


def test_generic_anime_collectible_cards_need_explicit_tcg_evidence():
    soup = BeautifulSoup(alter(labels=["cartas-coleccionables", "one-piece"]), "html.parser")
    title = "Cartas coleccionables One Piece"
    soup.select_one("h1.product_title").string = title
    data = json.loads(soup.script.get_text());data["@graph"][0]["name"] = title;soup.script.string = json.dumps(data)
    assert AnimefanSource().parse_detail(str(soup),candidate("tcg2")) is None
    current=AnimefanSource(include_collectibles=True).parse_detail(str(soup),candidate("tcg2"))
    assert current.data["domain"]=="collectibles" and "tcg" not in current.data


@pytest.mark.parametrize("name,state,price", [("stock", "UPCOMING", "199.00"),
    ("backorder", "UNKNOWN", "79.00"), ("sale", "UPCOMING", "257.56")])
def test_collectibles_require_opt_in_and_never_claim_tcg_from_franchise(name, state, price):
    assert AnimefanSource().parse_detail(fixture(name), candidate(name)) is None
    item = AnimefanSource(include_collectibles=True).parse_detail(fixture(name), candidate(name))
    assert item.state == state and item.data["price"] == price
    assert item.data["domain"] == "collectibles" and "tcg" not in item.data
    if name == "backorder":
        assert item.data["franchise"] == "Dragon Ball" and not item.data["availability_verified"]


@pytest.mark.parametrize("wording", ["Disponible para reserva", "Disponible próximamente", "Preventa"])
def test_explicit_reservation_stock_is_upcoming_even_if_metadata_instock(wording):
    body = alter(code="http://schema.org/InStock", stock=wording)
    assert AnimefanSource().parse_detail(body, candidate("tcg2")).state == "UPCOMING"


@pytest.mark.parametrize("wording", ["No disponible", "Sin existencias", "No hay existencias", "No disponibles"])
def test_negative_stock_never_becomes_available(wording):
    body = alter(code="http://schema.org/InStock", stock=wording)
    with pytest.raises(ExtractionError):
        AnimefanSource().parse_detail(body, candidate("tcg2"))


def test_full_price_is_not_the_optional_50_percent_deposit():
    item = AnimefanSource(include_collectibles=True).parse_detail(fixture("stock"), candidate("stock"))
    assert item.data["price"] == "199.00" and item.data["deposit_option"]
    soup = BeautifulSoup(fixture("stock"), "html.parser")
    soup.select_one(".pay-full input").attrs.pop("checked")
    soup.select_one(".pay-deposit input")["checked"] = "checked"
    item = AnimefanSource(include_collectibles=True).parse_detail(str(soup), candidate("stock"))
    assert not item.data["price_verified"] and "price" not in item.data
    soup.select_one(".pay-full").decompose()
    item = AnimefanSource(include_collectibles=True).parse_detail(str(soup), candidate("stock"))
    assert "price" not in item.data


def test_deposit_plan_alone_does_not_establish_preorder():
    body = alter("stock", labels=["figuras", "pvc"], stock="Hay existencias")
    assert AnimefanSource(include_collectibles=True).parse_detail(body, candidate("stock")).state == "AVAILABLE"


def test_principal_stock_never_comes_from_nested_recommendations():
    body = fixture("tcg2")  # Includes real nested Elementor recommendation roots.
    assert AnimefanSource().parse_detail(body, candidate("tcg2")).state == "UNAVAILABLE"
    embedded = BeautifulSoup(body, "html.parser")
    embedded.select("div.product.type-product")[1].append(BeautifulSoup('<form class="variations_form"></form>', "html.parser"))
    assert AnimefanSource().parse_detail(str(embedded), candidate("tcg2")).state == "UNAVAILABLE"
    soup = BeautifulSoup(body, "html.parser")
    main = soup.select_one("div.product.type-product")
    widget = main.select_one(".elementor-widget-woocommerce-product-add-to-cart")
    widget.decompose()
    related = main.select("div.product.type-product")[0]
    related.append(BeautifulSoup('<div class="elementor-widget-woocommerce-product-add-to-cart"><p class="stock">Hay existencias</p></div>', "html.parser"))
    with pytest.raises(ExtractionError):
        AnimefanSource().parse_detail(str(soup), candidate("tcg2"))


@pytest.mark.parametrize("body", ["<html><h1>Not found</h1></html>", "<html><title>Access denied</title></html>", "<html><h1>Shop</h1><ul class='products'><li class='product type-product'>Broken</li></ul></html>"])
def test_changed_or_blocked_structure_is_an_error_not_empty_catalogue(body):
    with pytest.raises(ExtractionError):
        AnimefanSource().parse_listing(body, CARD_CATALOGUES[0])


@pytest.mark.parametrize("code", [None, {}, "http://evil.test/InStock", "https://schema.org/Unexpected"])
def test_missing_malformed_or_unknown_schema_stock_fails_closed(code):
    soup = BeautifulSoup(fixture("tcg2"), "html.parser")
    data = json.loads(soup.script.get_text());data["@graph"][0]["offers"]["availability"] = code;soup.script.string = json.dumps(data)
    with pytest.raises(ExtractionError):
        AnimefanSource().parse_detail(str(soup), candidate("tcg2"))


def test_price_mismatch_unapproved_image_and_unverified_variable_product():
    with pytest.raises(ExtractionError):
        AnimefanSource().parse_detail(alter(price="21.98"), candidate("tcg2"))
    body = fixture("tcg2").replace(ORIGIN + "/wp-content/uploads/", "https://evil.test/")
    assert "image_url" not in AnimefanSource().parse_detail(body, candidate("tcg2")).data
    with pytest.raises(ExtractionError):
        AnimefanSource().parse_detail(fixture("tcg2").replace("product-type-simple", "product-type-variable"), candidate("tcg2"))


def test_foreign_or_action_urls_do_not_enter_catalogue():
    body = fixture("pokemon_listing").replace(ORIGIN + "/tienda/", "https://evil.test/tienda/")
    with pytest.raises(ExtractionError):
        AnimefanSource().parse_listing(body, CARD_CATALOGUES[0])
    body = fixture("pokemon_listing").replace(ORIGIN + "/tienda/", ORIGIN + "/?add-to-cart=1&path=")
    with pytest.raises(ExtractionError):
        AnimefanSource().parse_listing(body, CARD_CATALOGUES[0])


def sample(identity="1", title="Pokemon JCC producto", available=False):
    original = candidate("tcg2")
    url = ORIGIN + "/tienda/coleccion/pokemon/test-" + identity + "/"
    body = fixture("tcg2").replace("post-243604", "post-" + identity).replace(original.url, url).replace("Blister Cartas 30th Aniversario Pokemon Eevee Español", title)
    if available:
        body = body.replace("http://schema.org/OutOfStock", "http://schema.org/InStock").replace("Sin existencias", "Hay existencias")
    return url, body


def listing(entries, next_page=None):
    cards = ''.join(f'<li class="product type-product post-{identity} product_cat-pokemon-juego-de-cartas"><a class="woocommerce-LoopProduct-link" href="{url}"><h2 class="woocommerce-loop-product__title">{title}</h2></a></li>' for identity,url,title in entries)
    return '<html><h1>Pokemon juego de cartas</h1><ul class="products">'+cards+'</ul>'+ (f'<nav class="woocommerce-pagination"><a class="next" href="{next_page}">Next</a></nav>' if next_page else '')+'</html>'


class FakeHTTP:
    def __init__(self, pages, store=None):
        self.pages, self.store, self.calls = pages, store, []
    async def get(self, url):
        self.calls.append(url)
        value = self.pages.get(url, ExtractionError("HTTP 404"))
        if isinstance(value, Exception):
            raise value
        return value


def pages(entries):
    result = {base: listing(entries) for base in CARD_CATALOGUES}
    for identity,url,title in entries:
        result[url] = sample(identity, title)[1]
    return result


def ingest(store, result, config):
    return store.ingest("animefan", result, DetectionEngine(), RuleEngine(config.rules), config)


@pytest.mark.asyncio
async def test_deferred_initial_inventory_and_new_product_survive_restart_without_duplicates(tmp_path):
    config = Settings(llm_enabled=False, rules=[{"id":"all"}])
    path = str(tmp_path / "animefan.db")
    entries = [(str(i),sample(str(i))[0],"Pokemon JCC producto "+str(i)) for i in range(1,5)]
    store = Store(path)
    for _ in range(2):
        result = await AnimefanSource(max_items=1,max_pages=1).fetch(FakeHTTP(pages(entries),store))
        ingest(store,result,config)
        store.close();store = Store(path)
    assert not store.due_notifications(10)
    new = ("5",sample("5")[0],"Pokemon JCC nuevo producto")
    for _ in range(8):
        result = await AnimefanSource(max_items=2,max_pages=1).fetch(FakeHTTP(pages(entries+[new]),store))
        ingest(store,result,config)
    deliveries = store.due_notifications(100)
    assert len(deliveries)==1 and deliveries[0][0].item_id=="product:5"
    store.close()


@pytest.mark.asyncio
async def test_restock_of_known_product_outside_listing_and_partial_error_preserve_previous():
    config = Settings(llm_enabled=False,rules=[{"id":"all"}]);store=Store(":memory:")
    entry=("1",sample()[0],"Pokemon JCC producto")
    http=FakeHTTP(pages([entry]),store)
    ingest(store,await AnimefanSource(max_pages=1).fetch(http),config)
    http.pages.update({base:listing([]) for base in CARD_CATALOGUES});http.pages[entry[1]]=sample(available=True)[1]
    ingest(store,await AnimefanSource(max_pages=1).fetch(http),config)
    pending=store.due_notifications(100)
    assert len(pending)==1 and pending[0][0].event_type=="availability.changed"
    previous=store.item("animefan","product:1")[0].digest
    http.pages[entry[1]]=ExtractionError("HTTP404")
    with pytest.raises(ExtractionError):
        await AnimefanSource(max_pages=1).fetch(http)
    assert store.item("animefan","product:1")[0].digest==previous
    store.close()


@pytest.mark.asyncio
async def test_a_slow_new_detail_does_not_block_other_products(monkeypatch):
    import drop_alerts.sources.animefan as module
    entries=[(str(i),sample(str(i))[0],"Pokemon JCC producto "+str(i)) for i in (1,2)]
    http=FakeHTTP(pages(entries));real=module.asyncio.wait_for;timeouts=[]
    async def bounded(awaitable,timeout):
        timeouts.append(timeout)
        return await real(awaitable,timeout)
    monkeypatch.setattr(module.asyncio,"wait_for",bounded)
    http.pages[entries[0][1]]=TimeoutError()
    result=await AnimefanSource(max_items=2,max_pages=1).fetch(http)
    assert [item.id for item in result.items]==["product:2"]
    assert result.metadata["errors"]==["detail:unavailable"] and max(timeouts)<=20


@pytest.mark.asyncio
async def test_failed_catalogues_and_zero_budget_do_not_initialize_empty_source():
    with pytest.raises(ExtractionError):
        await AnimefanSource().fetch(FakeHTTP({}))
    with pytest.raises(ExtractionError):
        await AnimefanSource(max_duration_seconds=0).fetch(FakeHTTP({}))


@pytest.mark.asyncio
async def test_collectible_frontpage_resolves_deferred_urls_to_silent_woo_id(tmp_path):
    config=Settings(llm_enabled=False,rules=[{"id":"all"}])
    config.sources['animefan']['include_collectibles']=True
    path=str(tmp_path/"front.db");store=Store(path)
    names=["stock","backorder"]
    def frontpage(values):
        return '<html><h1>Inicio</h1><div class="elementor-widget-heading">'+''.join('<p class="elementor-heading-title"><a href="'+candidate(name).url+'">'+candidate(name).title+'</a></p>' for name in values)+'</div></html>'
    responses={ORIGIN+'/':frontpage(names),SHOP:listing([]),**{base:listing([]) for base in CARD_CATALOGUES},**{candidate(name).url:fixture(name) for name in names}}
    first=await AnimefanSource(max_items=1,max_pages=1,include_collectibles=True).fetch(FakeHTTP(responses,store))
    assert first.items[0].id==candidate("stock").id
    ingest(store,first,config);store.close();store=Store(path)
    second=await AnimefanSource(max_items=1,max_pages=1,include_collectibles=True).fetch(FakeHTTP(responses,store))
    assert second.items[0].id==candidate("backorder").id
    ingest(store,second,config)
    assert not store.due_notifications(10)
    assert 'initial-frontpage:'+candidate("backorder").url in second.metadata["discovery_inventories"]
    responses[ORIGIN+'/']=frontpage(names+["sale"]);responses[candidate("sale").url]=fixture("sale")
    for _ in range(4):
        result=await AnimefanSource(max_items=1,max_pages=1,include_collectibles=True).fetch(FakeHTTP(responses,store))
        ingest(store,result,config)
    pending=store.due_notifications(10)
    assert len(pending)==1 and pending[0][0].item_id==candidate("sale").id
    store.close()
