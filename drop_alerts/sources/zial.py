"""Verified Zial TCG WooCommerce catalogues and individual product offers."""
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

ORIGIN = "https://www.zialtcg.com"
SEED_URL = ORIGIN + "/producto/commander-deck-display-warhammer-40k-magic-the-gathering/"
CATALOGUES = (ORIGIN + "/categoria-producto/juegos-cartas/",
              ORIGIN + "/categoria-producto/preventa/",
              ORIGIN + "/categoria-producto/accesorios/")
REQUEST_TIMEOUT_SECONDS = 20
GAME_CATEGORIES = {"magic": "magic", "one-piece": "one_piece", "pokemon": "pokemon",
                   "riftbound": "riftbound", "gundam": "gundam", "lorcana-all": "lorcana",
                   "jurassic-park": "jurassic_park", "digimon": "digimon", "yu-gi-oh": "yugioh",
                   "dragon-ball": "dragon_ball"}


def _url(value, *, product=False, catalogue=False):
    if not isinstance(value, str) or not value or any(char.isspace() for char in value):
        return None
    try:
        parts = urlsplit(urljoin(ORIGIN + "/", value))
        if parts.scheme != "https" or parts.netloc != "www.zialtcg.com" or parts.username or parts.password or parts.query:
            return None
        if product and not re.fullmatch(r"/producto/[a-z0-9][a-z0-9_-]*/", parts.path):
            return None
        if catalogue and not any(parts.path == urlsplit(base).path or re.fullmatch(re.escape(urlsplit(base).path) + r"page/[1-9][0-9]{0,3}/", parts.path) for base in CATALOGUES):
            return None
        return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
    except ValueError:
        return None


def _labels(node):
    return [value.removeprefix(prefix) for value in node.get("class", [])
            for prefix in ("product_cat-", "product_tag-") if value.startswith(prefix)]


def _relevant(title, labels):
    value = normalized_name(title).replace("_", " ")
    if (set(labels).intersection({"tarjetas-regalo", "eventos", "torneos", "entradas", "rifas", "ruletas"})
            or re.search(r"\b(?:torneos?|entradas?|rifas?|ruletas?|loterias?|gift card|tarjetas? regalo|playing cards|poker|naipes?)\b", value)):
        return False
    card_form = re.search(r"\b(?:cartas?|sobres?|booster|deck|mazos?)\b", value)
    if re.search(r"\b(?:figuras?|figures?|figurines?|miniaturas?|resina|estatuas?|statues?|peluches?)\b", value) and not card_form:
        return False
    return bool(set(labels).intersection({"juegos-cartas", "accesorios"})
                or any(value.startswith("accesorios-") for value in labels))


def _game(title, labels):
    games = {game for label, game in GAME_CATEGORIES.items() if label in labels}
    # Product-specific categories establish the game; global menus never do.
    if len(games) == 1:
        return games.pop()
    if games:
        return None
    value = normalized_name(title).replace("_", " ")
    matches = []
    for game, pattern in (("pokemon", r"\bpokemon\b"), ("one_piece", r"\bone piece\b"),
                          ("magic", r"\bmagic(?: the gathering)?\b|\bmtg\b"),
                          ("gundam", r"\bgundam\b"), ("riftbound", r"\briftbound\b"),
                          ("jurassic_park", r"\bjurassic park\b"), ("lorcana", r"\blorcana\b")):
        if re.search(pattern, value):
            matches.append(game)
    return matches[0] if len(matches) == 1 else None


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


