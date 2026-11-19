"""JJCOLLECTION public sitemaps and server-rendered per-variant offers.

Verified 2026-11-19. No storefront SDK, cart requests or JavaScript execution.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
import json
import re
import time
import unicodedata
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
import xml.etree.ElementTree as ET

from ..models import ExtractionError, FetchResult, Item
from .common import jsonld, soup_from, text

ORIGIN = "https://www.jjcollection.es"
NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
IMAGE_NS = "{http://www.google.com/schemas/sitemap-image/1.1}"
MAX_DISCOVERY = 2000


def _normalize(value: str) -> str:
    return " ".join("".join(char for char in unicodedata.normalize("NFKD", value.casefold())
                            if not unicodedata.combining(char)).split())


def _url(value, *, variant=False, sitemap=False) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parts = urlsplit(urljoin(ORIGIN + "/", value))
        if (parts.scheme != "https" or parts.netloc != "www.jjcollection.es" or parts.username or parts.password
                or parts.port not in (None, 443)):
            return None
        if sitemap:
            if not re.fullmatch(r"/sitemap_products_\d+\.xml", parts.path):
                return None
            query = parse_qsl(parts.query, keep_blank_values=True)
            if any(key not in ("from", "to") or not val.isdecimal() for key, val in query):
                return None
        else:
            if not re.fullmatch(r"/products/[a-z0-9][a-z0-9-]*", parts.path):
                return None
            query = parse_qsl(parts.query, keep_blank_values=True)
            if variant:
                if len(query) != 1 or query[0][0] != "variant" or not re.fullmatch(r"[1-9]\d{0,19}", query[0][1]):
                    return None
            elif query:
                return None
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))
    except (ValueError, TypeError):
        return None


def _xml(body: str, expected: str):
    if "<!DOCTYPE" in body.upper() or "<!ENTITY" in body.upper():
        raise ExtractionError("JJCOLLECTION: XML no permitido")
    try:
        root = ET.fromstring(body)
    except (ValueError, ET.ParseError):
        raise ExtractionError("JJCOLLECTION: sitemap inválido") from None
    if root.tag != NS + expected:
        raise ExtractionError("JJCOLLECTION: estructura de sitemap no reconocida")
    return root


def _assigned_json(soup, name: str):
    values = []
    for script in soup.find_all("script"):
        content = script.string or script.get_text()
        for match in re.finditer(r"(?<![\w.])(?:window\.)?" + re.escape(name) + r"\s*=\s*", content):
            literal = content[match.end():]
            if not literal.startswith(("{", "[")):
                continue
            try:
                value, _ = json.JSONDecoder().raw_decode(literal)
                values.append(value)
            except ValueError:
                raise ExtractionError("JJCOLLECTION: JSON de producto inválido") from None
    if len(values) > 1:
        raise ExtractionError("JJCOLLECTION: identidad de producto ambigua")
    return values[0] if values else None


def _game(title: str, product_type: str, tags: list[str], brand: str) -> str | None:
    # Scope is this product's own title/type/tags/brand; never global navigation.
    value = _normalize(" ".join((title, product_type, brand, *tags)))
    patterns = {"pokemon": r"\bpokemon\b", "one_piece": r"\bone\s*piece\b", "magic": r"\bmagic\b|\bmtg\b",
                "riftbound": r"\briftbound\b", "lorcana": r"\blorcana\b", "dragon_ball": r"\bdragon\s*ball\b",
                "digimon": r"\bdigimon\b", "yugioh": r"\byu[ -]?gi[ -]?oh\b", "star_wars_unlimited": r"\bstar wars unlimited\b",
                "cyberpunk": r"\bcyberpunk\b"}
    games = [game for game, pattern in patterns.items() if re.search(pattern, value)]
    return games[0] if len(games) == 1 else None


def _relevant(title: str, product_type: str, category: str, tags: list[str], brand: str) -> bool:
    value = _normalize(" ".join((title, product_type, category, brand, *tags)))
    # Collections containing promo cards and a figure are card products; standalone
    # figures, gift cards and events are excluded by their own product type/title.
    if re.search(r"gift card|tarjeta regalo|vale regalo|\bfunko\b|\btorneo\b|\btournament\b", value):
        return False
    if re.search(r"figuras?|merchandising|peluches?", _normalize(product_type)):
        return False
    return bool(re.search(r"\btcg\b|\bcromos?\b|\bcartas?\b|trading card|\bbooster\b|\bsobres?\b|\bmazos?\b|\bdeck\b|\betb\b|"
                          r"fundas?|carpeta|\bbinder\b|tapetes?|deck ?box|top ?loader|accesorios", value))


def _image(value) -> dict:
    if not isinstance(value, str):
        return {}
    try:
        parts = urlsplit(urljoin(ORIGIN, value))
        allowed = ((parts.netloc == "www.jjcollection.es" and parts.path.startswith("/cdn/shop/"))
                   or (parts.netloc == "cdn.shopify.com" and parts.path.startswith("/s/files/1/0959/4431/1113/")))
        if parts.scheme == "https" and allowed and not parts.username and not parts.password:
            return {"image_url": urlunsplit(parts), "image_verified": True}
    except ValueError:
        pass
    return {}


@dataclass(frozen=True)
class Candidate:
    url: str
    title: str = ""
    modified: str = ""


@dataclass
class JJCollectionSource:
    id: str = "jjcollection"
    url: str = ORIGIN + "/"
    max_items: int = 12
    max_sitemaps: int = 2
    max_duration_seconds: float = 90

    def parse_sitemap_index(self, body: str) -> list[str]:
        root = _xml(body, "sitemapindex")
        urls = list(dict.fromkeys(url for row in root.findall(NS + "sitemap")
                                 if (url := _url(row.findtext(NS + "loc"), sitemap=True))))
        if not urls or len(urls) > 20:
            raise ExtractionError("JJCOLLECTION: inventario de sitemaps no reconocido")
        return urls

    def parse_sitemap(self, body: str) -> list[Candidate]:
        root = _xml(body, "urlset")
        candidates = {}
        for row in root.findall(NS + "url"):
            url = _url(row.findtext(NS + "loc"))
            if not url:
                continue
            title = row.findtext(IMAGE_NS + "image/" + IMAGE_NS + "title", "")
            modified = row.findtext(NS + "lastmod", "")
            try:
                instant = datetime.fromisoformat(modified.replace("Z", "+00:00"))
                if instant.tzinfo is None:
                    modified = ""
                else:
                    modified = str(instant.timestamp())
            except (ValueError, OverflowError):
                modified = ""
            candidates[url] = Candidate(url, title[:500], modified)
        if not candidates or len(candidates) > MAX_DISCOVERY:
            raise ExtractionError("JJCOLLECTION: inventario de productos no reconocido o excesivo")
        return list(candidates.values())

    def parse_detail(self, body: str, url: str) -> list[Item]:
        url = _url(url)
        if not url:
            raise ExtractionError("JJCOLLECTION: URL de producto no permitida")
        soup = soup_from(body)
        h1 = soup.select_one("h1.product__title")
        if h1 is None:
            raise ExtractionError("JJCOLLECTION: ficha de producto no reconocida")
        candidates = [row for row in jsonld(soup) if row.get("@type") in ("Product", "ProductGroup")
                      and _url(row.get("url")) == url]
        if len(candidates) != 1:
            raise ExtractionError("JJCOLLECTION: oferta estructurada ausente o ambigua")
        group = candidates[0]
        title = text(group.get("name", ""))
        if not title or _normalize(title) != _normalize(h1.get_text(" ", strip=True)):
            raise ExtractionError("JJCOLLECTION: título e identidad no concuerdan")
        product = _assigned_json(soup, "uppushOrderLimitProduct")
        if not isinstance(product, dict) or product.get("handle") != urlsplit(url).path.rsplit("/", 1)[-1]:
            raise ExtractionError("JJCOLLECTION: metadatos de producto ausentes o incorrectos")
        if _normalize(str(product.get("title", ""))) != _normalize(title):
            raise ExtractionError("JJCOLLECTION: metadatos de otro producto")
        tags, product_type = product.get("tags"), product.get("type")
        if (not isinstance(tags, list) or any(not isinstance(tag, str) for tag in tags)
                or not isinstance(product_type, str)):
            raise ExtractionError("JJCOLLECTION: etiquetas de producto inválidas")
        brand = group.get("brand", {})
        brand = str(brand.get("name", "")) if isinstance(brand, dict) else ""
        if not _relevant(title, product_type, str(group.get("category", "")), tags, brand):
            return []
        game = _game(title, product_type, tags, brand)
        preorder = any(_normalize(tag).replace("_", " ") in ("preventa", "preorder", "pre order", "sd preorder", "reserva") for tag in tags)
        description = text(group.get("description", ""))[:8000]
        variants = group.get("hasVariant") if group.get("@type") == "ProductGroup" else [group]
        raw_variants = product.get("variants")
        if not isinstance(variants, list) or not variants or len(variants) > 100 or not isinstance(raw_variants, list):
            raise ExtractionError("JJCOLLECTION: variantes no reconocidas")
        stock_by_id = {}
        for raw in raw_variants:
            if isinstance(raw, dict) and type(raw.get("id")) is int:
                stock_by_id[str(raw["id"])] = raw
        found = {}
        for variant in variants:
            if not isinstance(variant, dict):
                raise ExtractionError("JJCOLLECTION: variante inválida")
            offer = variant.get("offers")
            if not isinstance(offer, dict):
                raise ExtractionError("JJCOLLECTION: oferta de variante ausente")
            offer_url = _url(offer.get("url"), variant=True)
            if not offer_url or urlsplit(offer_url).path != urlsplit(url).path:
                raise ExtractionError("JJCOLLECTION: URL de variante incorrecta")
            variant_id = dict(parse_qsl(urlsplit(offer_url).query))["variant"]
            raw = stock_by_id.get(variant_id)
            if raw is None or type(raw.get("available")) is not bool:
                raise ExtractionError("JJCOLLECTION: disponibilidad de variante no reconocida")
            availability = offer.get("availability")
            if not isinstance(availability, str):
                raise ExtractionError("JJCOLLECTION: disponibilidad de oferta inválida")
            state_match = re.fullmatch(r"https?://schema\.org/(InStock|OutOfStock|SoldOut|PreOrder|BackOrder)", availability)
            if state_match is None:
                raise ExtractionError("JJCOLLECTION: estado de oferta no reconocido")
            availability = state_match.group(1)
            if raw["available"] != (availability in ("InStock", "PreOrder", "BackOrder")):
                raise ExtractionError("JJCOLLECTION: disponibilidad contradictoria")
            try:
                price = Decimal(str(offer.get("price")))
                if (offer.get("priceCurrency") != "EUR" or not price.is_finite() or price < 0 or price > 1_000_000_000
                        or type(raw.get("price")) is not int or price * 100 != raw["price"]):
                    raise ValueError("Precio no verificable")
            except (InvalidOperation, ValueError, TypeError):
                raise ExtractionError("JJCOLLECTION: precio de variante no verificable") from None
            variant_title = text(variant.get("name", ""))
            if not variant_title or _normalize(variant_title) != _normalize(str(raw.get("name", ""))):
                raise ExtractionError("JJCOLLECTION: nombre de variante no concuerda")
            state = ("UNAVAILABLE" if not raw["available"] else "UPCOMING" if preorder or availability == "PreOrder"
                     else "UNKNOWN" if availability == "BackOrder" else "AVAILABLE")
            stock_note = ("Preventa publicada; no acredita stock para entrega inmediata." if state == "UPCOMING" else
                          "La tienda admite pedidos pendientes de reposición; stock y fecha por confirmar." if state == "UNKNOWN" else
                          "Disponibilidad publicada para esta variante por la tienda.")
            data = {"region": "EU", "regions": ["EU", "ES"], "country": "ES", "language": "es", "channel": "online",
                    "provenance": "retailer", "product_url": url, "variant_id": variant_id,
                    "price": format(price, ".2f"), "currency": "EUR", "price_verified": True, "availability_verified": state != "UNKNOWN",
                    "preorder": preorder, "availability_evidence": availability,
                    "summary": stock_note, "identity_verified": True, "product_type": product_type,
                    **_image(variant.get("image", group.get("image")))}
            if game:
                data["tcg"] = game
            variant_label = raw.get("public_title")
            if isinstance(variant_label, str) and variant_label:
                data["variant"] = variant_label[:300]
            if type(product.get("id")) is int:
                data["product_id"] = str(product["id"])
            content = "\n".join((variant_title, description, "Etiquetas del producto: " + ", ".join(tags[:40]),
                                  f"Oferta de esta variante: {availability}; {format(price, '.2f')} EUR."))
            identity = "variant:" + variant_id
            if identity in found:
                raise ExtractionError("JJCOLLECTION: identidad de variante duplicada")
            found[identity] = Item(identity, self.id, variant_title, offer_url, kind="product", state=state,
                                   content=content[:12000], data=data)
        return list(found.values())

    async def fetch(self, http) -> FetchResult:
        store = getattr(http, "store", None)
        local = getattr(self, "_metadata", {})
        self._metadata = local
        def read(key, default):
            raw = store.get_meta("jjcollection:" + key) if store and hasattr(store, "get_meta") else local.get(key)
            try:
                return json.loads(raw) if isinstance(raw, str) else default if raw is None else raw
            except (TypeError, ValueError):
                return default
        def save(key, value):
            if store and hasattr(store, "set_meta"):
                store.set_meta("jjcollection:" + key, json.dumps(value, ensure_ascii=False))
            else:
                local[key] = value
        deadline = time.monotonic() + self.max_duration_seconds
        async def get(url):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError
            try:
                return await asyncio.wait_for(http.get(url), min(20, remaining))
            except TimeoutError:
                if time.monotonic() >= deadline:
                    raise
                raise ExtractionError("JJCOLLECTION: tiempo de petición agotado") from None
        try:
            maps = self.parse_sitemap_index(await get(ORIGIN + "/sitemap.xml"))
            map_paths = [urlsplit(value).path for value in maps]
            baseline_maps = read("initial_sitemaps", None)
            if not isinstance(baseline_maps, list):
                baseline_maps = map_paths
                save("initial_sitemaps", baseline_maps)
            map_cursor = read("sitemap_cursor", 0)
            map_cursor = map_cursor if type(map_cursor) is int else 0
            selected_maps = (maps[map_cursor:] + maps[:map_cursor])[:max(1, self.max_sitemaps)]
            baseline = set(read("initial_products", []))
            initialized_maps = set(read("initialized_sitemaps", []))
            found, errors = {}, []
            for map_url in selected_maps:
                try:
                    rows = self.parse_sitemap(await get(map_url))
                except (ExtractionError, TimeoutError):
                    errors.append("sitemap:extraction_failed")
                    continue
                path = urlsplit(map_url).path
                if path in baseline_maps and path not in initialized_maps:
                    baseline.update(row.url for row in rows)
                    initialized_maps.add(path)
                for row in rows:
                    found[row.url] = row
            if not found:
                raise ExtractionError("JJCOLLECTION: ningún inventario de productos válido")
            if len(baseline) > MAX_DISCOVERY * 20:
                raise ExtractionError("JJCOLLECTION: inventario inicial excesivo")
            save("initial_products", sorted(baseline))
            save("initialized_sitemaps", sorted(initialized_maps))
            save("sitemap_cursor", (map_cursor + len(selected_maps)) % len(maps))
            known_items = store.get_source_items(self.id) if store and hasattr(store, "get_source_items") else []
            seen = set(read("seen_products", []))
            for known in known_items:
                parent = _url(known.data.get("product_url"))
                if parent:
                    seen.add(parent)
                    found.setdefault(parent, Candidate(parent))
            # New discoveries are prioritized, while a reserved rotating quota keeps
            # sold-out/old products under review even when they leave the sitemap.
            candidates = sorted(found.values(), key=lambda row: (-float(row.modified or 0), row.url))
            cursor = read("product_cursor", 0)
            cursor = (cursor if type(cursor) is int else 0) % len(candidates)
            limit = max(1, self.max_items)
            priority = [row for row in candidates if row.url not in seen][:limit // 2]
            selected, ids = [], {row.url for row in priority}
            for offset, row in enumerate(candidates[cursor:] + candidates[:cursor], 1):
                if len(selected) >= limit - len(priority):
                    break
                if row.url not in ids:
                    selected.append((row, (cursor + offset) % len(candidates)))
            # Reserve actual execution slots, not merely list positions, for old
            # products: slow/new details cannot starve restock checks forever.
            work = []
            for index in range(max(len(priority), len(selected))):
                if index < len(selected):
                    work.append(selected[index])
                if index < len(priority):
                    work.append((priority[index], None))
            accepted, inventories = [], {}
            for row, cursor_after in work:
                if cursor_after is not None:
                    save("product_cursor", cursor_after)
                try:
                    items = self.parse_detail(await get(row.url), row.url)
                except TimeoutError:
                    errors.append("detail:time_budget_exhausted")
                    break
                except ExtractionError:
                    errors.append("detail:extraction_failed")
                    continue
                seen.add(row.url)
                accepted.extend(items)
                if row.url in baseline:
                    inventories["initial-product:" + row.url] = [item.id for item in items]
            if not accepted and errors:
                raise ExtractionError("JJCOLLECTION: no se pudieron confirmar productos; se conserva el estado")
            save("seen_products", sorted(seen)[-MAX_DISCOVERY * 20:])
            self._metadata = local
            return FetchResult(accepted, not_modified=not accepted,
                               metadata={"method": "public product sitemap + HTML JSON-LD variant offers",
                                         "errors": errors, "discovery_inventories": inventories,
                                         "bootstrap_ids": [item.id for item in accepted if item.data["product_url"] in baseline],
                                         "bounded_window": len(work) < len(candidates), "discovered_products": len(found)})
        except TimeoutError:
            raise ExtractionError("JJCOLLECTION: tiempo total de consulta agotado") from None
