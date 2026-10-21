"""Small RSS/Atom reader for verified feeds. No browser or feed SDK required."""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit

from ..identities import referenced_announcement
from ..models import ExtractionError, FetchResult, Item, safe_url
from .common import text
from .relevance import relevant_announcement

ATOM = "{http://www.w3.org/2005/Atom}"
MEDIA = "{http://search.yahoo.com/mrss/}"
YOUTUBE = "{http://www.youtube.com/xml/schemas/2015}"


def published_date(value: str | None) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        try:
            date = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            date = parsedate_to_datetime(value)
        # A feed without timezone does not establish an exact instant.
        return date.astimezone(timezone.utc).isoformat() if date.tzinfo else None
    except (ValueError, TypeError, OverflowError):
        return None


@dataclass
class FeedSource:
    id: str
    url: str
    allowed_hosts: tuple[str, ...]
    max_items: int = 50
    official: bool = False
    youtube_channel: str | None = None

    def parse(self, body: str) -> FetchResult:
        if re.search(r"<!\s*(?:DOCTYPE|ENTITY)\b", body, re.I):
            raise ExtractionError("Declaración XML no permitida")
        try:
            root = ET.fromstring(body)
        except ET.ParseError:
            raise ExtractionError("Feed XML inválido") from None
        if root.tag == "rss" and root.find("channel") is not None:
            channel = root.find("channel")
            if not channel.findtext("title") or not channel.findtext("link"):
                raise ExtractionError("RSS sin identidad de canal")
            entries, atom = channel.findall("item"), False
        elif root.tag == ATOM + "feed" and root.findtext(ATOM + "title"):
            entries, atom = root.findall(ATOM + "entry"), True
        else:
            raise ExtractionError("Estructura RSS/Atom no reconocida")
        if self.youtube_channel and root.findtext(YOUTUBE + "channelId") != self.youtube_channel:
            raise ExtractionError("El feed no pertenece al canal de Magic configurado")
        if len(entries) > 1000:
            raise ExtractionError("Feed con demasiadas entradas")
        items, identities, invalid, seen = [], [], 0, set()
        for node in entries:
            title = node.findtext(ATOM + "title" if atom else "title", "")
            if atom:
                link = next((link.get("href", "") for link in node.findall(ATOM + "link")
                             if link.get("rel", "alternate") == "alternate"), "")
                identity = node.findtext(ATOM + "id") or link
                raw = node.findtext(ATOM + "summary") or node.findtext(ATOM + "content") or node.findtext(MEDIA + "group/" + MEDIA + "description", "")
                published = node.findtext(ATOM + "published")
            else:
                link = node.findtext("link", "")
                identity = node.findtext("guid") or link
                raw = node.findtext("description", "")
                published = node.findtext("pubDate")
            try:
                link = safe_url(link)
                if urlsplit(link).scheme != "https" or urlsplit(link).hostname not in self.allowed_hosts:
                    raise ValueError()
                if self.youtube_channel and node.findtext(YOUTUBE + "channelId") != self.youtube_channel:
                    raise ValueError()
            except (ValueError, TypeError):
                invalid += 1
                continue
            identity = str(identity).strip()
            if not identity or len(identity) > 2048 or identity in seen:
                if not identity:
                    invalid += 1
                continue
            seen.add(identity)
            identities.append(identity)
            summary = text(raw)[:2000]
            title = text(title) or summary.split("\n", 1)[0][:160]
            if not title:
                invalid += 1
                continue
            if not relevant_announcement(title + " " + summary):
                continue
            data = {"summary": summary[:1000], "published_at": published_date(published),
                    "availability_verified": False, "region": "GLOBAL",
                    "provenance": "official" if self.official else "secondary",
                    "evidence": [title[:300]], "format": "Atom" if atom else "RSS"}
            # Store an explicitly linked primary article, but never follow it automatically.
            urls = re.findall(r'https?://[^\s<>"\)]+', raw)
            primary = referenced_announcement(urls)
            if primary:
                data["announcement_url"] = primary
            thumbnail = node.find(MEDIA + "group/" + MEDIA + "thumbnail")
            if self.youtube_channel and thumbnail is not None:
                image = thumbnail.get("url", "")
                try:
                    image = safe_url(image)
                    if urlsplit(image).scheme == "https" and (urlsplit(image).hostname or "").endswith(".ytimg.com"):
                        data.update(image_url=image, image_verified=True)
                except ValueError:
                    pass
            items.append(Item(id=identity, source=self.id, title=title, url=link,
                              kind="announcement", state="ANNOUNCED", data=data,
                              content=(title + "\n" + summary)[:4000]))
        if entries and invalid == len(entries):
            raise ExtractionError("Feed sin entradas válidas; se conserva el estado")
        metadata = {"method": "Atom" if atom else "RSS", "bootstrap_ids": identities,
                    "errors": ["feed:invalid_entry"] * min(invalid, 20), "entries": len(entries)}
        return FetchResult(items[:self.max_items], not_modified=not items, metadata=metadata)

    async def fetch(self, http) -> FetchResult:
        return self.parse(await http.get(self.url))
