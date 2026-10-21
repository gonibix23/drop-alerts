"""Official Secret Lair posts using the verified public Bluesky API and fixed DID."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from ..identities import referenced_announcement
from ..models import ExtractionError, FetchResult, Item, safe_url
from .feeds import published_date
from .relevance import relevant_announcement

SECRET_LAIR_DID = "did:plc:5a2wvprzfv3cej7fxud66twr"


@dataclass
class BlueskySource:
    id: str = "secret_lair_bluesky"
    did: str = SECRET_LAIR_DID
    max_items: int = 30

    @property
    def url(self):
        return "https://public.api.bsky.app/xrpc/app.bsky.feed.getAuthorFeed?actor=" + self.did + "&limit=30"

    def parse(self, body: str) -> FetchResult:
        try:
            payload = json.loads(body)
            feed = payload["feed"]
            if not isinstance(feed, list) or len(feed) > 100:
                raise ValueError()
        except (ValueError, TypeError, KeyError):
            raise ExtractionError("Respuesta Bluesky no reconocida") from None
        items, identities, invalid, seen = [], [], 0, set()
        for entry in feed:
            if not isinstance(entry, dict) or not isinstance(entry.get("post"), dict):
                invalid += 1
                continue
            post = entry["post"]
            # Reposts are not announcements authored by the approved official account.
            if entry.get("reason"):
                continue
            author = post.get("author")
            if not isinstance(author, dict) or author.get("did") != self.did:
                invalid += 1
                continue
            record, uri = post.get("record"), post.get("uri", "")
            if (not isinstance(record, dict) or not isinstance(record.get("text"), str) or not isinstance(uri, str)
                    or not re.fullmatch(re.escape("at://" + self.did + "/app.bsky.feed.post/") + r"[a-z0-9]+", uri)):
                invalid += 1
                continue
            if uri in seen:
                continue
            seen.add(uri)
            identities.append(uri)
            content = record["text"].strip()[:6000]
            links = []
            facets = record.get("facets", [])
            for facet in facets if isinstance(facets, list) else []:
                if not isinstance(facet, dict):
                    continue
                features = facet.get("features", [])
                for feature in features if isinstance(features, list) else []:
                    if isinstance(feature, dict) and feature.get("$type") == "app.bsky.richtext.facet#link":
                        links.append(feature.get("uri"))
            links += re.findall(r'https?://[^\s<>"\)]+', content)
            embed = post.get("embed")
            if isinstance(embed, dict) and isinstance(embed.get("external"), dict):
                links.append(embed["external"].get("uri"))
            primary = referenced_announcement(links)
            if not content or not (relevant_announcement(content) or primary):
                continue
            key = uri.rsplit("/", 1)[-1]
            title = content.split("\n", 1)[0][:160]
            data = {"summary": content[:1000], "published_at": published_date(record.get("createdAt")),
                    "author_did": self.did, "availability_verified": False, "region": "GLOBAL",
                    "provenance": "official", "evidence": [content[:300]]}
            if primary:
                data["announcement_url"] = primary
            if isinstance(embed, dict) and embed.get("$type") == "app.bsky.embed.images#view":
                images = embed.get("images", [])
                if isinstance(images, list) and images and isinstance(images[0], dict):
                    try:
                        candidate = images[0].get("thumb", "")
                        image = safe_url(candidate) if isinstance(candidate, str) else ""
                        if urlsplit(image).scheme == "https" and urlsplit(image).hostname == "cdn.bsky.app":
                            data.update(image_url=image, image_verified=True)
                    except ValueError:
                        pass
            items.append(Item(id=uri, source=self.id, title=title,
                              url=f"https://bsky.app/profile/{self.did}/post/{key}",
                              kind="announcement", state="ANNOUNCED", data=data, content=content))
        if feed and invalid == len(feed):
            raise ExtractionError("Publicaciones Bluesky inválidas")
        return FetchResult(items[:self.max_items], not_modified=not items,
                           metadata={"method": "public Bluesky API; fixed author DID", "bootstrap_ids": identities,
                                     "errors": ["bluesky:invalid_post"] * min(invalid, 20)})

    async def fetch(self, http) -> FetchResult:
        return self.parse(await http.get(self.url))
