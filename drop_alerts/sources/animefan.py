"""Verified Animefan WooCommerce catalogues and Elementor product facts.

Card products are the default scope; figures/merchandise are an explicit option.
No catalogue query strings, purchase actions, REST APIs or browser are used.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import json
import re
import time
from urllib.parse import urljoin, urlsplit, urlunsplit

from ..models import ExtractionError, FetchResult, Item
from ..profiles import normalized_name
from .common import jsonld, soup_from, text

ORIGIN = "https://animefan.es"
CARD_CATALOGUES = (ORIGIN + "/categoria-producto/fabricante/pokemon-juego-de-cartas/",
                   ORIGIN + "/categoria-producto/grupo-producto/cartas-coleccionables/")
SHOP = ORIGIN + "/tienda/"
REQUEST_TIMEOUT_SECONDS = 20
CARD_LABELS = {"pokemon-juego-de-cartas", "cartas-coleccionables", "carta"}
GAMES = {"pokemon": r"\bpokemon\b", "magic": r"\bmagic(?: the gathering)?\b|\bmtg\b",
         "one_piece": r"\bone piece\b", "riftbound": r"\briftbound\b", "lorcana": r"\blorcana\b",
         "yugioh": r"\byu gi oh\b|\byugioh\b", "dragon_ball": r"\bdragon ball\b",
         "digimon": r"\bdigimon\b", "star_wars_unlimited": r"\bstar wars unlimited\b"}


def _url(value, *, product=False, catalogue=False):
    if not isinstance(value, str) or not value or any(char.isspace() for char in value):
        return None
    try:
        parts = urlsplit(urljoin(ORIGIN + "/", value))
        if (parts.scheme != "https" or parts.netloc != "animefan.es" or parts.username or parts.password or parts.query):
            return None
        if product and not re.fullmatch(r"/tienda/(?:[a-z0-9][a-z0-9_-]*/){2,6}", parts.path):
            return None
        if catalogue:
            bases = (*CARD_CATALOGUES, SHOP)
            if not any(parts.path == urlsplit(base).path or re.fullmatch(re.escape(urlsplit(base).path) + r"page/[1-9][0-9]{0,3}/", parts.path) for base in bases):
                return None
        return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
    except ValueError:
        return None


def _labels(node):
    return [value.removeprefix(prefix) for value in node.get("class", [])
            for prefix in ("product_cat-", "product_tag-") if value.startswith(prefix)]


def _is_card(title, labels):
    normalized = normalized_name(title).replace("_", " ")
    if re.search(r"\bplaying cards\b|\bpoker\b|\bnaipes?\b", normalized):
        return False
    evidence = normalized_name(title + " " + " ".join(labels)).replace("_", " ")
    explicit = bool("pokemon-juego-de-cartas" in labels
                    or ("magic-the-gathering" in labels and set(labels).intersection(CARD_LABELS))
                    or re.search(r"\b(?:tcg|jcc|trading card game|card game|magic the gathering)\b", evidence))
    card_form = bool(set(labels).intersection(CARD_LABELS)
                     or re.search(r"\bcartas?\b|\bbooster\b|\bsobres?\b|\bmazos?\b|\balbum\b|\bbinder\b|\bdeck\b", normalized))
    return explicit and card_form


def _game(title, labels):
    value = normalized_name(title + " " + " ".join(labels)).replace("_", " ")
    explicit = bool(set(labels).intersection({"pokemon-juego-de-cartas", "magic-the-gathering"})
                    or re.search(r"\b(?:tcg|jcc|trading card game|card game|magic the gathering)\b", value))
    if not explicit:
        return None
    found = [game for game, pattern in GAMES.items() if re.search(pattern, value)]
    return found[0] if len(found) == 1 else None


def _money(value):
    if isinstance(value, bool):
        return None
    try:
        amount = Decimal(str(value))
        if amount.is_finite() and 0 <= amount <= 1_000_000_000 and amount.as_tuple().exponent >= -4:
            return amount.quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError, TypeError):
        pass
    return None


def _price(widget):
    price = widget.select_one("p.price") if widget else None
    if price is None:
        return None
    wording = normalized_name(price.get_text(" ", strip=True)).replace("_", " ")
    if re.search(r"\b(?:desde|partir|reserva|senal|deposito|ahora)\b", wording):
        return None
    current = price.find("ins") or price
    amounts = [node for node in current.select(".woocommerce-Price-amount") if node.find_parent("del") is None]
    if len(amounts) != 1:
        return None
    symbol = amounts[0].select_one(".woocommerce-Price-currencySymbol")
    if symbol is None or symbol.get_text(strip=True) != "€":
        return None
    value = amounts[0].get_text("", strip=True).replace("€", "").replace("\xa0", "").strip()
    if not re.fullmatch(r"\d{1,3}(?:\.\d{3})*,\d{2}|\d+,\d{2}", value):
        return None
    return _money(value.replace(".", "").replace(",", "."))


def _work(candidates, known, limit, cursor, priority_first):
    priority = [item for item in candidates if item.url not in known][:limit // 2]
    selected = {item.url for item in priority}
    rotation = []
    for step, item in enumerate(candidates[cursor:] + candidates[:cursor], 1):
        if len(rotation) + len(priority) >= limit:
            break
        if item.url not in selected:
            rotation.append((item, (cursor + step) % max(1, len(candidates))))
    result = []
    for index in range(max(len(priority), len(rotation))):
        pair = ([(priority[index], None)] if index < len(priority) else []) + ([rotation[index]] if index < len(rotation) else [])
        result.extend(pair if priority_first else reversed(pair))
    return result


@dataclass
class AnimefanSource:
    id: str = "animefan"
    url: str = ORIGIN + "/"
    max_items: int = 12
    max_pages: int = 2
    max_duration_seconds: float = 90
    include_collectibles: bool = False

    @staticmethod
    def _widget(root, selector):
        # Elementor recommendations can contain nested product templates. Their
        # price/stock/content must never substitute the principal widget.
        nodes = []
        for node in root.select(selector):
            owner = node.find_parent(lambda tag: tag.name == "div" and all(value in tag.get("class", []) for value in ("product", "type-product", "elementor-location-single")))
            if owner is root:
                nodes.append(node)
        if len(nodes) > 1:
            raise ExtractionError("Animefan: datos principales ambiguos")
        return nodes[0] if nodes else None

    def parse_listing(self, body: str, catalogue: str) -> tuple[list[Item], str | None, bool]:
        soup = soup_from(body)
        products = soup.select_one("ul.products")
        if products is None or soup.find("h1") is None or not _url(catalogue, catalogue=True):
            raise ExtractionError("Animefan: catálogo no reconocido")
        found, complete = {}, True
        for card in products.select("li.product.type-product"):
            title_node = card.select_one(".woocommerce-loop-product__title")
            title = text(title_node.get_text(" ", strip=True)) if title_node else ""
            labels = _labels(card)
            if title and not self.include_collectibles and not _is_card(title, labels):
                continue
            anchor = card.select_one("a.woocommerce-LoopProduct-link[href]")
            url = _url(anchor.get("href"), product=True) if anchor else None
            identities = [value.removeprefix("post-") for value in card.get("class", []) if re.fullmatch(r"post-[1-9][0-9]*", value)]
            if not title or not url or len(identities) != 1:
                complete = False
                continue
            found[url] = Item("product:" + identities[0], self.id, title, url, kind="product")
        next_url = None
        for anchor in soup.select(".woocommerce-pagination a.next[href]"):
            candidate = _url(anchor.get("href"), catalogue=True)
            if candidate:
                next_url = candidate
                break
        if not complete and not found:
            raise ExtractionError("Animefan: tarjetas incompletas")
        return list(found.values()), next_url, complete

    def parse_frontpage(self, body: str) -> list[Item]:
        soup = soup_from(body)
        if soup.find("h1") is None or not soup.select_one(".elementor-widget-heading"):
            raise ExtractionError("Animefan: portada no reconocida")
        found = {}
        for anchor in soup.select(".elementor-heading-title a[href]"):
            url = _url(anchor.get("href"), product=True)
            title = text(anchor.get_text(" ", strip=True))
            if url and title:
                found[url] = Item("url:" + url, self.id, title, url, kind="product")
        if not found:
            raise ExtractionError("Animefan: portada sin productos verificables")
        return list(found.values())[:200]

    def parse_detail(self, body: str, candidate: Item) -> Item | None:
        soup = soup_from(body)
        roots = [node for node in soup.select("div.product.type-product.elementor-location-single")
                 if any(re.fullmatch(r"post-[1-9][0-9]*", value) for value in node.get("class", []))
                 and (widget := self._widget(node, ".elementor-widget-woocommerce-product-title")) is not None
                 and widget.select_one("h1.product_title") is not None]
        if len(roots) != 1 or not _url(candidate.url, product=True):
            raise ExtractionError("Animefan: ficha principal no reconocida")
        root = roots[0]
        ids = [value.removeprefix("post-") for value in root.get("class", []) if re.fullmatch(r"post-[1-9][0-9]*", value)]
        if len(ids) != 1 or (candidate.id.startswith("product:") and candidate.id != "product:" + ids[0]):
            raise ExtractionError("Animefan: identidad distinta")
        if "product-type-simple" not in root.get("class", []) or self._widget(root, ".variations_form"):
            raise ExtractionError("Animefan: variantes sin verificar")
        heading_widget = self._widget(root, ".elementor-widget-woocommerce-product-title")
        headings = heading_widget.select("h1.product_title") if heading_widget else []
        if len(headings) != 1:
            raise ExtractionError("Animefan: título principal ambiguo")
        title = text(headings[0].get_text(" ", strip=True))
        structured = [row for row in jsonld(soup) if row.get("@type") == "Product" and isinstance(row.get("offers"), dict)
                      and _url(row["offers"].get("url"), product=True) == candidate.url]
        if len(structured) != 1 or normalized_name(text(structured[0].get("name", ""))) != normalized_name(title):
            raise ExtractionError("Animefan: oferta principal no coincide")
        info, labels = structured[0], _labels(root)
        card = _is_card(title, labels)
        if not card and not self.include_collectibles:
            return None
        if re.search(r"\b(?:torneo|entrada|tarjeta regalo|gift card)\b", normalized_name(title).replace("_", " ")):
            return None
        offer = info["offers"]
        if offer.get("@type") != "Offer":
            raise ExtractionError("Animefan: oferta individual no reconocida")
        code = re.fullmatch(r"https?://schema\.org/(InStock|OutOfStock|SoldOut|PreOrder|BackOrder)", str(offer.get("availability", "")))
        if not code:
            raise ExtractionError("Animefan: disponibilidad desconocida")
        code = code.group(1)
        controls = self._widget(root, ".elementor-widget-woocommerce-product-add-to-cart")
        stocks = controls.select(".stock") if controls else []
        if len(stocks) > 1:
            raise ExtractionError("Animefan: disponibilidad visible ambigua")
        stock = text(stocks[0].get_text(" ", strip=True)) if stocks else ""
        value = normalized_name(stock).replace("_", " ")
        preorder = bool(set(labels).intersection({"pre-venta", "pre-venta-almacen", "pre-venta-tipo-compra", "reservas-europa"})
                        or re.search(r"\breserva\b|\bpreventa\b|\bpre venta\b|\bproximamente\b", value))
        unavailable = bool(re.search(r"\bsin existencias\b|\bagotad[oa]\b|\bsin stock\b|\bno disponibles?\b|\bno hay existencias\b", value))
        ordered = bool(re.search(r"\bbajo pedido\b|\ba pedido\b", value) or "a-pedido" in labels)
        available = bool(re.search(r"\bhay existencias\b|\ben stock\b|\bdisponibles?\b", value))
        if unavailable:
            if code not in ("OutOfStock", "SoldOut"):
                raise ExtractionError("Animefan: stock contradictorio")
            state = "UNAVAILABLE"
        elif code in ("OutOfStock", "SoldOut"):
            raise ExtractionError("Animefan: agotado sin corroboración visible")
        elif ordered:
            state = "UNKNOWN"
        elif preorder or code == "PreOrder":
            state = "UPCOMING"
        elif code == "BackOrder":
            state = "UNKNOWN"
        elif available and code == "InStock":
            state = "AVAILABLE"
        else:
            raise ExtractionError("Animefan: stock sin corroboración visible")
        price = _money(offer.get("price")) if offer.get("priceCurrency") == "EUR" else None
        visible = _price(self._widget(root, ".elementor-widget-woocommerce-product-price"))
        deposit = controls.select_one(".awcdp-deposits-wrapper") if controls else None
        full_payment = deposit.select_one(".pay-full input[value='no'][checked]") if deposit else None
        full_wording = normalized_name(deposit.select_one(".pay-full").get_text(" ", strip=True)).replace("_", " ") if full_payment else ""
        if deposit and (full_payment is None or "importe completo" not in full_wording):
            visible = None  # A deposit-only amount cannot become the total price.
        if price is not None and visible is not None and price != visible:
            raise ExtractionError("Animefan: precio contradictorio")
        content_node = self._widget(root, ".elementor-widget-woocommerce-product-content")
        description = text(content_node.get_text("\n", strip=True))[:8000] if content_node else text(info.get("description", ""))[:8000]
        note = {"AVAILABLE": "La tienda indica existencias para este producto.", "UNAVAILABLE": "La tienda indica que este producto no tiene existencias.",
                "UPCOMING": "Reserva o preventa publicada; no acredita entrega inmediata.",
                "UNKNOWN": "Producto bajo pedido o pendiente de reposición; stock y fecha por confirmar."}[state]
        category = "card_accessory" if card and re.search(r"\balbum|\bfundas|\bbinder|\btapete", normalized_name(title)) else "card_product" if card else "figure" if any(label in labels for label in ("figuras", "figura-europa", "pvc", "resinas", "diorama")) or re.search(r"\bfigure\b|\bfigura\b|\bstatue\b", title, re.I) else "merchandise"
        data = {"region": "EU", "country": "ES", "language": "es", "channel": "online", "provenance": "retailer",
                "retailer": "Animefan", "product_id": ids[0], "identity_verified": True,
                "domain": "tcg" if card else "collectibles", "product_category": category,
                "availability_verified": state != "UNKNOWN", "availability_evidence": stock or code,
                "preorder": state == "UPCOMING", "summary": note, "price_verified": False}
        if card:
            game = _game(title, labels)
            if game:
                data["tcg"] = game
        else:
            franchise = [value.removeprefix("pa_franquicia-") for value in root.get("class", []) if value.startswith("pa_franquicia-")]
            if len(franchise) == 1:
                data["franchise"] = franchise[0].replace("-", " ").title()[:200]
        if price is not None and visible is not None:
            data.update(price=format(price, ".2f"), currency="EUR", price_verified=True)
        if deposit:
            data["deposit_option"] = True
        images = info.get("image", [])
        first = images[0] if isinstance(images, list) and images else images
        image = _url(first.get("url") if isinstance(first, dict) else first)
        if image and urlsplit(image).path.startswith("/wp-content/uploads/"):
            data.update(image_url=image, image_verified=True)
        content = "\n".join((title, description, stock, "Preventa publicada" if state == "UPCOMING" else ""))
        return Item("product:" + ids[0], self.id, title, candidate.url, kind="product", state=state, content=content, data=data)

    async def fetch(self, http) -> FetchResult:
        store = getattr(http, "store", None)
        local = getattr(self, "_metadata", {})
        def read(key, default):
            raw = store.get_meta("animefan:" + key) if store and hasattr(store, "get_meta") else local.get(key)
            try:
                return json.loads(raw) if isinstance(raw, str) else default if raw is None else raw
            except (ValueError, TypeError):
                return default
        def save(key, value):
            if store and hasattr(store, "set_meta"):
                store.set_meta("animefan:" + key, json.dumps(value, ensure_ascii=False))
            else:
                local[key] = value
        deadline = time.monotonic() + self.max_duration_seconds
        async def get(url):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError
            try:
                return await asyncio.wait_for(http.get(url), min(REQUEST_TIMEOUT_SECONDS, remaining))
            except TimeoutError:
                if time.monotonic() >= deadline:
                    raise
                raise ExtractionError("Animefan: petición agotada") from None
        found, inventories, errors = {}, {}, []
        valid_pages = 0
        if self.include_collectibles:
            try:
                front = self.parse_frontpage(await get(self.url))
                found.update((item.url, item) for item in front)
                if read("initial_frontpage", None) is None:
                    save("initial_frontpage", [item.url for item in front])
                valid_pages += 1
            except (ExtractionError, TimeoutError):
                errors.append("frontpage:unavailable")
        for base in (*CARD_CATALOGUES, *((SHOP,) if self.include_collectibles else ())):
            page = base
            for index in range(max(1, min(5, self.max_pages))):
                if not page:
                    break
                try:
                    items, next_page, complete = self.parse_listing(await get(page), page)
                    valid_pages += 1
                    found.update((item.url, item) for item in items)
                    if complete:
                        inventories["catalogue:" + urlsplit(page).path] = [item.id for item in items]
                    else:
                        errors.append("catalogue:incomplete_cards")
                    # First pages stay fresh; a separate cursor rotates their archive.
                    key = "page:" + base
                    saved = _url(read(key, None), catalogue=True)
                    page = (saved if saved and saved != base else next_page) if index == 0 else next_page
                    save(key, page or base)
                except (ExtractionError, TimeoutError):
                    errors.append("catalogue:unavailable")
                    break
        if not valid_pages:
            raise ExtractionError("Animefan: ningún inventario válido")
        known_items = store.get_source_items(self.id) if store and hasattr(store, "get_source_items") else getattr(self, "_known", [])
        for item in known_items:
            if _url(item.url, product=True) and (self.include_collectibles or item.data.get("domain") != "collectibles"):
                found.setdefault(item.url, item)
        candidates = list(found.values())
        known = {item.url for item in known_items}
        cursor = read("cursor", 0)
        cursor = (cursor if type(cursor) is int else 0) % max(1, len(candidates))
        priority_first = read("priority_first", True) is not False
        work = _work(candidates, known, max(1, self.max_items), cursor, priority_first)
        accepted, attempted = [], False
        baseline_front = set(read("initial_frontpage", []))
        for candidate, after in work:
            if time.monotonic() >= deadline:
                errors.append("details:time_budget_exhausted")
                break
            attempted = True
            if after is not None:
                cursor = after
            try:
                item = self.parse_detail(await get(candidate.url), candidate)
                if item is not None:
                    accepted.append(item)
                    if item.url in baseline_front:
                        inventories["initial-frontpage:" + item.url] = [item.id]
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
        if work and not accepted and errors:
            raise ExtractionError("Animefan: ninguna ficha confirmada; se conserva el estado")
        return FetchResult(accepted, not_modified=not accepted,
                           metadata={"method": "WooCommerce catalogues + Elementor product HTML and JSON-LD",
                                     "bootstrap_ids": [item.id for item in found.values() if item.id.startswith("product:")],
                                     "discovery_inventories": inventories, "errors": errors,
                                     "catalogue_pages": valid_pages, "bounded_window": True})
