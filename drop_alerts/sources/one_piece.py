"""Verified One Piece Western catalogue and public announcements (25 Oct 2026).

The publisher labels this edition NA/EU/OC/LATAM/ME. A release announcement
or USD MSRP is never treated as European stock or a checkout price.
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass
from urllib.parse import urlencode, urlsplit

from ..models import ExtractionError, FetchResult, Item
from .common import official_url, soup_from, text

ORIGIN = "https://en.onepiece-cardgame.com"
REGIONS = ["NA", "EU", "OC", "LATAM", "ME"]
PRODUCT_PATH = re.compile(r"/products/(?!index(?:\.|/|$))[^?#]+(?:\.html|\.php|/)$")
NEWS_PATH = re.compile(r"/(?:news|topics|events|information)/[^?#]+(?:\.html|\.php|/)$")
PROMOTION = re.compile(r"promo(?:tion|tional)?\b|giveaway|give away|campaign|exclusive|limited|anniversary|dash pack|special (?:card|set|prize)|premium (?:card|collection)|don!!|fest\b|comic[- ]?con", re.I)
NOISE = re.compile(r"banned|restricted|errata|card effect text|intellectual property|recommended decks|tournament results|standings|rules? (?:update|revision)|\bfaq\b", re.I)
PRODUCT_CODE = re.compile(r"\[((?:OP|ST|EB|PRB|DP|GC|SD|TS)[A-Z0-9-]+)\]", re.I)


def _same_title(expected: str, observed: str) -> bool:
    code = PRODUCT_CODE.search(expected)
    if code:
        other = PRODUCT_CODE.search(observed)
        return bool(other and code.group(1).casefold() == other.group(1).casefold())
    expected = re.sub(r"\s+has been (?:announced|updated)\.?$", "", expected, flags=re.I)
    normalize = lambda value: re.sub(r"[^\w]+", "", value.casefold())
    left, right = normalize(expected), normalize(observed)
    return bool(left and right and (left in right or right in left))


def _image(base: str, value) -> dict:
    if not isinstance(value, str):
        return {}
    try:
        url = official_url(base, value)
    except (ValueError, TypeError):
        return {}
    if url and not any(part in url for part in ("img_thumbnail", "/common/", "/modal/")):
        return {"image_url": url, "image_verified": True}
    return {}


def _metadata(summary: str, *, channel: str = "retail", **extra) -> dict:
    return {"tcg": "one_piece", "region": "WESTERN", "regions": list(REGIONS),
            "language": "en", "channel": channel, "provenance": "official",
            "availability_verified": False, "summary": summary[:1000], **extra}


def _window(candidates: list[Item], known: set[str], limit: int, cursor: int):
    priority = [item for item in candidates if item.id not in known][:limit // 2]
    selected = []
    reserved = {item.id for item in priority}
    for traversed, candidate in enumerate(candidates[cursor:] + candidates[:cursor], 1):
        if len(selected) >= limit - len(priority):
            break
        if candidate.id not in reserved:
            selected.append((candidate, (cursor + traversed) % max(1, len(candidates))))
    work = []
    for position in range(max(len(selected), len(priority))):
        if position < len(selected):
            work.append(selected[position])
        if position < len(priority):
            work.append((priority[position], None))
    return work


class _BoundedSource:
    async def _details(self, http, candidates: list[Item], get, metadata: dict) -> FetchResult:
        store = getattr(http, "store", None)
        key = "source_cursor:" + self.id
        try:
            cursor = int(store.get_meta(key, 0)) if store and hasattr(store, "get_meta") else getattr(self, "_cursor", 0)
        except (ValueError, TypeError):
            cursor = 0
        cursor %= max(1, len(candidates))
        known = {item.id for item in store.get_source_items(self.id)} if store and hasattr(store, "get_source_items") else getattr(self, "_known", set())
        accepted, errors, next_cursor = [], list(metadata.get("errors", [])), cursor
        for candidate, cursor_after in _window(candidates, known, self.max_items, cursor):
            if cursor_after is not None:
                next_cursor = cursor_after
            try:
                item = self.parse_detail(await get(candidate.url), candidate)
                if item is not None:
                    accepted.append(item)
            except TimeoutError:
                errors.append("details:time_budget_exhausted")
                break
            except ExtractionError:
                errors.append("detail:extraction_failed")
        self._cursor = next_cursor
        self._known = known | {item.id for item in accepted}
        if store and hasattr(store, "set_meta"):
            store.set_meta(key, next_cursor)
        if not accepted and any(error.startswith(("detail:", "details:")) for error in errors):
            raise ExtractionError("One Piece: no se pudo confirmar ningún detalle; se conserva el estado")
        return FetchResult(accepted, not_modified=not accepted,
                           metadata={**metadata, "errors": errors, "bootstrap_ids": [item.id for item in candidates]})


@dataclass
class OnePieceProductsSource(_BoundedSource):
    id: str = "one_piece_products"
    url: str = ORIGIN + "/products/"
    max_items: int = 8
    max_duration_seconds: float = 90

    def parse_listing(self, body: str) -> list[Item]:
        soup = soup_from(body)
        container = soup.select_one("main .linkListColInner")
        if container is None:
            raise ExtractionError("One Piece: estructura de catálogo no reconocida")
        found = {}
        for card in container.select("li.linkListColBox"):
            anchor, heading = card.select_one("a.linkListColItem[href]"), card.select_one(".linkListColTitle")
            if anchor is None or heading is None:
                continue
            try:
                url = official_url(self.url, anchor["href"])
            except (ValueError, TypeError):
                continue
            title = text(heading.get_text(" ", strip=True))
            if not url or not title or not PRODUCT_PATH.fullmatch(urlsplit(url).path):
                continue
            data = _metadata(title, announcement_url=url, evidence=[title])
            tag = card.select_one(".linkListColTag")
            if tag and "PREMIUM BANDAI" in tag.get_text().upper():
                data["distribution"] = "premium_bandai"
            image = card.find("img")
            if image:
                data.update(_image(self.url, image.get("data-src") or image.get("src")))
            found[url] = Item(url, self.id, title, url, kind="announcement", state="ANNOUNCED", data=data, content=title)
        if not found:
            raise ExtractionError("One Piece: catálogo sin productos reconocibles")
        return list(found.values())

    def parse_detail(self, body: str, item: Item) -> Item:
        soup = soup_from(body)
        article = soup.select_one("main article.articleCol")
        status = article.select_one(".detailColStatus") if article else None
        heading = article.select_one(".articleColHead h2") if article else None
        heading = heading or (status.find(["h2", "h3", "h4"]) if status else None)
        if article is None or status is None or heading is None:
            raise ExtractionError("One Piece: ficha de producto incompleta")
        title = text(heading.get_text(" ", strip=True))
        if not title or not status.find("dl") or not _same_title(item.title, title):
            raise ExtractionError("One Piece: ficha sin identidad o detalles")
        item.title = title
        paragraphs = []
        intro = article.select_one(".articleColHead p") or article.select_one(".featuresCol .text-area p")
        if intro:
            paragraphs.append(text(intro.get_text(" ", strip=True)))
        advertised = article.select_one(".mvDetailTxtDate")
        if advertised:
            paragraphs.append(text(advertised.get_text(" ", strip=True)))
        for section in status.find_all("dl", recursive=False):
            label, value = section.find("dt"), section.find("dd")
            if label is None or value is None:
                continue
            label_text, value_text = text(label.get_text(" ", strip=True)), text(value.get_text(" ", strip=True))
            paragraphs.append(label_text + ": " + value_text)
            if label_text.casefold() == "msrp":
                item.data["msrp_text"] = value_text[:200]
        if not any(paragraphs):
            raise ExtractionError("One Piece: detalles de producto vacíos")
        item.content = (title + "\n" + "\n".join(paragraphs))[:12000]
        item.data.update(summary=(paragraphs[0] if intro else title)[:1000], evidence=[title], announcement_url=item.url)
        code = PRODUCT_CODE.search(title)
        if code:
            item.data["product_code"] = code.group(1)
        image = article.select_one(".detailColSlider img[data-src]") or article.select_one(".detailColSlider img[src]")
        if image:
            item.data.update(_image(item.url, image.get("data-src") or image.get("src")))
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
            raise ExtractionError("Presupuesto de catálogo One Piece agotado") from None
        store = getattr(http, "store", None)
        if store and hasattr(store, "get_source_items"):
            ids = {item.id for item in candidates}
            for saved in store.get_source_items(self.id):
                url = official_url(self.url, saved.url)
                if url and PRODUCT_PATH.fullmatch(urlsplit(url).path) and saved.id not in ids:
                    candidates.append(saved)
                    ids.add(saved.id)
        return await self._details(http, candidates, get, {"method": "official server-rendered product catalogue", "bounded_window": True})


@dataclass
class OnePieceNewsSource(_BoundedSource):
    id: str = "one_piece_news"
    url: str = ORIGIN + "/news/"
    max_items: int = 8
    max_pages: int = 2
    max_duration_seconds: float = 90

    def api_url(self, page: int) -> str:
        # Observed in /renewal/js/news_async.js, verified as public GET on 25 Oct.
        data = json.dumps({"category": "INFORMATION", "subcategory": [""], "is_history": True}, separators=(",", ":"))
        return ORIGIN + "/common/templates/api/article_list.php?" + urlencode({"start": page * 10, "limit": 10, "data": data})

    def parse_api(self, body: str, start: int = 0) -> tuple[list[Item], int]:
        try:
            envelope = json.loads(body)
            data = envelope["data"]
            entries, total = data["article_list"], data["total_count"]
            if (envelope["statusCode"] != 200 or data["apiStatus"] is not True or not isinstance(entries, list)
                    or type(total) is not int or total < len(entries) or len(entries) > 50
                    or data.get("start") != start or (start < total and not entries)):
                raise ValueError()
        except (ValueError, KeyError, TypeError):
            raise ExtractionError("One Piece: estructura de noticias pública no reconocida") from None
        found = {}
        for entry in entries:
            try:
                if not isinstance(entry, dict) or entry.get("site") != "en" or entry.get("publish_status") != "publish":
                    raise ValueError()
                title = entry["title"]
                category = entry["categories"]["subcategory"][0]["code"]
                if not isinstance(title, str) or not isinstance(category, str):
                    raise ValueError()
                # Product pages have their own monitored identity; cardlists,
                # rules and errata are not new product/promotion announcements.
                if category in ("products", "cards", "rules") or NOISE.search(title):
                    continue
                onepiece = entry.get("onepiece", {})
                if not isinstance(onepiece, dict) or not isinstance(onepiece.get("related_item", {}), dict):
                    raise ValueError()
                references = onepiece.get("related_item", {}).get("en", [])
                if not isinstance(references, list):
                    raise ValueError()
                reference = references[0] if references else None
                target = reference["url"] if reference else entry["url"]
                if reference and reference["type"] == "article":
                    target += ".html"
                url = official_url(self.url, target)
                if not url or not NEWS_PATH.fullmatch(urlsplit(url).path):
                    continue
                title = text(title)
                event = category == "events" or urlsplit(url).path.startswith("/events/")
                # Events get a body check for explicit special/promo rewards;
                # ordinary tournament result pages and generic site news do not.
                if not event and not PROMOTION.search(title):
                    continue
                published = entry.get("dspdate", "")
                published = published[:10].replace("/", "-") if isinstance(published, str) and re.match(r"^\d{4}/\d{2}/\d{2}", published) else None
                metadata = _metadata(title, channel="event" if event else "announcement", category=category,
                                     published_at=published, announcement_url=url, evidence=[title])
                metadata.update(_image(self.url, entry.get("thumbnail")))
                found.setdefault(url, Item(url, self.id, title, url, kind="event" if event else "announcement", state="ANNOUNCED", data=metadata, content=title))
            except (ValueError, KeyError, TypeError, IndexError):
                raise ExtractionError("One Piece: entrada de noticias incompleta") from None
        return list(found.values()), total

    def parse_home(self, body: str) -> list[Item]:
        soup = soup_from(body)
        cards = soup.select("main .newsList > li.newsListItem")
        if not cards:
            raise ExtractionError("One Piece: portada sin noticias reconocibles")
        found = {}
        for card in cards:
            anchor, heading = card.select_one("a.newsListLink[href]"), card.select_one(".newsTitle")
            if not anchor or not heading:
                continue
            try:
                url = official_url(self.url, anchor["href"])
            except (ValueError, TypeError):
                continue
            title = text(heading.get_text(" ", strip=True))
            if not url or not NEWS_PATH.fullmatch(urlsplit(url).path) or NOISE.search(title):
                continue
            event = urlsplit(url).path.startswith("/events/")
            if not event and not PROMOTION.search(title):
                continue
            date = card.find("time")
            published = date.get("datetime", "")[:10] if date else None
            data = _metadata(title, channel="event" if event else "announcement", published_at=published, announcement_url=url, evidence=[title])
            found[url] = Item(url, self.id, title, url, kind="event" if event else "announcement", state="ANNOUNCED", data=data, content=title)
        return list(found.values())

    def parse_detail(self, body: str, item: Item) -> Item | None:
        soup = soup_from(body)
        article = soup.select_one("main article.articleCol")
        heading = article.select_one(".pageTitCol h2") if article else None
        content = article.select_one(".contentsCol") if article else None
        # Older event landing pages use the verified LP template and image alt
        # as their visible heading. This is text supplied by the publisher, not OCR.
        landing = soup.select_one("main .lpWrap")
        landing_title = landing.select_one(".lpTitle img[alt]") if landing else None
        landing_body = landing.select_one("article.lpMainCol") if landing else None
        if landing_title and landing_body:
            observed = text(landing_title["alt"])
            simplify = lambda value: re.sub(r"\b(?:in|feat\.?|featuring)\b", " ", value, flags=re.I)
            if not _same_title(simplify(item.title), simplify(observed)):
                raise ExtractionError("One Piece: identidad de evento inconsistente")
            paragraphs = [text(node.get_text(" ", strip=True)) for node in landing_body.find_all(["p", "h3", "h4", "h5", "li"])]
            if not any(paragraphs):
                raise ExtractionError("One Piece: evento sin contenido verificable")
            if not PROMOTION.search(observed + "\n" + "\n".join(paragraphs)):
                return None
            item.title = observed
            item.content = (observed + "\n" + "\n".join(paragraphs))[:12000]
            summary = landing_body.select_one(".lpMvCatch") or landing_body.find("p")
            item.data.update(summary=text(summary.get_text(" ", strip=True))[:1000], evidence=[observed])
            period = landing_body.select_one(".lpEventPeriod")
            if period:
                item.data["event_period_text"] = text(period.get_text(" ", strip=True))[:300]
            outline = landing_body.select_one("#lpOutline")
            if outline and re.search(r"\bUSA\b|\bUnited States\b", outline.get_text(" ", strip=True), re.I):
                item.data.update(region="US", regions=["US"])
            image = landing_body.select_one(".lpMvImg img[src]")
            if image:
                item.data.update(_image(item.url, image.get("src")))
            return item
        if article is None or heading is None or content is None:
            raise ExtractionError("One Piece: anuncio incompleto")
        for node in content.find_all(["script", "style", "nav", "form"]):
            node.decompose()
        title = text(heading.get_text(" ", strip=True))
        paragraphs = [text(node.get_text(" ", strip=True)) for node in content.find_all(["p", "h3", "h4", "h5", "li"])]
        if not title or not any(paragraphs) or not _same_title(item.title, title):
            raise ExtractionError("One Piece: anuncio sin texto")
        body_text = "\n".join(paragraphs)
        if NOISE.search(title) or not PROMOTION.search(title + "\n" + body_text):
            return None
        item.title, item.content = title, (title + "\n" + body_text)[:12000]
        item.data.update(summary=next((value for value in paragraphs if value), title)[:1000], evidence=[title])
        if item.kind == "event":
            # Keep the original event period, never present it as a sale opening.
            period = next((heading.find_next("p") for heading in content.find_all(["h3", "h4"])
                           if text(heading.get_text(" ", strip=True)).casefold() == "period"), None)
            if period:
                item.data["event_period_text"] = text(period.get_text(" ", strip=True))[:300]
        image = article.select_one(".mvImgCol img[src]")
        if image:
            item.data.update(_image(item.url, image.get("src")))
        return item

    async def fetch(self, http) -> FetchResult:
        deadline = time.monotonic() + self.max_duration_seconds
        async def get(url):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError
            return await asyncio.wait_for(http.get(url), remaining)
        errors, found = [], {}
        try:
            soup = soup_from(await get(self.url))
            if soup.find("div", id="vueapp") is None or not any("/renewal/js/news_async.js" in node.get("src", "") for node in soup.find_all("script", src=True)):
                raise ExtractionError("One Piece: interfaz de noticias cambió")
            for page in range(self.max_pages):
                items, total = self.parse_api(await get(self.api_url(page)), page * 10)
                found.update((item.id, item) for item in items if item.id not in found)
                if (page + 1) * 10 >= total:
                    break
        except (ExtractionError, TimeoutError):
            errors.append("news_api:unavailable")
            try:
                fallback = self.parse_home(await get(ORIGIN + "/"))
                found.update((item.id, item) for item in fallback if item.id not in found)
            except TimeoutError:
                raise ExtractionError("Presupuesto de noticias One Piece agotado") from None
        candidates = list(found.values())
        metadata = {"method": "verified public news JSON + server-rendered fallback", "errors": errors,
                    "discovery_inventories": {"official_news_api_v1": list(found)} if not errors else {}}
        return await self._details(http, candidates, get, metadata)
