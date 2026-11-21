"""El Cartón Peleón: verified Odoo HTML, without cart or account requests."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import json
import re
import time
from urllib.parse import quote, unquote, urljoin, urlsplit, urlunsplit

from ..models import ExtractionError, FetchResult, Item
from ..profiles import normalized_name
from .common import jsonld, soup_from, text

ORIGIN = "https://www.elcartonpeleon.com"
SEED_URL = ORIGIN + "/shop/commander-pack-4-mazos-ingles-magic-the-gathering-warhammer-40k-deck-set-19822"
CATALOGUES = tuple(ORIGIN + "/shop/category/" + name + "?order=publish_date+desc"
                   for name in ("juegos-de-cartas-204", "accesorios-160"))
REQUEST_TIMEOUT_SECONDS = 20
STOCK_URL = ORIGIN + "/website_sale/get_combination_info"
GAME_CATEGORIES = {"113": "magic", "124": "one_piece", "139": "pokemon", "166": "riftbound",
                   "119": "lorcana", "144": "digimon", "129": "star_wars_unlimited", "149": "yugioh",
                   "192": "cyberpunk", "179": "dragon_ball", "191": "palworld", "201": "universus",
                   "206": "weiss_schwarz"}


def _url(value, *, product=False, catalogue=False):
    if not isinstance(value, str) or not value or any(char.isspace() for char in value):
        return None
    try:
        parts = urlsplit(urljoin(ORIGIN + "/", value))
        if parts.scheme != "https" or parts.netloc != "www.elcartonpeleon.com" or parts.username or parts.password or parts.fragment:
            return None
        path = unquote(parts.path)
        if product:
            if parts.query or not re.fullmatch(r"/shop/(?:[\w-]+-\d+/)?[\w-]+-[1-9][0-9]*", path):
                return None
            path = "/shop/" + path.rsplit("/", 1)[-1]
        elif catalogue:
            if parts.query not in ("", "order=publish_date+desc") or not any(
                    re.fullmatch(re.escape(urlsplit(base).path) + r"(?:/page/[1-9][0-9]{0,3})?", path) for base in CATALOGUES):
                return None
        elif parts.query:
            return None
        return urlunsplit((parts.scheme, parts.netloc, quote(path, safe="/-_"), parts.query, ""))
    except ValueError:
        return None


def _relevant(title, categories):
    value = normalized_name(title).replace("_", " ")
    if re.search(r"\b(?:entradas?|torneos?|inscripcion|eventos?|rifas?|ruletas?|gift card|tarjetas? regalo|poker|naipes?|tarot)\b", value):
        return False
    if re.search(r"\b(?:figuras?|figures?|figurines?|miniaturas?|resina|estatuas?|peluches?|juego de mesa)\b", value) and not re.search(r"\b(?:sobres?|booster|deck|mazos?)\b", value):
        return False
    if "204" in categories:
        return True
    return "160" in categories and bool(re.search(
        r"\b(?:fundas?|sleeves?|tapetes?|playmats?|deck|deckbox|mazos?|portamazos?|archivadores?|binders?|albums?|albumes|carpetas?|toploaders?|cartas?|card|sobres?|boosters?|divisores?|separadores?)\b", value))


def _game(title, categories):
    games = {GAME_CATEGORIES[value] for value in categories if value in GAME_CATEGORIES}
    if len(games) == 1:
        return games.pop()
    if games:
        return None
    value = normalized_name(title).replace("_", " ").replace("ß", "ss")
    patterns = {"magic": r"\bmagic(?: the gathering)?\b|\bmtg\b", "one_piece": r"\bone piece\b",
                "pokemon": r"\bpokemon\b", "riftbound": r"\briftbound\b", "lorcana": r"\blorcana\b",
                "digimon": r"\bdigimon\b", "yugioh": r"\byu gi oh\b|\byugioh\b",
                "dragon_ball": r"\bdragon ball\b", "star_wars_unlimited": r"\bstar wars unlimited\b",
                "cyberpunk": r"\bcyberpunk\b", "palworld": r"\bpalworld\b", "universus": r"\buniversus\b",
                "weiss_schwarz": r"\bweiss schwarz\b"}
    found = [game for game, pattern in patterns.items() if re.search(pattern, value)]
    return found[0] if len(found) == 1 else None


def _hidden(node, boundary=None):
    while node is not None:
        if node.has_attr("hidden") or set(node.get("class", [])).intersection({"d-none", "css_non_editable_mode_hidden"}) or re.search(r"(?:display\s*:\s*none|visibility\s*:\s*hidden)", node.get("style", ""), re.I):
            return True
        if node is boundary:
            break
        node = node.parent
    return False


def _money(value):
    if isinstance(value, bool):
        return None
    try:
        amount = Decimal(str(value))
        if amount.is_finite() and 0 < amount <= 1_000_000_000 and amount.as_tuple().exponent >= -4:
            return amount.quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError, TypeError):
        pass
    return None


def _price(main):
    prices = main.select('.product_price[name="product_price"]')
    if len(prices) != 1 or _hidden(prices[0], main):
        return None
    price = prices[0]
    wording = normalized_name(price.get_text(" ", strip=True)).replace("_", " ")
    if re.search(r"\b(?:desde|senal|deposito|a partir|pago parcial)\b", wording):
        return None
    values = [node for node in price.select('[name="product_price_container"] .oe_price .oe_currency_value') if not _hidden(node, main)]
    if len(values) != 1 or "€" not in values[0].parent.get_text():
        return None
    value = values[0].get_text(strip=True)
    if not re.fullmatch(r"\d{1,3}(?:\.\d{3})*,\d{2}|\d+,\d{2}", value):
        return None
    return _money(value.replace(".", "").replace(",", "."))


def _identities(node, name, attribute):
    values = {str(element.get("value", "")) for element in node.select('input[name="' + name + '"]')}
    values.update(str(element.get(attribute, "")) for element in node.select(".o_add_wishlist[" + attribute + "]"))
    if name == "product_id":
        values.update(str(element.get("data-pid", "")) for element in node.select(".cp-card-int[data-pid]"))
    return values


def _work(candidates, known, limit, cursor, priority_first):
    priority = [item for item in candidates if item.id not in known][:limit // 2]
    selected = {item.id for item in priority}
    rotating = []
    for step, item in enumerate(candidates[cursor:] + candidates[:cursor], 1):
        if len(rotating) + len(priority) >= limit:
            break
        if item.id not in selected:
            rotating.append((item, (cursor + step) % max(1, len(candidates))))
    result = []
    for index in range(max(len(priority), len(rotating))):
        pair = ([(priority[index], None)] if index < len(priority) else []) + ([rotating[index]] if index < len(rotating) else [])
        result.extend(pair if priority_first else reversed(pair))
    return result


@dataclass
class CartonPeleonSource:
    id: str = "carton_peleon"
    url: str = ORIGIN + "/"
    max_items: int = 12
    max_pages: int = 2
    max_duration_seconds: float = 90

    def parse_listing(self, body: str, catalogue: str):
        soup = soup_from(body)
        grid = soup.select_one("#o_wsale_products_grid")
        if grid is None or not _url(catalogue, catalogue=True):
            raise ExtractionError("El Cartón Peleón: catálogo no reconocido")
        category = "204" if "/juegos-de-cartas-204" in catalogue else "160"
        found, complete = {}, True
        cards = grid.select("form.oe_product_cart")
        if not cards:
            raise ExtractionError("El Cartón Peleón: catálogo vacío o incompleto")
        for card in cards:
            anchor = card.select_one("h2.o_wsale_products_item_title a[href]")
            title = text(anchor.get_text(" ", strip=True)) if anchor else ""
            if title and not _relevant(title, [category]):
                continue
            url = _url(anchor.get("href"), product=True) if anchor else None
            templates = _identities(card, "product_template_id", "data-product-template-id")
            variants = _identities(card, "product_id", "data-product-product-id")
            if not title or not url or len(templates) != 1 or len(variants) != 1 or not all(re.fullmatch(r"[1-9][0-9]*", value) for value in templates | variants) or url.rsplit("-", 1)[-1] not in templates:
                complete = False
                continue
            identity = "variant:" + next(iter(variants))
            if identity in found and found[identity].url != url:
                raise ExtractionError("El Cartón Peleón: identidad de catálogo ambigua")
            found[identity] = Item(identity, self.id, title, url, kind="product", data={"template_id": next(iter(templates))})
        next_url = next((url for marker in soup.select("ul.pagination .oi-chevron-right")
                         if marker.parent.name == "a" and (url := _url(marker.parent.get("href"), catalogue=True))
                         and urlsplit(url).path.startswith(urlsplit(catalogue).path.split("/page/")[0] + "/page/")), None)
        if not complete and not found:
            raise ExtractionError("El Cartón Peleón: tarjetas incompletas")
        return list(found.values()), next_url, complete

    def parse_detail(self, body: str, candidate: Item):
        soup = soup_from(body)
        roots = soup.select("section#product_detail")
        if len(roots) != 1 or _url(candidate.url, product=True) != candidate.url:
            raise ExtractionError("El Cartón Peleón: ficha no reconocida")
        root = roots[0]
        mains = root.select("#product_details #o_wsale_product_details_content.js_product.js_main_product")
        if len(mains) != 1:
            raise ExtractionError("El Cartón Peleón: producto principal ambiguo")
        main = mains[0]
        headings = main.select(".o_wsale_product_details_content_section_title h1")
        templates = _identities(main, "product_template_id", "data-product-template-id")
        variants = _identities(main, "product_id", "data-product-product-id")
        if len(headings) != 1 or len(templates) != 1 or len(variants) != 1 or not all(re.fullmatch(r"[1-9][0-9]*", value) for value in templates | variants):
            raise ExtractionError("El Cartón Peleón: identidad incompleta")
        template, variant = next(iter(templates)), next(iter(variants))
        if template != candidate.url.rsplit("-", 1)[-1] or candidate.id.startswith("variant:") and candidate.id != "variant:" + variant:
            raise ExtractionError("El Cartón Peleón: identidad de variante distinta")
        selectors = main.select(".js_add_cart_variants")
        if len(selectors) != 1 or selectors[0].select("li, select, input, option"):
            raise ExtractionError("El Cartón Peleón: variantes no verificables")
        try:
            exclusions = json.loads(selectors[0].get("data-attribute-exclusions", ""))
        except (ValueError, TypeError):
            raise ExtractionError("El Cartón Peleón: variantes incompletas") from None
        variant_fields = {"mapped_attribute_names": dict, "exclusions": dict, "archived_combinations": list,
                          "parent_exclusions": dict, "parent_combination": list}
        if not isinstance(exclusions, dict) or any(type(exclusions.get(key)) is not kind or exclusions[key]
                                                  for key, kind in variant_fields.items()):
            raise ExtractionError("El Cartón Peleón: variantes múltiples no soportadas")
        title = text(headings[0].get_text(" ", strip=True))
        categories = {match.group(1) for anchor in root.select(".o_wsale_breadcrumb a[href]")
                      if (match := re.fullmatch(r"/shop/category/[\w-]+-([1-9][0-9]*)", unquote(urlsplit(urljoin(ORIGIN, anchor["href"])).path)))
                      and urlsplit(urljoin(ORIGIN, anchor["href"])).netloc == "www.elcartonpeleon.com"}
        if not _relevant(title, categories):
            return None
        products = [row for row in jsonld(soup) if row.get("@type") == "Product" and _url(row.get("url"), product=True) == candidate.url]
        if len(products) != 1 or normalized_name(text(products[0].get("name", ""))) != normalized_name(title):
            raise ExtractionError("El Cartón Peleón: metadatos de otro producto")
        info = products[0]
        offer = info.get("offers")
        if not isinstance(offer, dict) or offer.get("@type") != "Offer" or offer.get("url") is not None and _url(offer["url"], product=True) != candidate.url:
            raise ExtractionError("El Cartón Peleón: oferta individual no verificable")
        code = re.fullmatch(r"https?://schema\.org/(InStock|OutOfStock|SoldOut|PreOrder|BackOrder)", str(offer.get("availability", "")))
        if code is None:
            raise ExtractionError("El Cartón Peleón: disponibilidad estructurada desconocida")
        code = code.group(1)
        notices = [node for node in main.select(".cp-dispo") if not _hidden(node, main)]
        if any(node.get("data-pid") != variant for node in notices) or len(notices) > 1:
            raise ExtractionError("El Cartón Peleón: aviso de otra variante")
        notice = notices[0] if notices else None
        heading = notice.select_one(".cp-t") if notice else None
        stock = text(heading.get_text(" ", strip=True)) if heading else ""
        wording = normalized_name(stock).replace("_", " ")
        preorder = any(not _hidden(node, main) for node in main.select(".ecp-chip--reserva-card"))
        if notice and "cp-dispo-agot" in notice.get("class", []) and re.search(r"\bagotado online\b", wording):
            if code not in ("OutOfStock", "SoldOut"):
                raise ExtractionError("El Cartón Peleón: stock agotado contradictorio")
            state = "UNAVAILABLE"
        elif notice and "cp-dispo-prox" in notice.get("class", []) and re.search(r"\bproximamente\b", wording):
            state = "UPCOMING"
        elif notice:
            raise ExtractionError("El Cartón Peleón: aviso de disponibilidad desconocido")
        elif preorder and code in ("InStock", "PreOrder"):
            state, stock = "UPCOMING", "Reserva publicada"
        else:
            positive = [text(node.get_text(" ", strip=True)) for node in main.select(".ecp-stock-aviso")
                        if not _hidden(node, main) and "ecp-stock-aviso--tienda" not in node.get("class", [])]
            positive = [value for value in positive if re.fullmatch(r"Solo quedan [1-9][0-9]* unidades", value, re.I)]
            state = "AVAILABLE" if len(positive) == 1 and code == "InStock" else "UNKNOWN"
            stock = positive[0] if state == "AVAILABLE" else "No hay evidencia pública suficiente de stock online."
        visible, amount = _price(main), _money(offer.get("price")) if offer.get("priceCurrency") == "EUR" else None
        if visible is not None and amount is not None and visible != amount:
            raise ExtractionError("El Cartón Peleón: precio contradictorio")
        notes = {"UPCOMING": "Reserva o lanzamiento próximo anunciado; no acredita existencias para entrega inmediata.",
                 "UNAVAILABLE": "Agotado online; las unidades indicadas solo en tienda no son stock para compra web.",
                 "AVAILABLE": "La ficha indica unidades disponibles online.",
                 "UNKNOWN": "Producto publicado; disponibilidad online sin confirmar mediante HTML estático."}
        data = {"region": "EU", "country": "ES", "language": "es", "channel": "online", "provenance": "retailer",
                "retailer": "El Cartón Peleón", "domain": "tcg", "product_id": variant, "template_id": template,
                "identity_verified": True, "availability_verified": state != "UNKNOWN", "availability_evidence": stock,
                "preorder": state == "UPCOMING", "summary": notes[state], "price_verified": False}
        if visible is not None and amount is not None:
            data.update(price=format(amount, ".2f"), currency="EUR", price_verified=True)
        game = _game(title, categories)
        if game:
            data["tcg"] = game
        sku = info.get("sku")
        if isinstance(sku, (str, int)) and not isinstance(sku, bool) and str(sku).strip():
            data["sku"] = str(sku)[:120]
        image = info.get("image")
        image = image[0] if isinstance(image, list) and image else image
        if isinstance(image, str):
            parts = urlsplit(urljoin(ORIGIN, image))
            if parts.scheme == "https" and parts.netloc == "www.elcartonpeleon.com" and re.fullmatch(r"/web/image/product\.product/" + variant + r"/image_(?:1024|1920)", parts.path) and re.fullmatch(r"(?:unique=[a-zA-Z0-9]+)?", parts.query) and not parts.fragment:
                data.update(image_url=urlunsplit(parts), image_verified=True)
        section = main.select_one(".o_wsale_product_details_content_section_title")
        description = section.select_one(".oe_structure")
        description = text(description.get_text(" ", strip=True))[:6000] if description else ""
        release = section.select_one(".ecp-ficha-fecha")
        special = section.select_one(".ecp-aviso-especial__texto")
        release = text(release.get_text(" ", strip=True)) if release else ""
        special = text(special.get_text(" ", strip=True)) if special else ""
        if "fecha por determinar" in normalized_name(special).replace("_", " "):
            release = "Fecha por determinar; la estimación mostrada por la tienda no está confirmada."
        return Item("variant:" + variant, self.id, title, candidate.url, kind="product", state=state,
                    data=data, content="\n".join((title, description, stock, release, special)))

    def stock_request(self, item):
        return {"jsonrpc": "2.0", "method": "call", "id": 1, "params": {
            "product_template_id": int(item.data["template_id"]), "product_id": int(item.data["product_id"]),
            "combination": [], "add_qty": 1, "uom_id": None, "context": {}}}

    def parse_stock(self, payload, item):
        """Only the public product-combination read RPC; never cart mutation or API prices."""
        if not isinstance(payload, dict) or payload.get("jsonrpc") != "2.0" or payload.get("error") is not None or not isinstance(payload.get("result"), dict):
            raise ExtractionError("El Cartón Peleón: respuesta de stock inválida")
        result = payload["result"]
        for key, expected in (("product_id", item.data["product_id"]), ("product_template_id", item.data["template_id"])):
            if type(result.get(key)) is not int or result[key] != int(expected):
                raise ExtractionError("El Cartón Peleón: stock de otra variante")
        if result.get("is_combination_possible") is not True or normalized_name(str(result.get("display_name", ""))) != normalized_name(item.title):
            raise ExtractionError("El Cartón Peleón: combinación de stock no verificable")
        if any(type(result.get(key)) is not bool for key in ("is_storable", "allow_out_of_stock_order", "prevent_zero_price_sale")):
            raise ExtractionError("El Cartón Peleón: indicadores de stock incompletos")
        quantities = {}
        for key in ("free_qty", "cart_qty", "max_combo_quantity"):
            if key not in result and key == "max_combo_quantity":
                continue
            value = result.get(key)
            if type(value) not in (int, float) or not Decimal(str(value)).is_finite() or not 0 <= value <= 1_000_000_000:
                raise ExtractionError("El Cartón Peleón: cantidad de stock inválida")
            quantities[key] = value
        quantity = min(quantities["free_qty"] - quantities["cart_qty"], quantities.get("max_combo_quantity", quantities["free_qty"]))
        if result["prevent_zero_price_sale"]:
            state, summary = "UNKNOWN", "La tienda bloquea la venta online de esta combinación; condiciones de venta sin confirmar."
        elif not result["is_storable"]:
            state, summary = "UNKNOWN", "La tienda no ofrece una cantidad de stock verificable para este producto."
        elif quantity >= 1:
            state, summary = "AVAILABLE", "Existencias online verificadas por la consulta pública de la ficha de producto."
        elif not result["allow_out_of_stock_order"]:
            state, summary = "UNAVAILABLE", "Sin unidades online para comprar según la consulta pública de la ficha."
        else:
            state, summary = "UNKNOWN", "Compra bajo pedido permitida sin existencias online; entrega y reposición sin confirmar."
        old_evidence = item.data["availability_evidence"]
        item.state = state
        item.data.update(availability_verified=state != "UNKNOWN", availability_evidence=summary,
                         availability_method="public_product_combination_rpc", summary=summary)
        item.content = item.content.replace(old_evidence, summary)
        return item

    async def fetch(self, http):
        store = getattr(http, "store", None)
        local = getattr(self, "_metadata", {})

        def read(key, default):
            raw = store.get_meta("carton_peleon:" + key) if store and hasattr(store, "get_meta") else local.get(key)
            try:
                return json.loads(raw) if isinstance(raw, str) else default if raw is None else raw
            except (ValueError, TypeError):
                return default

        def save(key, value):
            if store and hasattr(store, "set_meta"):
                store.set_meta("carton_peleon:" + key, json.dumps(value))
            else:
                local[key] = value

        deadline = time.monotonic() + self.max_duration_seconds

        async def request(url, payload=None):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError
            try:
                call = http.get(url) if payload is None else http.post_json(url, payload)
                return await asyncio.wait_for(call, min(REQUEST_TIMEOUT_SECONDS, remaining))
            except TimeoutError:
                if time.monotonic() >= deadline:
                    raise
                raise ExtractionError("El Cartón Peleón: petición agotada") from None

        async def detail(candidate):
            item = self.parse_detail(await request(candidate.url), candidate)
            if item is not None and (item.state == "UNKNOWN" or item.state == "AVAILABLE" and not item.data["price_verified"]):
                item = self.parse_stock(await request(STOCK_URL, self.stock_request(item)), item)
            return item

        accepted, inventories, errors = [], {}, []
        try:
            seed = await detail(Item("url:" + SEED_URL, self.id, "Producto vigilado", SEED_URL, kind="product"))
            if seed is not None:
                accepted.append(seed)
                inventories["seed:commander-warhammer"] = [seed.id]
        except (ExtractionError, TimeoutError):
            errors.append("seed:unavailable")
        found, valid_pages = {}, 0
        limit = max(1, self.max_items)
        if limit > 1:
            for base in CATALOGUES:
                page = base
                for index in range(max(1, min(5, self.max_pages))):
                    if not page:
                        break
                    try:
                        items, next_page, complete = self.parse_listing(await request(page), page)
                        valid_pages += 1
                        found.update((item.id, item) for item in items)
                        if complete:
                            inventories["catalogue:" + urlsplit(page).path] = [item.id for item in items]
                        else:
                            errors.append("catalogue:incomplete_cards")
                        key = "page:" + base
                        saved = _url(read(key, None), catalogue=True)
                        if saved and not urlsplit(saved).path.startswith(urlsplit(base).path + "/page/"):
                            saved = None
                        page = (saved or next_page) if index == 0 else next_page
                        save(key, page or base)
                    except (ExtractionError, TimeoutError):
                        errors.append("catalogue:unavailable")
                        break
        known_items = store.get_source_items(self.id) if store and hasattr(store, "get_source_items") else getattr(self, "_known", [])
        for item in known_items:
            if _url(item.url, product=True) == item.url and item.url != SEED_URL:
                found.setdefault(item.id, item)
        candidates = [item for item in found.values() if item.url != SEED_URL]
        known = {item.id for item in known_items}
        cursor = read("cursor", 0)
        cursor = (cursor if type(cursor) is int else 0) % max(1, len(candidates))
        priority_first = read("priority_first", True) is not False
        work = _work(candidates, known, limit - 1, cursor, priority_first)
        attempted = False
        for candidate, after in work:
            if time.monotonic() >= deadline:
                errors.append("details:time_budget_exhausted")
                break
            attempted = True
            if after is not None:
                cursor = after
            try:
                item = await detail(candidate)
                if item is not None:
                    accepted.append(item)
            except TimeoutError:
                errors.append("details:time_budget_exhausted")
                break
            except ExtractionError:
                errors.append("detail:unavailable")
        save("cursor", cursor)
        if attempted:
            save("priority_first", not priority_first)
        self._metadata = local
        self._known = list({item.id: item for item in known_items + accepted}.values())
        if not accepted and (errors or work or limit == 1):
            raise ExtractionError("El Cartón Peleón: ninguna ficha confirmada; se conserva el estado")
        if not accepted and not valid_pages:
            raise ExtractionError("El Cartón Peleón: ningún inventario válido")
        return FetchResult(accepted, not_modified=not accepted, metadata={
            "method": "Odoo HTML + Product/Offer JSON-LD + public product-combination stock RPC",
            "errors": errors, "bootstrap_ids": [item.id for item in found.values()], "discovery_inventories": inventories,
            "catalogue_pages": valid_pages, "pinned_product": SEED_URL, "bounded_window": True})
