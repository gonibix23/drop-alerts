"""Conservative identities shared by announcements that link the same primary article."""
from __future__ import annotations

import re
from urllib.parse import urlsplit, urlunsplit


def announcement_url(value: str) -> str | None:
    """Accept individual official articles, never a storefront, listing or model URL."""
    try:
        parts = urlsplit(value)
        if parts.scheme != "https" or parts.username or parts.password or parts.port not in (None, 443):
            return None
        host = (parts.hostname or "").lower()
        path = parts.path.rstrip("/")
        if host in ("magic.wizards.com", "www.magic.wizards.com"):
            valid = re.fullmatch(r"/en/news/[^/]+/[^/]+", path)
            host = "magic.wizards.com"
        elif host == "wpn.wizards.com":
            valid = re.fullmatch(r"/en/news/[^/]+", path)
        elif host == "www.mtgfestivals.com":
            valid = re.fullmatch(r"/global/en-us/magiccon-news/\d{4}/[^/]+\.html", path)
        else:
            return None
        return urlunsplit(("https", host, path, "", "")) if valid else None
    except (ValueError, TypeError):
        return None


def referenced_announcement(urls) -> str | None:
    candidates = {canonical for url in urls if isinstance(url, str) and (canonical := announcement_url(url))}
    # Multiple different articles are a roundup, not one announcement identity.
    return next(iter(candidates)) if len(candidates) == 1 else None