def _price(summary):
    nodes = summary.select("p.price")
    if len(nodes) != 1:
        return None
    price = nodes[0]
    wording = normalized_name(price.get_text(" ", strip=True)).replace("_", " ")
    if re.search(r"\b(?:desde|partir|senal|deposito|reserva)\b", wording):
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
class ZialTCGSource:
    id: str = "zial_tcg"
    url: str = ORIGIN + "/"
    max_items: int = 12
    max_pages: int = 2
    max_duration_seconds: float = 90

    def parse_listing(self, body: str, catalogue: str):
        soup = soup_from(body)
        container = soup.select_one("ul.products")
        if container is None or soup.find("h1") is None or not _url(catalogue, catalogue=True):
            raise ExtractionError("Zial: catálogo no reconocido")
        found, complete = {}, True
        for card in container.select("li.product.type-product"):
            title_node = card.select_one(".woocommerce-loop-product__title")
            title = text(title_node.get_text(" ", strip=True)) if title_node else ""
            if title and not _relevant(title, _labels(card)):
                continue
            anchor = card.select_one("a.woocommerce-LoopProduct-link[href]")
            url = _url(anchor.get("href"), product=True) if anchor else None
            ids = [value.removeprefix("post-") for value in card.get("class", []) if re.fullmatch(r"post-[1-9][0-9]*", value)]
            if not title or not url or len(ids) != 1:
                complete = False
                continue
            identity = "product:" + ids[0]
            if identity in found and found[identity].url != url:
                raise ExtractionError("Zial: identidad de catálogo ambigua")
            found[identity] = Item(identity, self.id, title, url, kind="product")
        next_url = next((url for anchor in soup.select(".woocommerce-pagination a.next[href]")
                         if (url := _url(anchor.get("href"), catalogue=True))), None)
        if not complete and not found:
            raise ExtractionError("Zial: tarjetas incompletas")
        return list(found.values()), next_url, complete

    def parse_detail(self, body: str, candidate: Item):
        soup = soup_from(body)
        roots = [node for node in soup.select("div.product.type-product[id]")
                 if re.fullmatch(r"product-[1-9][0-9]*", node["id"]) and node.select_one(".summary.entry-summary h1.product_title")]
        if len(roots) != 1 or not _url(candidate.url, product=True):
            raise ExtractionError("Zial: producto principal no reconocido")
        root = roots[0]
        identity = root["id"].removeprefix("product-")
        if candidate.id.startswith("product:") and candidate.id != "product:" + identity:
            raise ExtractionError("Zial: identidad de ficha distinta")
        if "post-" + identity not in root.get("class", []) or "product-type-simple" not in root.get("class", []) or root.select_one(".variations_form"):
            raise ExtractionError("Zial: variante o identidad no verificable")
        summaries = root.select(".summary.entry-summary")
        if len(summaries) != 1:
            raise ExtractionError("Zial: resumen principal ambiguo")
        summary = summaries[0]
        headings = summary.select("h1.product_title")
        if len(headings) != 1:
            raise ExtractionError("Zial: título principal ambiguo")
        title = text(headings[0].get_text(" ", strip=True))
        labels = _labels(root)
        if not _relevant(title, labels):
            return None
        structured = [row for row in jsonld(soup) if row.get("@type") == "Product" and _url(row.get("url"), product=True) == candidate.url]
        if len(structured) != 1 or normalized_name(text(structured[0].get("name", ""))) != normalized_name(title):
            raise ExtractionError("Zial: oferta principal no coincide")
        info = structured[0]
        offers = info.get("offers")
        if isinstance(offers, dict):
            offers = [offers]
        if not isinstance(offers, list) or len(offers) != 1 or not isinstance(offers[0], dict):
            raise ExtractionError("Zial: oferta individual no verificable")
        offer = offers[0]
        if offer.get("@type") != "Offer" or _url(offer.get("url"), product=True) != candidate.url:
            raise ExtractionError("Zial: URL de oferta distinta")
        stock_nodes = summary.select("p.stock")
        if len(stock_nodes) != 1:
            raise ExtractionError("Zial: stock visible ausente o ambiguo")
        stock = text(stock_nodes[0].get_text(" ", strip=True))
        value = normalized_name(stock).replace("_", " ")
        description_node = root.select_one("#tab-description")
        description = text(description_node.get_text("\n", strip=True))[:8000] if description_node else ""
        description = re.sub(r"^Descripci[oó]n\s*", "", description, flags=re.I)
        code = re.fullmatch(r"https?://schema\.org/(InStock|OutOfStock|SoldOut|PreOrder|BackOrder)", str(offer.get("availability", "")))
        if code is None:
            raise ExtractionError("Zial: disponibilidad estructurada desconocida")
        code = code.group(1)
        unavailable = bool(re.search(r"\bsin (?:stock|existencias)\b|\bagotad[oa]\b|\bno\b.{0,60}\b(?:disponibles?|existencias|stock|unidades)\b", value))
        ordered = bool(re.search(r"\bbajo pedido\b|\ba pedido\b", value))
        preorder = bool(set(labels).intersection({"preventa", "pre-venta", "reserva", "reservas"})
                        or re.search(r"\b(?:preventa|pre venta|reserva|proximamente)\b", value)
                        or re.match(r"\s*(?:PREVENTA|PRE-VENTA|RESERVA)\b", title + "\n" + description, re.I)
                        or re.match(r"\s*(?:PREVENTA|PRE-VENTA|RESERVA)\b", description, re.I))
        available = bool(re.search(r"\bdisponibles?\b|\bhay existencias\b|\ben stock\b", value))
        if unavailable:
            if code not in ("OutOfStock", "SoldOut"):
                raise ExtractionError("Zial: stock contradictorio")
            state = "UNAVAILABLE"
        elif code in ("OutOfStock", "SoldOut"):
            raise ExtractionError("Zial: agotado sin corroboración visible")
        elif ordered or code == "BackOrder":
            state = "UNKNOWN"
        elif preorder or code == "PreOrder":
            state = "UPCOMING"
        elif available and code == "InStock":
            state = "AVAILABLE"
        else:
            raise ExtractionError("Zial: stock no verificable")
        amount = _money(offer.get("price")) if offer.get("priceCurrency") == "EUR" else None
        visible = _price(summary)
        # Never turn a deposit-only purchase into a full product price.
        if summary.select_one(".awcdp-deposits-wrapper, .wc-deposits-wrapper"):
            visible = None
        if amount is not None and visible is not None and amount != visible:
            raise ExtractionError("Zial: precio contradictorio")
        notes = {"AVAILABLE": "La tienda indica existencias para este producto.",
                 "UNAVAILABLE": "La tienda indica que este producto está agotado.",
                 "UPCOMING": "Preventa o reserva publicada; las unidades reservables no acreditan stock para entrega inmediata.",
                 "UNKNOWN": "Producto bajo pedido o pendiente de reposición; stock y fecha por confirmar."}
        data = {"region": "EU", "country": "ES", "language": "es", "channel": "online", "provenance": "retailer",
                "retailer": "Zial TCG Store", "domain": "tcg", "product_id": identity, "identity_verified": True,
                "availability_verified": state != "UNKNOWN", "availability_evidence": stock,
                "preorder": state == "UPCOMING", "summary": notes[state], "price_verified": False}
        game = _game(title, labels)
        if game:
            data["tcg"] = game
        sku = info.get("sku")
        if isinstance(sku, (str, int)) and not isinstance(sku, bool) and str(sku).strip():
            data["sku"] = str(sku)[:120]
        if amount is not None and visible is not None:
            data.update(price=format(amount, ".2f"), currency="EUR", price_verified=True)
        images = info.get("image")
        first = images[0] if isinstance(images, list) and images else images
        image = _url(first.get("url") if isinstance(first, dict) else first)
        if image and urlsplit(image).path.startswith("/wp-content/uploads/"):
            data.update(image_url=image, image_verified=True)
        return Item("product:" + identity, self.id, title, candidate.url, kind="product", state=state,
                    content="\n".join((title, description, stock, "Preventa publicada" if state == "UPCOMING" else "")), data=data)

    async def fetch(self, http):
        store = getattr(http, "store", None)
        local = getattr(self, "_metadata", {})
        def read(key, default):
            raw = store.get_meta("zial:" + key) if store and hasattr(store, "get_meta") else local.get(key)
            try:
                return json.loads(raw) if isinstance(raw, str) else default if raw is None else raw
            except (ValueError, TypeError):
                return default
        def save(key, value):
            if store and hasattr(store, "set_meta"):
                store.set_meta("zial:" + key, json.dumps(value))
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
                raise ExtractionError("Zial: petición agotada") from None
        accepted, inventories, errors = [], {}, []
        try:
            seed = self.parse_detail(await get(SEED_URL), Item("url:" + SEED_URL, self.id, "Producto vigilado", SEED_URL, kind="product"))
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
                        items, next_page, complete = self.parse_listing(await get(page), page)
                        valid_pages += 1
                        found.update((item.id, item) for item in items)
                        if complete:
                            inventories["catalogue:" + urlsplit(page).path] = [item.id for item in items]
                        else:
                            errors.append("catalogue:incomplete_cards")
                        key = "page:" + base
                        saved = _url(read(key, None), catalogue=True)
                        page = (saved if saved and saved != base else next_page) if index == 0 else next_page
                        save(key, page or base)
                    except (ExtractionError, TimeoutError):
                        errors.append("catalogue:unavailable")
                        break
        known_items = store.get_source_items(self.id) if store and hasattr(store, "get_source_items") else getattr(self, "_known", [])
        for item in known_items:
            if _url(item.url, product=True) and item.url != SEED_URL:
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
                item = self.parse_detail(await get(candidate.url), candidate)
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
            raise ExtractionError("Zial: ninguna ficha confirmada; se conserva el estado")
        if not accepted and not valid_pages:
            raise ExtractionError("Zial: ningún inventario válido")
        return FetchResult(accepted, not_modified=not accepted,
                           metadata={"method": "WooCommerce HTML + Product/Offer JSON-LD", "errors": errors,
                                     "bootstrap_ids": [item.id for item in found.values()], "discovery_inventories": inventories,
                                     "catalogue_pages": valid_pages, "pinned_product": SEED_URL, "bounded_window": True})
