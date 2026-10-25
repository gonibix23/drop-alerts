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
        elif host == "en.onepiece-cardgame.com":
            valid = re.fullmatch(r"/(?:products|topics|news|events|information)/(?:[^/]+/)*[^/]+\.(?:html|php)", path) or re.fullmatch(r"/events/\d{4}/[^/]+", path)
        elif host in ("www.pokemon.com", "pokemon.com"):
            valid = re.fullmatch(r"/(?:es|us)/(?:noticias-pokemon|pokemon-news|noticias|news|jcc-pokemon/galeria-de-productos|pokemon-tcg/product-gallery)/[^/]+", path)
            host = "www.pokemon.com"
        elif host == "pokemon.gamespress.com":
            valid = re.fullmatch(r"/es/[^/]+", path)
        elif host == "www.pokemon-card.com":
            valid = re.fullmatch(r"/info/\d{4}/\d{2}/[^/]+\.html", path)
        else:
            return None
        return urlunsplit(("https", host, path, "", "")) if valid else None
    except (ValueError, TypeError):
        return None


def referenced_announcement(urls) -> str | None:
    candidates = {canonical for url in urls if isinstance(url, str) and (canonical := announcement_url(url))}
    # Multiple different articles are a roundup, not one announcement identity.
    return next(iter(candidates)) if len(candidates) == 1 else None


def event_reference_url(value: str) -> str | None:
    try:
        parts = urlsplit(value)
        if parts.scheme != "https" or parts.username or parts.password or parts.port not in (None, 443):
            return None
        host, path = (parts.hostname or "").lower(), parts.path.rstrip("/")
        if host in ("www.bandai-tcg-plus.com", "bandai-tcg-plus.com", "locator.wizards.com"):
            valid = re.fullmatch(r"/event/\d+", path)
            host = "www.bandai-tcg-plus.com" if "bandai" in host else host
        elif host == "localbatoru.com":
            valid = re.fullmatch(r"/event/[A-Za-z0-9_-]+", path)
        else:
            return None
        return urlunsplit(("https", host, path, "", "")) if valid else None
    except (ValueError, TypeError):
        return None
