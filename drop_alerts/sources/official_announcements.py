"""Bounded official announcement sources, using observed HTML/public catalog contracts.

These adapters report publication, never purchase availability. See the checked
source URLs and captured semantic fragments in tests/fixtures/announcements_*.
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass
from urllib.parse import urlencode, urljoin, urlsplit

from ..models import ExtractionError, FetchResult, Item
from .common import official_url, soup_from, text
from .secret_lair import CATALOG_ORIGIN, SecretLairSource


SPECIAL_TERMS = ("secret lair", "chaos vault", "festival in a box", "secret gallery", "roadshow")


def is_special_announcement(value: str) -> bool:
    value = value.casefold()
    return any(term in value for term in SPECIAL_TERMS) or (
        any(term in value for term in ("exclusive", "limited edition", "special promotion"))
        and any(term in value for term in ("promo card", "promotional card"))
    )


def _image(soup, base: str, allowed_hosts: set[str]) -> dict:
    node = soup.find("meta", property="og:image")
    try:
        candidate = urljoin(base, node.get("content", "")) if node else ""
        parts = urlsplit(candidate)
    except (ValueError, TypeError):
        return {}
    if parts.scheme == "https" and parts.hostname in allowed_hosts and not parts.username and not parts.password:
        return {"image_url": candidate, "image_verified": True}
    return {}


def _announcement(source: str, title: str, url: str, summary: str = "", **data) -> Item:
    return Item(id=url, source=source, title=title, url=url, kind="announcement", state="ANNOUNCED",
                content=(title + "\n" + summary).strip(),
                data={"summary": summary, "evidence": [title], "availability_verified": False,
                      "announcement_url": url, "region": "GLOBAL", **data})


def _window(items: list[Item], known: set[str], limit: int, cursor: int):
    """Reserve half for newly discovered IDs, while advancing historical work."""
    priority = [item for item in items if item.id not in known][:limit // 2]
    priority_ids = {item.id for item in priority}
    rotating = []
    for traversed, item in enumerate(items[cursor:] + items[:cursor], 1):
        if len(rotating) >= limit - len(priority):
            break
        if item.id not in priority_ids:
            rotating.append((item, (cursor + traversed) % max(1, len(items))))
    # Attempt rotating work first: a repeatedly slow or broken new URL cannot
    # consume every budget before the historical cursor has made progress.
    work = []
    for position in range(max(len(priority), len(rotating))):
        if position < len(rotating):
            work.append(rotating[position])
        if position < len(priority):
            work.append((priority[position], None))
    return work


class _EditorialSource:
    """Shared bounded workflow; concrete adapters own their observed markup."""

    async def fetch(self, http) -> FetchResult:
        deadline = time.monotonic() + self.max_duration_seconds

        async def get(url):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError
            return await asyncio.wait_for(http.get(url), remaining)

        try:
            candidates = self.parse_listing(await get(self.url))
        except TimeoutError:
            raise ExtractionError("Presupuesto de consulta de anuncios agotado") from None
        store = getattr(http, "store", None)
        key = "source_cursor:" + self.id
        cursor = int(store.get_meta(key, 0)) if store and hasattr(store, "get_meta") else getattr(self, "_cursor", 0)
        cursor %= max(1, len(candidates))
        inventory_key = "source_discovery_seen:" + self.id
        known = getattr(self, "_known_candidates", set())
        if store and hasattr(store, "get_meta"):
            try:
                value = json.loads(store.get_meta(inventory_key, "[]"))
                known = {item for item in value if isinstance(item, str)} if isinstance(value, list) else set()
            except (ValueError, TypeError):
                known = set()
        # Include all discovered URLs, not only relevant persisted items. Failed
        # or irrelevant new articles must not retain priority on every poll.
        selected = _window(candidates, known, self.max_articles, cursor)
        accepted, errors = [], []
        traversed = 0
        next_cursor = cursor
        for candidate, cursor_after in selected:
            traversed += 1
            if cursor_after is not None:
                next_cursor = cursor_after
            try:
                item = self.parse_article(await get(candidate.url), candidate)
            except TimeoutError:
                errors.append("article:time_budget_exhausted")
                break
            except ExtractionError:
                errors.append("article:extraction_failed")
                continue
            if is_special_announcement(item.title + "\n" + item.content):
                accepted.append(item)
        self._cursor = next_cursor
        self._known_candidates = {item.id for item in candidates}
        if store and hasattr(store, "set_meta"):
            store.set_meta(key, self._cursor)
            store.set_meta(inventory_key, json.dumps([item.id for item in candidates[:512]]))
        if not accepted and errors:
            raise ExtractionError("No se pudo confirmar el contenido de los anuncios; se conserva el estado")
        # A successfully parsed listing with valid but irrelevant articles is a
        # healthy empty result. A login/challenge/changed structure fails above.
        return FetchResult(accepted, not_modified=not accepted,
                           metadata={"method": "official HTML announcements", "errors": errors,
                                     "articles_checked": traversed, "bootstrap_ids": [i.id for i in candidates]})


@dataclass
class WPNNewsSource(_EditorialSource):
    id: str = "wpn_news"
    url: str = "https://wpn.wizards.com/en/news"
    max_articles: int = 8
    max_duration_seconds: float = 90

    def parse_listing(self, body: str) -> list[Item]:
        soup = soup_from(body)
        # The current listing is Nuxt SSR inside #__nuxt, without a main tag.
        # Individual WPN articles do expose main (used by parse_article).
        main = soup.find("main") or soup.find("div", id="__nuxt")
        if main is None:
            raise ExtractionError("WPN: listado sin contenedor reconocido")
        found = {}
        for anchor in main.find_all("a", href=True):
            url = official_url(self.url, anchor["href"])
            if not url or not re.fullmatch(r"/en/news/[^/]+/?", urlsplit(url).path):
                continue
            heading, container = None, anchor
            for parent in [anchor, *list(anchor.parents)[:4]]:
                headings = parent.find_all(["h2", "h3"])
                if len(headings) == 1:
                    heading, container = headings[0], parent
                    break
            title = text(heading.get_text(" ", strip=True) if heading else anchor.get_text(" ", strip=True))
            if not title or title.casefold() in ("read more", "learn more"):
                continue
            paragraph = container.find("p")
            summary = text(paragraph.get_text(" ", strip=True))[:1000] if paragraph else ""
            found[url] = _announcement(self.id, title, url, summary, channel="retail")
        if not found:
            raise ExtractionError("WPN: estructura de noticias no reconocida")
        return list(found.values())

    def parse_article(self, body: str, item: Item) -> Item:
        soup = soup_from(body)
        main = soup.find("main")
        article = main.find(attrs={"data-article-id": True}) if main else None
        heading = main.find(["h1", "h2"]) if main else None
        if article is None or heading is None:
            raise ExtractionError("WPN: artículo sin cuerpo e identidad verificables")
        paragraphs = [text(p.get_text(" ", strip=True)) for p in article.find_all(["p", "li", "h2", "h3"])]
        if not any(paragraphs):
            raise ExtractionError("WPN: artículo vacío")
        item.title = text(heading.get_text(" ", strip=True))
        item.content = (item.title + "\n" + "\n".join(paragraphs))[:12000]
        item.data.update(summary=next(p for p in paragraphs if p)[:1000], evidence=[item.title],
                         **_image(soup, item.url, {"wpn.wizards.com", "images.ctfassets.net"}))
        date = heading.find_previous_sibling("p")
        match = re.match(r"[A-Za-z]+ \d{1,2}, \d{4}", date.get_text(" ", strip=True)) if date else None
        if match:
            item.data["published_at"] = match.group(0)
        return item


@dataclass
class MagicConNewsSource(_EditorialSource):
    id: str = "magiccon_news"
    url: str = "https://www.mtgfestivals.com/global/en-us/magiccon-news.html"
    max_articles: int = 8
    max_duration_seconds: float = 90

    def parse_listing(self, body: str) -> list[Item]:
        soup = soup_from(body)
        found = {}
        for anchor in soup.select("a.card__base[href]"):
            url = official_url(self.url, anchor["href"])
            if not url or not re.fullmatch(r"/global/en-us/magiccon-news/\d{4}/[^/]+\.html", urlsplit(url).path):
                continue
            heading = anchor.select_one(".card__title")
            title = text(heading.get_text(" ", strip=True) if heading else anchor.get("title", ""))
            if not title:
                continue
            summary = anchor.select_one(".card__text")
            date = anchor.select_one(".card__date")
            data = {"channel": "event"}
            if date:
                data["published_at"] = text(date.get_text(" ", strip=True))
            found[url] = _announcement(self.id, title, url,
                                      text(summary.get_text(" ", strip=True))[:1000] if summary else "", **data)
        if not found:
            raise ExtractionError("MagicCon: estructura de noticias no reconocida")
        return list(found.values())

    def parse_article(self, body: str, item: Item) -> Item:
        soup = soup_from(body)
        # AEM renders the article in cmp-text components; there is no article/main.
        components = soup.select("div.cmp-text[data-rxtag-multiple='text']")
        if not soup.find("h1") or not components:
            raise ExtractionError("MagicCon: artículo incompleto")
        paragraphs = [text(p.get_text(" ", strip=True)) for component in components
                      for p in component.find_all(["p", "li", "h2", "h3"])]
        if not any(paragraphs):
            raise ExtractionError("MagicCon: artículo sin texto")
        item.content = (item.title + "\n" + "\n".join(paragraphs))[:12000]
        relevant = [p for p in paragraphs if is_special_announcement(p)]
        item.data.update(summary=(relevant[0] if relevant else next(p for p in paragraphs if p))[:1000],
                         evidence=[item.title, *relevant[:2]],
                         **_image(soup, item.url, {"www.mtgfestivals.com"}))
        return item


@dataclass
class ChaosVaultSource:
    id: str = "chaos_vault_eu"
    url: str = "https://secretlair.wizards.com/eu/chaosvault"
    max_products: int = 100
    max_catalog_pages: int = 4
    max_duration_seconds: float = 90

    def parse_listing(self, body: str) -> list[str]:
        soup = soup_from(body)
        feeds = []
        for catalogue in soup.find_all("sf-filter-catalogue", crit=True):
            match = re.fullmatch(r"feedID:(\d+)", catalogue["crit"])
            if match and match.group(1) not in feeds:
                feeds.append(match.group(1))
        if not feeds:
            raise ExtractionError("Chaos Vault: catálogo no reconocido")
        return feeds[:4]

    def parse_catalog(self, body: str, feed: str) -> tuple[list[Item], int]:
        parser = SecretLairSource()
        ids, total = parser.parse_catalog(body)
        data = json.loads(body)
        products = data["filters"][0]["products"] if "filters" in data else data["products"]
        items = []
        for product, pid in zip(products, ids):
            descriptions = product.get("descriptions")
            if not isinstance(descriptions, list):
                raise ExtractionError("Chaos Vault: producto sin descripción estructurada")
            title = next((text(d.get("title", "")) for d in descriptions
                          if isinstance(d, dict) and d.get("lang") == "EN"
                          and isinstance(d.get("title"), str)), "")
            if not title:
                raise ExtractionError("Chaos Vault: producto sin nombre verificable")
            url = "https://secretlair.wizards.com/eu/product/" + pid
            item = _announcement(self.id, title, url, "Producto publicado en el catálogo oficial de Chaos Vault EU.",
                                 region="EU", channel="online", product_id=pid,
                                 evidence=["Chaos Vault feedID:" + feed, "catalog.productID=" + pid, title])
            item.id = "product:" + pid
            image = product.get("image")
            try:
                parts = urlsplit(image) if isinstance(image, str) else None
            except ValueError:
                parts = None
            if parts and parts.scheme == "https" and parts.hostname == "cdn-prod.scalefast.com" and not parts.username and not parts.password:
                item.data.update(image_url=image, image_verified=True)
            # Catalog commercial flags are deliberately not interpreted here.
            items.append(item)
        return items, total

    async def fetch(self, http) -> FetchResult:
        deadline = time.monotonic() + self.max_duration_seconds

        async def get(url):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError
            return await asyncio.wait_for(http.get(url), remaining)

        try:
            feeds = self.parse_listing(await get(self.url))
            # The Chaos Vault HTML references the filter but not its transport
            # config. Discover the latter from the same official EU home page.
            _, _, config, _ = SecretLairSource().parse_home(await get("https://secretlair.wizards.com/eu/"))
            if config.get("searchUrl") != CATALOG_ORIGIN or not all(config.get(k) for k in ("userID", "locale", "currency", "searchEnv")):
                raise ExtractionError("Chaos Vault: configuración de catálogo no reconocida")
            discovered = {}
            bounded = False
            for feed in feeds:
                seen = set()
                for page in range(self.max_catalog_pages):
                    params = {"userID": config["userID"], "locale": config["locale"], "currency": config["currency"],
                              "sort": "featured", "offset": page * 20, "count": 20, "env": config["searchEnv"],
                              "crit": "ALL", "filters": "feedID:" + feed}
                    items, total = self.parse_catalog(await get(CATALOG_ORIGIN + "?" + urlencode(params)), feed)
                    ids = {item.id for item in items}
                    if page * 20 < total and (not items or ids <= seen):
                        raise ExtractionError("Chaos Vault: paginación incompleta o repetida")
                    seen.update(ids)
                    discovered.update((item.id, item) for item in items)
                    if (page + 1) * 20 >= total:
                        break
                    if page + 1 == self.max_catalog_pages:
                        bounded = True
            all_items = list(discovered.values())
            store = getattr(http, "store", None)
            key = "source_cursor:" + self.id
            cursor = int(store.get_meta(key, 0)) if store and hasattr(store, "get_meta") else getattr(self, "_cursor", 0)
            cursor %= max(1, len(all_items))
            known = getattr(self, "_known_items", set())
            if store and hasattr(store, "get_source_items"):
                known = {item.id for item in store.get_source_items(self.id)}
            work = _window(all_items, known, self.max_products, cursor)
            selected = [item for item, _ in work]
            self._cursor = next((position for _, position in reversed(work) if position is not None), cursor)
            self._known_items = known | {item.id for item in selected}
            if store and hasattr(store, "set_meta"):
                store.set_meta(key, self._cursor)
            return FetchResult(selected, not_modified=not selected,
                               metadata={"method": "official Chaos Vault public catalog", "region": "EU",
                                         "bootstrap_ids": list(discovered), "bounded_window": bounded or len(selected) < len(all_items)})
        except TimeoutError:
            raise ExtractionError("Presupuesto de consulta Chaos Vault agotado") from None
