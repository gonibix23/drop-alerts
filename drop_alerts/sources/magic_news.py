"""Official Magic news: server-rendered article links and article body."""
from __future__ import annotations

import re
import asyncio
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

from ..models import ExtractionError, FetchResult, Item
from .common import official_url, soup_from, text


@dataclass
class MagicNewsSource:
    id: str = "magic_news"
    url: str = "https://magic.wizards.com/en/news"
    max_articles: int = 15
    max_duration_seconds: float = 120

    def parse_listing(self, body: str) -> list[Item]:
        soup = soup_from(body)
        found: dict[str, Item] = {}
        for anchor in soup.find_all("a", href=True):
            url = official_url(self.url, anchor["href"])
            if not url or not re.fullmatch(r"/en/news/[^/]+/[^/]+/?", urlsplit(url).path):
                continue
            title = text(anchor.get_text(" ", strip=True))
            if not title or title.lower() in ("read more", "learn more", "see the cards"):
                continue
            # Cards and feature blocks differ, but contain stable semantic h3/p HTML.
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

    def parse_article(self, body: str, item: Item) -> Item:
        soup = soup_from(body)
        article, heading = soup.find("article"), soup.find("h1")
        if article is None or heading is None:
            raise ExtractionError("Artículo Magic incompleto: faltan article/h1")
        for node in article.find_all(["script", "style", "nav", "form"]):
            node.decompose()
        title = text(heading.get_text(" ", strip=True))
        paragraphs = [text(p.get_text(" ", strip=True)) for p in article.find_all(["p", "li", "h2", "h3"])]
        if not any(paragraphs):
            raise ExtractionError("Artículo Magic sin contenido verificable")
        item.title = title
        item.content = (title + "\n" + "\n".join(paragraphs))[:12000]
        date = article.find("time")
        item.data["published_at"] = date.get("datetime", date.get_text(strip=True)) if date else None
        item.data["summary"] = next((p for p in paragraphs if p), item.data.get("summary", ""))[:1000]
        item.data["evidence"] = [title]
        return item

    async def fetch(self, http) -> FetchResult:
        deadline = time.monotonic() + self.max_duration_seconds
        async def get_with_deadline(url):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError()
            return await asyncio.wait_for(http.get(url), timeout=remaining)
        try:
            items = self.parse_listing(await get_with_deadline(self.url))
        except TimeoutError:
            raise ExtractionError("Presupuesto de consulta Magic agotado") from None
        # Recent bounded listing: no hidden pagination APIs and no browser required.
        selected = items[:self.max_articles]
        errors, accepted = [], []
        for item in selected:
            try:
                self.parse_article(await get_with_deadline(item.url), item)
            except TimeoutError:
                errors.append("details:time_budget_exhausted")
                break
            except ExtractionError:
                # A partial article must not overwrite a previously good full article.
                errors.append("article:" + urlsplit(item.url).path.rsplit("/", 1)[-1] + ":extraction_failed")
                continue
            accepted.append(item)
        if not accepted:
            raise ExtractionError("No se pudo extraer ningún artículo Magic; se conserva el estado")
        return FetchResult(accepted, metadata={"method": "server-rendered HTML", "articles": len(accepted),
                                               "errors": errors, "bootstrap_ids": [i.id for i in items]})
