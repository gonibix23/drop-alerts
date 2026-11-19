"""Tabletop Gamers: verified WooCommerce HTML and Product JSON-LD.

No REST API, query-string filters, cart actions or browser are used. Catalogue
pages and product details were checked on 2026-11-19; see the research note.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import re
import time
from urllib.parse import urljoin, urlsplit, urlunsplit

from ..models import ExtractionError, FetchResult, Item
from ..profiles import normalized_name
from .common import jsonld, soup_from, text

ORIGIN = "https://tabletopgamers.es"
CATALOGUE = ORIGIN + "/product-category/tcg/"
DISCOVERY = (CATALOGUE, ORIGIN + "/producto/novedades/", ORIGIN + "/producto/pre-venta/",
             ORIGIN + "/product-category/fundas/")
PRODUCT_PATH = re.compile(r"/product/[^/]+/")
PAGE_PATH = re.compile(r"/product-category/tcg/(?:page/[1-9][0-9]{0,2}/)?")
REQUEST_TIMEOUT_SECONDS = 20
GAMES = {
    "magic": r"\bmagic(?: the gathering| tg)?\b|\bmtg\b",
    "one_piece": r"\bone\s*piece\b", "pokemon": r"\bpokemon\b",
    "riftbound": r"\briftbound\b", "lorcana": r"\blorcana\b",
    "dragon_ball": r"\bdragon ball\b", "digimon": r"\bdigimon\b",
    "yugioh": r"\byu gi oh\b|\byugioh\b",
    "star_wars_unlimited": r"\bstar wars(?: unlimited)?\b|\bswu\b|\bsw unlimited\b",
    "cyberpunk": r"\bcyberpunk\b",
}


def _url(base: str, value, pattern=None) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = urlsplit(urljoin(base, value))
        if (parsed.scheme != "https" or parsed.netloc != "tabletopgamers.es" or parsed.query
                or parsed.username or parsed.password or any(char.isspace() for char in value)):
            return None
        if pattern and not pattern.fullmatch(parsed.path):
            return None
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
    except ValueError:
        return None


def _game(title: str, labels: list[str]) -> str | None:
    normalized = normalized_name(title + " " + " ".join(labels)).replace("_", " ")
    games = [game for game, pattern in GAMES.items() if re.search(pattern, normalized)]
    return games[0] if len(games) == 1 else None


def _relevant(title: str, labels: list[str]) -> bool:
    value = normalized_name(title).replace("_", " ")
    if (set(labels).intersection({"eventos", "torneos", "entradas"})
            or re.search(r"\btorneo\b|\bentrada\b|\bplazas\b|\bcluedo\b|\bmonopoly\b|\bpuzzle\b", value)
            or re.search(r"\bpre ?release\b.*\bdia \d{1,2}\b", value)):
        return False
    return bool(set(labels).intersection({"tcg", "fundas", "albumes", "deck-box", "tapetes"}))


def _money(value) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        amount = Decimal(str(value))
        if amount.is_finite() and Decimal("0") < amount <= Decimal("1000000000") and amount.as_tuple().exponent >= -4:
            return float(amount)
    except (InvalidOperation, ValueError, TypeError):
        pass
    return None


def _html_price(summary):
    container = summary.select_one(".price")
    if container is None:
        return None
    current = container.find("ins") or container
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


def _stock(summary) -> tuple[str | None, str]:
    stock = summary.select_one(".stock")
    if stock is None:
        return None, ""
    value = text(stock.get_text(" ", strip=True))
    normalized = normalized_name(value).replace("_", " ")
    classes = set(stock.get("class", []))
    if "out-of-stock" in classes or re.search(r"\bagotado\b|\bsin (?:stock|existencias)\b", normalized):
        return "UNAVAILABLE", value
    if re.search(r"\breserva\b|\bpreventa\b|\bpre venta\b", normalized):
        return "UPCOMING", value
    if "in-stock" in classes and re.search(r"\bdisponibles?\b|\ben stock\b", normalized):
        return "AVAILABLE", value
    # A backorder policy is not a dated preorder or physical stock.
    return None, value


def _window(candidates, known, limit, cursor, priority_first=True):
    priority = [item for item in candidates if item.id not in known][:limit // 2]
    reserved = {item.id for item in priority}
    rotating = []
    for step, item in enumerate(candidates[cursor:] + candidates[:cursor], 1):
        if len(rotating) + len(priority) >= limit:
            break
        if item.id not in reserved:
            rotating.append((item, (cursor + step) % max(1, len(candidates))))
    selected = []
    for index in range(max(len(priority), len(rotating))):
        pair = []
        if index < len(priority):
            pair.append((priority[index], None))
        if index < len(rotating):
            pair.append(rotating[index])
        selected.extend(pair if priority_first else reversed(pair))
    return selected


@dataclass
class TabletopGamersSource:
    id: str = "tabletop_gamers"
    url: str = ORIGIN + "/"
    max_items: int = 8
    max_pages: int = 2
    max_duration_seconds: float = 90

    def parse_listing(self, body: str) -> tuple[list[Item], str | None, bool]:
        soup = soup_from(body)
        container = soup.select_one("ul.products")
        if container is None or soup.find("h1") is None:
            raise ExtractionError("Tabletop: catálogo no reconocido")
        found, complete = {}, True
        for card in container.select("li.product.type-product"):
            labels = [value.removeprefix("product_cat-") for value in card.get("class", []) if value.startswith("product_cat-")]
            tags = [value.removeprefix("product_tag-") for value in card.get("class", []) if value.startswith("product_tag-")]
            anchor = card.select_one("li.title a[href]")
            title = text(anchor.get_text(" ", strip=True)) if anchor else ""
            if title and not _relevant(title, labels):
                continue
            url = _url(self.url, anchor.get("href"), PRODUCT_PATH) if anchor else None
            identifiers = [value[5:] for value in card.get("class", []) if re.fullmatch(r"post-[1-9][0-9]*", value)]
            if not title or not url or len(identifiers) != 1:
                complete = False
                continue
            identity = "product:" + identifiers[0]
            found[identity] = Item(identity, self.id, title, url, kind="product", data={"listing_labels": labels + tags})
        next_url = None
        for anchor in soup.select("a[href]"):
            candidate = _url(self.url, anchor["href"], PAGE_PATH)
            if candidate and "/page/" in candidate and "Entradas anteriores" in anchor.get_text(" ", strip=True):
                next_url = candidate
                break
        if not complete and not found:
            raise ExtractionError("Tabletop: fichas de catálogo incompletas")
        return list(found.values()), next_url, complete

    def parse_detail(self, body: str, candidate: Item) -> Item:
        soup = soup_from(body)
        identity = candidate.id.removeprefix("product:")
        product = soup.select_one("div.product.type-product#product-" + identity) if identity.isdigit() else None
        summary = product.select_one(".summary.entry-summary") if product else None
        title_node = summary.select_one(".product_title") if summary else None
        if product is None or summary is None or title_node is None:
            raise ExtractionError("Tabletop: identidad de ficha no reconocida")
        if "product-type-simple" not in product.get("class", []) or summary.select_one(".variations_form"):
            raise ExtractionError("Tabletop: variantes no verificadas; se conserva el estado")
        title = text(title_node.get_text(" ", strip=True))
        labels = [value.removeprefix("product_cat-") for value in product.get("class", []) if value.startswith("product_cat-")]
        labels += [value.removeprefix("product_tag-") for value in product.get("class", []) if value.startswith("product_tag-")]
        for anchor in summary.select(".product_meta a[href]"):
            link = _url(self.url, anchor["href"])
            if link and re.fullmatch(r"/product-(?:category|tag)/[^/]+/", urlsplit(link).path):
                labels.append(urlsplit(link).path.rstrip("/").rsplit("/", 1)[-1])
        if not title or not _relevant(title, labels):
            raise ExtractionError("Tabletop: ficha sin categoría de cartas o accesorios")
        structured = [entry for entry in jsonld(soup) if entry.get("@type") == "Product" and _url(self.url, entry.get("url"), PRODUCT_PATH) == candidate.url]
        if len(structured) != 1:
            raise ExtractionError("Tabletop: Product JSON-LD principal no verificable")
        info = structured[0]
        offer = info.get("offers")
        if not isinstance(offer, dict) or offer.get("@type") != "Offer":
            raise ExtractionError("Tabletop: oferta individual no verificable")
        title_key = lambda value: re.sub(r"\W+", "", normalized_name(value))
        if title_key(text(info.get("name", ""))) != title_key(title):
            raise ExtractionError("Tabletop: título estructurado no coincide")
        availability_code = re.fullmatch(r"(?:https?://schema\.org/)?(InStock|OutOfStock|SoldOut|PreOrder)", str(offer.get("availability", "")))
        schema_state = {"InStock": "AVAILABLE", "OutOfStock": "UNAVAILABLE", "SoldOut": "UNAVAILABLE", "PreOrder": "UPCOMING"}.get(availability_code.group(1)) if availability_code else None
        visible_state, availability = _stock(summary)
        # WooCommerce may advertise a purchasable reservation as InStock in SEO.
        # An explicit RESERVA label keeps it upcoming, never physical stock.
        state = "UPCOMING" if schema_state == "AVAILABLE" and visible_state == "UPCOMING" else schema_state
        if not state or not visible_state or state != visible_state:
            raise ExtractionError("Tabletop: stock ausente o contradictorio")
        price = _money(offer.get("price")) if offer.get("priceCurrency") == "EUR" else None
        visible_price = _html_price(summary)
        if price is not None and visible_price is not None and Decimal(str(price)) != Decimal(str(visible_price)):
            raise ExtractionError("Tabletop: precio contradictorio")
        description_node = summary.select_one(".woocommerce-product-details__short-description")
        description = text(description_node.get_text(" ", strip=True))[:3000] if description_node else ""
        # Keep only stable product facts, never counters, reviews, cart tokens or related products.
        content = "\n".join(value for value in (title, description, availability) if value)
        data = {"region": "EU", "country": "ES", "language": "es", "channel": "online", "provenance": "retailer",
                "retailer": "Tabletop Gamers", "product_id": identity, "identity_verified": True,
                "availability_verified": True, "availability_evidence": availability,
                "summary": description[:700] or title, "evidence": [title, availability]}
        game = _game(title, labels)
        if game:
            data["tcg"] = game
        if price is not None and visible_price is not None:
            data.update(price=price, currency="EUR", price_verified=True)
        image = info.get("image")
        image = image.get("url") if isinstance(image, dict) else image
        approved = _url(self.url, image)
        if approved and urlsplit(approved).path.startswith("/wp-content/uploads/"):
            data.update(image_url=approved, image_verified=True)
        return Item(candidate.id, self.id, title, candidate.url, kind="product", state=state, content=content, data=data)

    async def fetch(self, http) -> FetchResult:
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
                raise ExtractionError("Tabletop: tiempo de petición agotado") from None
        store = getattr(http, "store", None)
        def meta(key, default):
            return store.get_meta(key, default) if store and hasattr(store, "get_meta") else getattr(self, "_" + key.rsplit(":", 1)[-1], default)
        def save(key, value):
            if store and hasattr(store, "set_meta"):
                store.set_meta(key, value)
            else:
                setattr(self, "_" + key.rsplit(":", 1)[-1], value)
        found, inventories, errors = {}, {}, []
        next_catalogue = None
        valid_pages = 0
        for url in DISCOVERY:
            try:
                items, next_page, complete = self.parse_listing(await get(url))
                valid_pages += 1
                found.update((item.id, item) for item in items)
                if complete:
                    inventories["catalogue:" + urlsplit(url).path] = [item.id for item in items]
                else:
                    errors.append("catalogue:incomplete_cards")
                if url == CATALOGUE:
                    next_catalogue = next_page
            except (ExtractionError, TimeoutError):
                errors.append("catalogue:unavailable")
        page = _url(self.url, meta("tabletop:page", next_catalogue), PAGE_PATH)
        if page == CATALOGUE:
            page = next_catalogue
        for _ in range(max(0, min(5, self.max_pages) - 1)):
            if not page:
                break
            try:
                items, next_page, complete = self.parse_listing(await get(page))
                valid_pages += 1
                found.update((item.id, item) for item in items)
                if complete:
                    inventories["catalogue:" + urlsplit(page).path] = [item.id for item in items]
                else:
                    errors.append("catalogue:incomplete_cards")
                page = next_page or next_catalogue
            except (ExtractionError, TimeoutError):
                errors.append("catalogue:unavailable")
                break
        save("tabletop:page", page or CATALOGUE)
        if not valid_pages:
            raise ExtractionError("Tabletop: ningún catálogo válido")
        known_items = store.get_source_items(self.id) if store and hasattr(store, "get_source_items") else getattr(self, "_known_items", [])
        known = {item.id for item in known_items}
        for item in known_items:
            if _url(self.url, item.url, PRODUCT_PATH) and re.fullmatch(r"product:[1-9][0-9]*", item.id):
                found.setdefault(item.id, item)
        candidates = list(found.values())
        try:
            cursor = int(meta("tabletop:cursor", 0)) % max(1, len(candidates))
        except (ValueError, TypeError):
            cursor = 0
        priority_first = str(meta("tabletop:priority_turn", "1")) != "0"
        selected = _window(candidates, known, max(1, self.max_items), cursor, priority_first)
        accepted = []
        attempted = False
        for candidate, after in selected:
            if time.monotonic() >= deadline:
                errors.append("details:time_budget_exhausted")
                break
            if after is not None:
                cursor = after
            attempted = True
            try:
                accepted.append(self.parse_detail(await get(candidate.url), candidate))
            except TimeoutError:
                errors.append("details:time_budget_exhausted")
                break
            except ExtractionError:
                errors.append("detail:unavailable")
        save("tabletop:cursor", cursor)
        if attempted:
            save("tabletop:priority_turn", "0" if priority_first else "1")
        self._known_items = list({item.id: item for item in known_items + accepted}.values())
        if selected and not accepted:
            raise ExtractionError("Tabletop: no se pudo confirmar ninguna ficha")
        return FetchResult(accepted, not_modified=not accepted, metadata={"method": "WooCommerce HTML + Product JSON-LD",
                           "bootstrap_ids": list(found), "discovery_inventories": inventories, "errors": errors,
                           "bounded_window": True, "catalogue_pages": valid_pages})
