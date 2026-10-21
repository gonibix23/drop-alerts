"""Bounded discovery of official Magic articles, with revisits of saved news."""
from __future__ import annotations

import asyncio
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import urlsplit

from ..models import ExtractionError, FetchResult, Item
from .common import official_url, soup_from, text


ARTICLE_PATH = re.compile(r"/en/news/[^/]+/[^/]+/?")
SPECIAL_TOPIC = re.compile(
    r"secret[\s-]+lair|chaos[\s-]+vault|festival[\s-]+in[\s-]+a[\s-]+box|"
    r"secret[\s-]+gallery|roadshow|zeta[\s-]+set|extra[\s-]+life|"
    r"global[\s-]+fund[\s-]+for[\s-]+women|countdown[\s-]+kit", re.I)


@dataclass
class MagicNewsSource:
    id: str = "magic_news"
    url: str = "https://magic.wizards.com/en/news"
    max_articles: int = 15
    max_duration_seconds: float = 120
    announcements_url: str = "https://magic.wizards.com/en/news/announcements"
    sitemap_url: str = "https://magic.wizards.com/en/sitemap.xml"
    max_sitemap_entries: int = 10000
    _cursor: int = field(default=0, init=False, repr=False)

    def parse_listing(self, body: str) -> list[Item]:
        soup = soup_from(body)
        found: dict[str, Item] = {}
        for anchor in soup.find_all("a", href=True):
            url = official_url(self.url, anchor["href"])
            if not url or not ARTICLE_PATH.fullmatch(urlsplit(url).path):
                continue
            title = text(anchor.get_text(" ", strip=True))
            if not title or title.lower() in ("read more", "learn more", "see the cards"):
                continue
            container = anchor.parent
            summary = ""
            if container:
                para = container.find("p")
                if para:
                    summary = text(para.get_text(" ", strip=True))
            found[url] = Item(id=url, source=self.id, title=title, url=url, kind="article",
                              state="ANNOUNCED", content=(title + "\n" + summary).strip(),
                              data={"summary": summary, "evidence": [title],
                                    "availability_verified": False})
        if not found:
            raise ExtractionError("No se encontraron artículos: estructura Magic no reconocida")
        return list(found.values())

    def parse_sitemap(self, body: str) -> list[str]:
        # Never expand entities, external resources or arbitrary sitemap links.
        if re.search(r"<!\s*(?:DOCTYPE|ENTITY)\b", body, re.I):
            raise ExtractionError("Sitemap Magic con declaraciones no admitidas")
        try:
            root = ET.fromstring(body)
        except ET.ParseError:
            raise ExtractionError("Sitemap Magic XML inválido") from None
        namespace = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
        if root.tag != namespace + "urlset":
            raise ExtractionError("Estructura de sitemap Magic no reconocida")
        nodes = root.findall(namespace + "url")
        if not nodes or len(nodes) > self.max_sitemap_entries:
            raise ExtractionError("Inventario sitemap Magic vacío o demasiado grande")
        found: dict[str, str] = {}
        valid_article = False
        for node in nodes:
            url = official_url(self.url, node.findtext(namespace + "loc", ""))
            if not url or not ARTICLE_PATH.fullmatch(urlsplit(url).path):
                continue
            valid_article = True
            if not SPECIAL_TOPIC.search(urlsplit(url).path):
                continue
            modified = node.findtext(namespace + "lastmod", "")
            try:
                datetime.fromisoformat(modified.replace("Z", "+00:00"))
            except ValueError:
                modified = ""
            found[url] = modified
        if not valid_article:
            raise ExtractionError("Sitemap Magic sin artículos reconocibles")
        # lastmod affects fetch order, never publication dates or event triggers.
        return sorted(found, key=lambda value: (found[value], value), reverse=True)

    def parse_article(self, body: str, item: Item) -> Item:
        soup = soup_from(body)
        article, heading = soup.find("article"), soup.find("h1")
        if article is None or heading is None:
            raise ExtractionError("Artículo Magic incompleto: faltan article/h1")
        for node in article.find_all(["script", "style", "nav", "form"]):
            node.decompose()
        title = text(heading.get_text(" ", strip=True))
        paragraphs = [text(p.get_text(" ", strip=True)) for p in article.find_all(["p", "li", "h2", "h3"])]
        if not title or not any(paragraphs):
            raise ExtractionError("Artículo Magic sin contenido verificable")
        item.title = title
        item.content = (title + "\n" + "\n".join(paragraphs))[:12000]
        date = article.find("time")
        item.data["published_at"] = date.get("datetime", date.get_text(strip=True)) if date else None
        item.data["summary"] = next((p for p in paragraphs if p), item.data.get("summary", ""))[:1000]
        item.data["evidence"] = [title]
        item.data["announcement_url"] = item.url
        image = soup.find("meta", property="og:image")
        if image and isinstance(image.get("content"), str):
            candidate = image["content"]
            if candidate.startswith("//"):
                candidate = "https:" + candidate
            try:
                parts = urlsplit(candidate)
                if (parts.scheme == "https" and parts.hostname in ("images.ctfassets.net", "media.wizards.com")
                        and not parts.username and not parts.password):
                    item.data.update(image_url=candidate, image_verified=True)
            except ValueError:
                # Decorative metadata cannot invalidate an otherwise valid article.
                pass
        return item

    async def fetch(self, http) -> FetchResult:
        deadline = time.monotonic() + self.max_duration_seconds

        async def get_with_deadline(url):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError()
            return await asyncio.wait_for(http.get(url), timeout=remaining)

        discovered: dict[str, Item] = {}
        errors, inventories = [], {}
        for channel, url in ((None, self.url), ("announcements_v2", self.announcements_url),
                             ("sitemap_v1", self.sitemap_url)):
            try:
                body = await get_with_deadline(url)
                if channel == "sitemap_v1":
                    urls = self.parse_sitemap(body)
                    items = [Item(id=value, source=self.id, title=urlsplit(value).path.rsplit("/", 1)[-1].replace("-", " "),
                                  url=value, kind="article", state="ANNOUNCED",
                                  data={"availability_verified": False}) for value in urls]
                else:
                    items = self.parse_listing(body)
            except TimeoutError:
                errors.append("discovery:time_budget_exhausted")
                break
            except ExtractionError:
                errors.append((channel or "frontpage") + ":discovery_failed")
                continue
            if channel:
                inventories[channel] = [item.id for item in items]
            for item in items:
                # Sitemap candidates supply no title or publication evidence.
                discovered.setdefault(item.id, item)

        store = getattr(http, "store", None)
        known = {item.id: item for item in store.get_source_items(self.id)} if store and hasattr(store, "get_source_items") else {}
        for item in known.values():
            url = official_url(self.url, item.url)
            if item.kind == "article" and url and ARTICLE_PATH.fullmatch(urlsplit(url).path):
                discovered.setdefault(item.id, item)
        if not discovered:
            raise ExtractionError("No se pudo descubrir ningún artículo Magic; se conserva el estado")

        candidates = list(discovered.values())
        unseen = [item for item in candidates if item.id not in known]
        unseen.sort(key=lambda item: not bool(SPECIAL_TOPIC.search(item.title + " " + item.url)))
        limit = max(1, self.max_articles)
        priority = unseen[:max(1, (limit + 1) // 2)] if limit > 1 else []
        # Reserve a rotating window for saved announcements and baseline backlog.
        if store and hasattr(store, "get_meta"):
            try:
                self._cursor = int(store.get_meta("source_cursor:" + self.id, 0))
            except (ValueError, TypeError):
                self._cursor = 0
        self._cursor %= len(candidates)
        rotating = candidates[self._cursor:] + candidates[:self._cursor]
        selected = list(priority)
        traversed = 0
        for item in rotating:
            if len(selected) >= limit:
                break
            traversed += 1
            if item.id not in {value.id for value in selected}:
                selected.append(item)
        self._cursor = (self._cursor + traversed) % len(candidates)
        # Rotating work runs first, so repeated fresh-page stalls cannot starve it.
        selected = selected[len(priority):] + priority
        accepted = []
        for item in selected:
            try:
                self.parse_article(await get_with_deadline(item.url), item)
            except TimeoutError:
                errors.append("details:time_budget_exhausted")
                break
            except ExtractionError:
                errors.append("article:" + urlsplit(item.url).path.rsplit("/", 1)[-1] + ":extraction_failed")
                continue
            accepted.append(item)
        if not accepted:
            raise ExtractionError("No se pudo extraer ningún artículo Magic; se conserva el estado")
        if store and hasattr(store, "set_meta"):
            store.set_meta("source_cursor:" + self.id, str(self._cursor))
        return FetchResult(accepted, metadata={"method": "server-rendered HTML + bounded sitemap discovery",
                                              "articles": len(accepted), "errors": errors,
                                              "bootstrap_ids": list(discovered),
                                              "discovery_inventories": inventories})
