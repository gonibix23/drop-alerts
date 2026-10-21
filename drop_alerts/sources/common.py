from __future__ import annotations

import html
import json
import re
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from ..models import ExtractionError


def text(value: str) -> str:
    return " ".join(BeautifulSoup(html.unescape(str(value)), "html.parser").get_text(" ", strip=True).split())


def soup_from(body: str) -> BeautifulSoup:
    soup = BeautifulSoup(body, "html.parser")
    if not soup.find(["html", "main", "article", "script", "a"]):
        raise ExtractionError("HTML incompleto o no reconocido")
    if soup.title and any(x in soup.title.get_text().lower() for x in
                          ("access denied", "just a moment", "captcha")):
        raise ExtractionError("La fuente devolvió una página de bloqueo")
    return soup


def official_url(base: str, candidate: str) -> str | None:
    parts = urlsplit(urljoin(base, candidate))
    original = urlsplit(base)
    if parts.scheme != "https" or parts.netloc != original.netloc or parts.username or parts.password:
        return None
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def jsonld(soup: BeautifulSoup):
    def walk(value):
        if isinstance(value, list):
            for entry in value:
                yield from walk(entry)
        elif isinstance(value, dict):
            yield value
            if "@graph" in value:
                yield from walk(value["@graph"])
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            yield from walk(json.loads(script.string or script.get_text()))
        except (ValueError, TypeError):
            continue


def embedded_json_arrays(soup: BeautifulSoup, name: str):
    # Decode a JSON literal following the observed assignment. Never evaluate JavaScript.
    for script in soup.find_all("script"):
        script_text = script.string or script.get_text()
        for match in re.finditer(re.escape(name) + r"\s*=\s*", script_text):
            try:
                value, _ = json.JSONDecoder().raw_decode(script_text[match.end():])
                if isinstance(value, list):
                    yield from value
            except ValueError:
                continue
