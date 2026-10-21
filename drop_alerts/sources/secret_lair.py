"""Secret Lair EU: observed public catalog discovery + verified Product JSON-LD."""
from __future__ import annotations

import json
import re
import asyncio
import time
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode, urlsplit

from ..models import ExtractionError, FetchResult, Item, fingerprint
from .common import embedded_json_arrays, jsonld, official_url, soup_from, text


AVAILABILITY = {"InStock": "AVAILABLE", "LimitedAvailability": "AVAILABLE",
                "OnlineOnly": "UNKNOWN", "PreOrder": "UPCOMING", "PreSale": "UPCOMING",
                "OutOfStock": "UNAVAILABLE", "SoldOut": "UNAVAILABLE",
                "Discontinued": "UNAVAILABLE", "BackOrder": "UNKNOWN"}
CATALOG_ORIGIN = "https://storesearch.eu.scalefast.com/StoreSearch"


@dataclass
class SecretLairSource:
    id: str = "secret_lair_eu"
    url: str = "https://secretlair.wizards.com/eu/"
    max_products: int = 50
    max_catalog_pages: int = 3
    max_duration_seconds: float = 120
    _cursor: int = field(default=0, init=False, repr=False)
    _seen_products: set[str] = field(default_factory=set, init=False, repr=False)

    def parse_home(self, body: str) -> tuple[list[Item], list[str], dict, list[str]]:
        soup = soup_from(body)
        product_urls = []
        for anchor in soup.find_all("a", href=True):
            url = official_url(self.url, anchor["href"])
            if url and re.fullmatch(r"/eu/(?:en/)?product/\d+(?:/[^/]+)?/?", urlsplit(url).path):
                product_id = re.search(r"/product/(\d+)", url).group(1)
                normalized = self.url.rstrip("/") + "/product/" + product_id
                if normalized not in product_urls:
                    product_urls.append(normalized)
        scripts = "\n".join(x.string or x.get_text() for x in soup.find_all("script"))
        config = {}
        # These literal properties were observed in sf_storesearch_config on 2026-10-21.
        marker = scripts.find("sf_storesearch_config")
        fragment = scripts[marker:marker + 20000] if marker >= 0 else ""
        for key in ("userID", "locale", "currency", "searchUrl", "searchEnv"):
            matches = re.findall(r"\b" + key + r"\s*:\s*'([^']+)'", fragment)
            if matches:
                config[key] = matches[-1]
        feeds = []
        for node in soup.select('[ng-controller="ExtraSectionController"][ng-init]'):
            match = re.match(r"init\('([0-9]+)(?:\|[^']*)?'", node["ng-init"])
            if match and match.group(1) not in feeds:
                feeds.append(match.group(1))
        announcements = []
        for event in embedded_json_arrays(soup, "upcoming_event_slides"):
            if not isinstance(event, dict) or event.get("visible") is not True:
                continue
            target = event.get("target", {})
            if not isinstance(target, dict) or not isinstance(target.get("home"), dict):
                raise ExtractionError("Estructura de anuncios Secret Lair no reconocida")
            if not target["home"].get("enabled"):
                continue
            title = text(event.get("event_name") or event.get("title") or "")
            if not title:
                continue
            subtitle, description = text(event.get("subtitle", "")), text(event.get("description", ""))
            identity = str(event.get("anchor_link") or fingerprint(title))
            announcements.append(Item(id="announcement:" + identity, source=self.id,
                                      title=title, url=self.url, kind="announcement",
                                      state="UPCOMING" if subtitle.lower() == "coming soon" else "ANNOUNCED",
                                      content="\n".join([title, subtitle, description]),
                                      data={"summary": description, "evidence": [subtitle],
                                            "availability_verified": False}))
        if not product_urls and not feeds and not announcements:
            raise ExtractionError("Secret Lair: catálogo no reconocido; se conserva el estado")
        return announcements, product_urls, config, feeds[:8]

    def parse_catalog(self, body: str) -> tuple[list[str], int]:
        try:
            data = json.loads(body)
            if not isinstance(data, dict):
                raise ValueError()
            result = data["filters"][0] if "filters" in data else data
            if not isinstance(result, dict):
                raise ValueError()
            products = result["products"]
            total = int(result.get("total", len(products)))
            if not isinstance(products, list) or total < len(products) or total < 0:
                raise ValueError()
            ids = [str(p["productID"]) for p in products if isinstance(p, dict)]
            if len(ids) != len(products) or any(not re.fullmatch(r"\d+", x) for x in ids):
                raise ValueError()
            return ids, total
        except (ValueError, TypeError, KeyError, IndexError):
            raise ExtractionError("Estructura del catálogo público no reconocida") from None

    def parse_product(self, body: str, url: str) -> Item:
        soup = soup_from(body)
        records = list(jsonld(soup))
        product = next((p for p in records if p.get("@type") == "Product"), None)
        pid = re.search(r"/product/(\d+)", url)
        if not pid or official_url(self.url, url) is None:
            raise ExtractionError("URL de producto no reconocida")
        if not product:
            # Some real catalog entries expose only Thing, not Product/Offer.
            # Confirm identity through both structured name and rendered h1,
            # but leave all commercial claims unknown.
            thing = next((p for p in records if p.get("@type") == "Thing" and isinstance(p.get("name"), str)), None)
            title = text(thing["name"]) if thing else ""
            headings = [text(node.get_text(" ", strip=True)) for node in soup.find_all("h1")]
            if not title or title.casefold() not in [h.casefold() for h in headings]:
                raise ExtractionError("Producto sin identidad estructurada y visible coherente")
            summary = text(thing.get("description", ""))[:2000]
            return Item(id="product:" + pid.group(1), source=self.id, title=title,
                        url=self.url.rstrip("/") + "/product/" + pid.group(1), kind="product",
                        state="UNKNOWN", content=title + "\n" + summary,
                        data={"summary": summary, "availability_verified": False,
                              "identity_verified": True, "structured_type": "Thing",
                              "evidence": ["Official catalog/product URL id=" + pid.group(1),
                                           "JSON-LD Thing.name agrees with HTML h1: " + title]})
        if not isinstance(product.get("name"), str) or not product["name"].strip():
            raise ExtractionError("Producto sin nombre válido")
        offers = product.get("offers", {})
        if isinstance(offers, list):
            offers = offers[0] if len(offers) == 1 else {}
        if not isinstance(offers, dict):
            offers = {}
        raw_availability = str(offers.get("availability", ""))
        availability_parts = urlsplit(raw_availability)
        availability = availability_parts.path.rsplit("/", 1)[-1]
        state = AVAILABILITY.get(availability, "UNKNOWN") if availability_parts.hostname == "schema.org" else "UNKNOWN"
        data = {"sku": str(product.get("sku", "")), "availability_verified": state != "UNKNOWN",
                "evidence": ["JSON-LD offers.availability=" + raw_availability],
                "summary": text(product.get("description", ""))[:2000]}
        currency = offers.get("priceCurrency")
        try:
            price = Decimal(str(offers["price"]))
            if (price.is_finite() and 0 <= price <= Decimal("1000000000")
                    and price.as_tuple().exponent >= -8
                    and isinstance(currency, str) and re.fullmatch(r"[A-Z]{3}", currency)):
                data.update(price=format(price.normalize(), "f"), currency=currency, price_verified=True)
        except (KeyError, ValueError, InvalidOperation):
            pass
        title = text(product["name"])
        return Item(id="product:" + pid.group(1), source=self.id, title=title,
                    url=self.url.rstrip("/") + "/product/" + pid.group(1), kind="product",
                    state=state, data=data, content=title + "\n" + data["summary"])

    async def fetch(self, http) -> FetchResult:
        deadline = time.monotonic() + self.max_duration_seconds
        async def get_with_deadline(url):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError()
            return await asyncio.wait_for(http.get(url), timeout=remaining)
        try:
            announcements, product_urls, config, feeds = self.parse_home(await get_with_deadline(self.url))
        except TimeoutError:
            raise ExtractionError("Presupuesto de consulta Secret Lair agotado") from None
        if feeds:
            if config.get("searchUrl") != CATALOG_ORIGIN or not all(config.get(k) for k in ("userID", "locale", "currency", "searchEnv")):
                raise ExtractionError("Configuración de catálogo no reconocida; no se visitan endpoints arbitrarios")
            for feed in feeds:
                seen_in_feed = set()
                for page in range(self.max_catalog_pages):
                    params = {"userID": config["userID"], "locale": config["locale"],
                              "currency": config["currency"], "sort": "featured", "offset": page * 20,
                              "count": 20, "env": config["searchEnv"], "crit": "ALL", "filters": "feedID:" + feed}
                    try:
                        ids, total = self.parse_catalog(await get_with_deadline(CATALOG_ORIGIN + "?" + urlencode(params)))
                    except TimeoutError:
                        raise ExtractionError("Presupuesto de catálogo Secret Lair agotado") from None
                    if page * 20 < total and (not ids or (page and set(ids) <= seen_in_feed)):
                        raise ExtractionError("Paginación de catálogo incompleta o repetida")
                    seen_in_feed.update(ids)
                    for pid in ids:
                        url = self.url.rstrip("/") + "/product/" + pid
                        if url not in product_urls:
                            product_urls.append(url)
                    if (page + 1) * 20 >= total:
                        break
        # Recheck saved products even when removed from the current storefront. Missing means nothing.
        store = getattr(http, "store", None)
        known_products = set(self._seen_products)
        if store and hasattr(store, "get_source_items"):
            for item in store.get_source_items(self.id):
                url = official_url(self.url, item.url)
                if item.kind == "product" and url and re.search(r"/product/\d+(?:/|$)", urlsplit(url).path):
                    known_products.add(item.id)
                    if url not in product_urls:
                        product_urls.append(url)
        # Reserve half the budget for newly discovered products; the remaining
        # rotating window guarantees that old products still get rechecked.
        if store and hasattr(store, "get_meta"):
            self._cursor = int(store.get_meta("source_cursor:" + self.id, 0)) % max(1, len(product_urls))
        new_urls = [url for url in product_urls if "product:" + re.search(r"/product/(\d+)", url).group(1) not in known_products]
        priority_urls = new_urls[:self.max_products // 2]
        selected = list(priority_urls)
        rotating = product_urls[self._cursor:] + product_urls[:self._cursor]
        normal = []
        traversed = 0
        for url in rotating:
            if len(selected) >= self.max_products:
                break
            traversed += 1
            if url not in selected:
                selected.append(url)
                normal.append((url, (self._cursor + traversed) % max(1, len(product_urls))))
        # Interleave new and historical work, so repeated failures among newly
        # discovered products cannot consume the entire time budget first.
        work = []
        for position in range(max(len(priority_urls), len(normal))):
            # Start with the rotating work, so a repeatedly failing first new
            # product cannot prevent the persistent cursor from making progress.
            if position < len(normal):
                work.append(normal[position])
            if position < len(priority_urls):
                work.append((priority_urls[position], None))
        next_cursor = self._cursor
        items = list(announcements)
        errors = []
        attempted = 0
        for url, cursor_after in work:
            if deadline <= time.monotonic():
                errors.append("details:time_budget_exhausted")
                break
            attempted += 1
            if cursor_after is not None:
                next_cursor = cursor_after
            try:
                items.append(self.parse_product(await get_with_deadline(url), url))
                self._seen_products.add(items[-1].id)
            except TimeoutError:
                errors.append("details:time_budget_exhausted")
                break
            except ExtractionError:
                product_id = re.search(r"/product/(\d+)", url).group(1)
                errors.append("product:" + product_id + ":extraction_failed")
        self._cursor = next_cursor
        if store and hasattr(store, "set_meta"):
            store.set_meta("source_cursor:" + self.id, next_cursor)
        if not items:
            raise ExtractionError("Secret Lair no devolvió elementos verificables")
        return FetchResult(items, metadata={"method": "public catalog + Product JSON-LD",
                                            "products_discovered": len(product_urls),
                                            "products_checked": attempted, "announcements": len(announcements),
                                            "errors": errors,
                                            "bootstrap_ids": [item.id for item in announcements] + [
                                                "product:" + re.search(r"/product/(\d+)", url).group(1)
                                                for url in product_urls],
                                            "bounded_window": len(selected) < len(product_urls)})
