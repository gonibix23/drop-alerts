"""Verified Pokémon editorial sources; catalogues are not proof of retail stock.

Observed on 2026-10-25: Pokémon product galleries, TCG portal news cards,
Gamespress official press pages and the Japanese card game's news list.
No Pokémon Center scraping, hidden APIs or browser runtime is required.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
import re
import time
from urllib.parse import urljoin, urlsplit, urlunsplit

from ..models import ExtractionError, FetchResult, Item
from .common import soup_from, text


def _soup(body: str):
    soup = soup_from(body)
    if soup.title and any(marker in soup.title.get_text().casefold() for marker in
                          ("pardon our interruption", "verify you are human", "robot verification")):
        raise ExtractionError("Pokémon devolvió una pantalla de verificación")
    return soup


def _url(base: str, value, hosts: set[str]) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parts = urlsplit(urljoin(base, value))
        if parts.scheme != "https" or parts.hostname not in hosts or parts.username or parts.password or parts.port not in (None, 443):
            return None
        return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), "", ""))
    except ValueError:
        return None


def _image(base: str, value, hosts: set[str]) -> dict:
    # Keep the actual approved image URL (including the publisher's image options).
    approved = _url(base, value, hosts)
    if approved:
        return {"image_url": urljoin(base, value), "image_verified": True}
    return {}


def _item(source: str, title: str, url: str, *, language="es", region="GLOBAL", kind="announcement", summary="", **data) -> Item:
    return Item(id=url, source=source, title=title, url=url, kind=kind,
                state="UNKNOWN" if kind == "product" else "ANNOUNCED",
                content=(title + "\n" + summary).strip(),
                data={"tcg": "pokemon", "region": region, "language": language,
                      "channel": "news", "provenance": "official", "summary": summary,
                      "availability_verified": False, "published_at": None, "evidence": [title], **data})


def _window(items: list[Item], known: set[str], limit: int, cursor: int):
    if not items:
        return [], 0
    cursor %= len(items)
    priority = [item for item in items if item.id not in known][:limit // 2]
    selected = set(item.id for item in priority)
    rotating, next_cursor = [], cursor
    for index, item in enumerate(items[cursor:] + items[:cursor], 1):
        if len(rotating) + len(priority) >= limit:
            break
        next_cursor = (cursor + index) % len(items)
        if item.id not in selected:
            rotating.append(item)
            selected.add(item.id)
    work = []
    for index in range(max(len(priority), len(rotating))):
        if index < len(rotating):
            work.append(rotating[index])
        if index < len(priority):
            work.append(priority[index])
    return work, next_cursor


def _cursor(source, http, total):
    store = getattr(http, "store", None)
    try:
        value = store.get_meta("source_cursor:" + source.id, 0) if store and hasattr(store, "get_meta") else getattr(source, "_cursor", 0)
        return int(value) % max(1, total)
    except (ValueError, TypeError):
        return 0


class _ListingSource:
    async def fetch(self, http) -> FetchResult:
        items = self.parse_listing(await http.get(self.url))
        store = getattr(http, "store", None)
        known = {item.id for item in store.get_source_items(self.id)} if store and hasattr(store, "get_source_items") else getattr(self, "_known", set())
        selected, self._cursor = _window(items, known, self.max_items, _cursor(self, http, len(items)))
        self._known = known | {item.id for item in selected}
        if store and hasattr(store, "set_meta"):
            store.set_meta("source_cursor:" + self.id, self._cursor)
        return FetchResult(selected, not_modified=not selected,
                           metadata={"method": "official server-rendered Pokémon listing", "bootstrap_ids": [item.id for item in items],
                                     "coverage": "listing_only", "bounded_window": len(selected) < len(items)})


@dataclass
class PokemonProductsSource(_ListingSource):
    """Rendered gallery cards identify products, never price or inventory."""
    id: str = "pokemon_products_es"
    url: str = "https://www.pokemon.com/es/jcc-pokemon/galeria-de-productos"
    language: str = "es"
    region: str = "GLOBAL"
    max_items: int = 50

    def parse_listing(self, body: str) -> list[Item]:
        soup = _soup(body)
        gallery = soup.select_one("section.pokemon-tv-seasons-landing ul.match-height")
        if gallery is None or soup.find("h1") is None:
            raise ExtractionError("Pokémon: estructura de galería no reconocida")
        prefix = "/es/jcc-pokemon/galeria-de-productos/" if self.language == "es" else "/us/pokemon-tcg/product-gallery/"
        found = {}
        for card in gallery.select("li.match"):
            anchor = card.find("a", href=True)
            url = _url(self.url, anchor.get("href"), {"www.pokemon.com"}) if anchor else None
            if not url or not urlsplit(url).path.startswith(prefix) or len(urlsplit(url).path[len(prefix):].split("/")) != 1:
                continue
            title_node = card.select_one(".season-info")
            title = text(title_node.get_text(" ", strip=True)) if title_node else ""
            if not title:
                continue
            image = card.find("img")
            data = _image(self.url, image.get("src"), {"www.pokemon.com", "assets.pokemon.com"}) if image else {}
            item = _item(self.id, title, url, language=self.language, region=self.region, kind="product",
                         summary="Producto incluido en la galería oficial de JCC Pokémon; precio y stock no verificados.",
                         channel="retail", identity_verified=True, coverage="listing_only", **data)
            item.id = "product:" + urlsplit(url).path.rsplit("/", 1)[-1]
            found[item.id] = item
        if not found:
            raise ExtractionError("Pokémon: galería sin productos reconocibles")
        return list(found.values())


@dataclass
class PokemonUSProductsSource(PokemonProductsSource):
    id: str = "pokemon_products_us"
    url: str = "https://www.pokemon.com/us/pokemon-tcg/product-gallery"
    language: str = "en"
    region: str = "US"


@dataclass
class PokemonTCGNewsSource(_ListingSource):
    id: str = "pokemon_tcg_news_es"
    url: str = "https://tcg.pokemon.com/es-es/news/"
    language: str = "es"
    region: str = "GLOBAL"
    max_items: int = 30

    def parse_listing(self, body: str) -> list[Item]:
        soup = _soup(body)
        listing = soup.select_one("div.news[data-active-filter]")
        cards = listing.select("li.news__item-column[data-filters]") if listing else []
        if not cards:
            raise ExtractionError("Pokémon TCG: estructura de noticias no reconocida")
        found = {}
        recognizable = 0
        for card in cards:
            # The publisher provides this category in rendered HTML. Strategy,
            # tournament schedules and digital games are separate scopes.
            anchor, heading = card.select_one("a.news__item[href]"), card.select_one(".news__item-title")
            if anchor is None or heading is None:
                continue
            title = text(heading.get_text(" ", strip=True))
            if title:
                recognizable += 1
            if "products" not in card.get("data-filters", "").split():
                continue
            url = _url(self.url, anchor["href"], {"www.pokemon.com", "tcg.pokemon.com"})
            if not url or not title or re.search(r"\b(?:pocket|live|estrategia|strategy|entrevista|interview|broadcast|campeonato|championship)\b", title, re.I):
                continue
            path = urlsplit(url).path
            if urlsplit(url).hostname == "www.pokemon.com" and not re.fullmatch(r"/(?:es/(?:noticias(?:-pokemon)?|destacados)|us/(?:news|pokemon-news|strategy))/[^/]+", path):
                continue
            if urlsplit(url).hostname == "tcg.pokemon.com" and not re.fullmatch(r"/(?:es-es|en-us)/expansions/[^/]+", path):
                continue
            image = card.select_one("img.news__item-image")
            images = _image(self.url, image.get("src"), {"tcg.pokemon.com", "www.pokemon.com", "assets.pokemon.com"}) if image else {}
            item = _item(self.id, title, url, language=self.language, region=self.region,
                         summary=title, announcement_url=url, coverage="listing_only", **images)
            item.id = "news:" + path.rsplit("/", 1)[-1]
            found[item.id] = item
        if not recognizable:
            raise ExtractionError("Pokémon TCG: tarjetas sin identidad reconocible")
        return list(found.values())


_PHYSICAL_TCG = re.compile(r"\bjcc\s*pok[eé]mon\b|\bpok[eé]mon\s*tcg\b|juego de cartas coleccionables pok[eé]mon|pok[eé]mon trading card game", re.I)
_DIGITAL = re.compile(r"\bpocket\b|\b(?:jcc\s*pok[eé]mon|pok[eé]mon\s*tcg)\s+live\b|\bformato digital\b|\b(?:iOS|Android)\b", re.I)
_NON_RELEASE_SECTION = re.compile(r"\b(?:prelanzamiento|prerelease)\b|\bformato digital\b|\b(?:jcc\s*pok[eé]mon|pok[eé]mon\s*tcg)\s+live\b|\bpocket\b", re.I)
_MONTHS_ES = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre")


@dataclass
class PokemonPressSource:
    id: str = "pokemon_press_es"
    url: str = "https://pokemon.gamespress.com/es"
    max_articles: int = 6
    max_duration_seconds: float = 90

    def parse_listing(self, body: str) -> list[Item]:
        soup = _soup(body)
        cards = soup.select("div.newsItem")
        if not cards:
            raise ExtractionError("Prensa Pokémon: listado no reconocido")
        candidates = {}
        for card in cards:
            anchor = card.select_one(".headline a[href]")
            url = _url(self.url, anchor.get("href"), {"pokemon.gamespress.com"}) if anchor else None
            title = text(anchor.get_text(" ", strip=True)) if anchor else ""
            if not url or not re.fullmatch(r"/es/[^/]+", urlsplit(url).path) or not title:
                continue
            # Keep only physical TCG headlines; Pocket has its own release cycle.
            if not _PHYSICAL_TCG.search(title) or _DIGITAL.search(title):
                continue
            item = _item(self.id, title, url, announcement_url=url)
            published = card.select_one("span.date")
            if published:
                try:
                    item.data["published_at"] = datetime.strptime(published.get_text(strip=True), "%d/%m/%Y").date().isoformat()
                except ValueError:
                    pass
            image = card.find("img")
            if image:
                item.data.update(_image(self.url, image.get("src"), {"imgeucdn.gamespress.com"}))
            candidates[url] = item
        return list(candidates.values())

    def parse_article(self, body: str, item: Item) -> Item:
        soup = _soup(body)
        article = soup.select_one("article#maincontent")
        heading = article.find("h1") if article else None
        content = article.select_one("section.bodytext[itemprop='articleBody']") if article else None
        if heading is None or content is None:
            raise ExtractionError("Prensa Pokémon: artículo sin cuerpo verificable")
        title = text(heading.get_text(" ", strip=True))
        if not title or not _PHYSICAL_TCG.search(title) or _DIGITAL.search(title):
            raise ExtractionError("Prensa Pokémon: noticia física no confirmada")
        for node in content.find_all(["script", "style", "form", "nav"]):
            node.decompose()
        for br in content.find_all("br"):
            br.replace_with("\n")
        paragraphs = [text(paragraph) for paragraph in re.split(r"\n\s*\n", content.get_text("", strip=False)) if text(paragraph)]
        physical = [paragraph for paragraph in paragraphs if not _NON_RELEASE_SECTION.search(paragraph)]
        if not physical:
            raise ExtractionError("Prensa Pokémon: sin párrafos físicos de producto")
        # The editorial date precedes the release sentence in one original <p>.
        # Keep it as publication metadata, never as a second product-release date.
        prefix = re.match(r"^(\d{1,2}) de (" + "|".join(_MONTHS_ES) + r") de (20\d{2})[.\s—-]+", physical[0], re.I)
        if prefix:
            try:
                item.data["published_at"] = datetime(int(prefix[3]), _MONTHS_ES.index(prefix[2].casefold()) + 1, int(prefix[1])).date().isoformat()
                item.data["publication_evidence"] = prefix[0].strip()
                physical[0] = physical[0][prefix.end():].strip()
            except ValueError:
                pass
        item.title = title
        item.content = (title + "\n" + "\n".join(physical))[:12000]
        item.data.update(summary=physical[0][:1000], evidence=[title, physical[0][:500]],
                         coverage="article_body", omitted_nonphysical_sections=len(paragraphs) - len(physical))
        image = soup.find("meta", property="og:image")
        if image:
            item.data.update(_image(item.url, image.get("content"), {"imgeucdn.gamespress.com"}))
        return item

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
            raise ExtractionError("Presupuesto de prensa Pokémon agotado") from None
        store = getattr(http, "store", None)
        known = {item.id for item in store.get_source_items(self.id)} if store and hasattr(store, "get_source_items") else getattr(self, "_known", set())
        work, self._cursor = _window(candidates, known, self.max_articles, _cursor(self, http, len(candidates)))
        accepted, errors = [], []
        for candidate in work:
            try:
                accepted.append(self.parse_article(await get(candidate.url), candidate))
            except (TimeoutError, ExtractionError):
                errors.append("article:extraction_failed")
        self._known = known | {item.id for item in accepted}
        if store and hasattr(store, "set_meta"):
            store.set_meta("source_cursor:" + self.id, self._cursor)
        if work and not accepted:
            raise ExtractionError("Prensa Pokémon: no se pudo extraer ningún artículo")
        return FetchResult(accepted, not_modified=not accepted,
                           metadata={"method": "official Pokémon press HTML", "bootstrap_ids": [item.id for item in candidates], "errors": errors})


@dataclass
class PokemonJapanNewsSource(_ListingSource):
    id: str = "pokemon_news_jp"
    url: str = "https://www.pokemon-card.com/info/"
    max_items: int = 30

    def parse_listing(self, body: str) -> list[Item]:
        soup = _soup(body)
        cards = soup.select("li.List_item")
        if not cards:
            raise ExtractionError("Pokémon Japón: noticias no reconocidas")
        found = {}
        for card in cards:
            label = card.select_one(".Calendar_Label_Products")
            anchor, image = card.find("a", href=True), card.select_one(".List_title img")
            if label is None or anchor is None:
                continue
            title = text(image.get("alt", "")) if image else ""
            if not re.search(r"拡張パック|構築デッキ|デッキセット|カードセット|プロモカード|ハイクラス|強化拡張", title) or "フィギュア" in title:
                continue
            url = _url(self.url, anchor["href"], {"www.pokemon-card.com", "www.30th.pokemon-card.com"})
            if not url or not re.fullmatch(r"/(?:info/\d+\.html|ex/[^/]+|products/.+|product/[^/]+)", urlsplit(url).path):
                continue
            item = _item(self.id, title, url, language="ja", region="JP", summary=title, coverage="listing_only", announcement_url=url)
            date = card.select_one(".Date")
            if date:
                try:
                    item.data["published_at"] = datetime.strptime(date.get_text(strip=True), "%Y.%m.%d").date().isoformat()
                except ValueError:
                    pass
            if image:
                item.data.update(_image(self.url, image.get("data-src") or image.get("src"), {"www.pokemon-card.com"}))
            found[url] = item
        return list(found.values())
