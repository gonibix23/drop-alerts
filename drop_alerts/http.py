"""Bounded HTTP source transport, with persistent conditional response caching."""
from __future__ import annotations

import asyncio
import math
import time
from collections import OrderedDict
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx

from .models import ExtractionError, safe_url


class SourceHTTP:
    def __init__(self, client: httpx.AsyncClient, store: Any = None,
                 max_bytes: int = 2_000_000, retries: int = 1,
                 min_request_interval: float = 0.25, timeout: float = 20):
        self.client, self.store = client, store
        self.max_bytes, self.retries = max_bytes, retries
        self.min_request_interval = min_request_interval
        self.timeout = timeout
        self._cache: OrderedDict[str, dict] = OrderedDict()
        self._last_request: dict[str, float] = {}
        self._cooldowns: dict[str, float] = {}

    async def get(self, url: str) -> str:
        try:
            # A slowly trickling body cannot hold the worker forever.
            async with asyncio.timeout(self.timeout * (self.retries + 1)):
                return await self._get(url)
        except TimeoutError:
            raise ExtractionError("Tiempo total de consulta agotado") from None

    async def _get(self, url: str, redirects: int = 0) -> str:
        url = safe_url(url)
        cached = self.store.get_http_cache(url) if self.store else self._cache.get(url)
        headers = {"User-Agent": "drop-alerts/1.0 (self-hosted source monitoring)"}
        if cached:
            if cached.get("etag"):
                headers["If-None-Match"] = cached["etag"]
            if cached.get("last_modified"):
                headers["If-Modified-Since"] = cached["last_modified"]
        host = urlsplit(url).netloc
        cooldown_key = "http_cooldown:" + host
        until = self.store.get_meta(cooldown_key, 0) if self.store and hasattr(self.store, "get_meta") else self._cooldowns.get(host, 0)
        if float(until) > time.time():
            raise ExtractionError("Fuente en pausa por límite de frecuencia")
        for attempt in range(self.retries + 1):
            delay = self.min_request_interval - (time.monotonic() - self._last_request.get(host, 0))
            if delay > 0:
                await asyncio.sleep(delay)
            self._last_request[host] = time.monotonic()
            try:
                # Follow only bounded same-origin redirects, checked before each request.
                async with self.client.stream("GET", url, headers=headers, follow_redirects=False,
                                              timeout=self.timeout) as response:
                    if response.status_code in (301, 302, 303, 307, 308):
                        destination = safe_url(urljoin(url, response.headers.get("Location", "")))
                        old_parts, new_parts = urlsplit(url), urlsplit(destination)
                        if redirects >= 3 or (new_parts.scheme, new_parts.netloc) != (old_parts.scheme, old_parts.netloc):
                            raise ExtractionError("Redirección de fuente no permitida")
                        return await self._get(destination, redirects + 1)
                    if response.status_code == 304:
                        if cached and isinstance(cached.get("body"), str):
                            return cached["body"]
                        raise ExtractionError("Respuesta 304 sin contenido previo")
                    if response.status_code in (429, 503):
                        retry = response.headers.get("Retry-After", "1")
                        try:
                            delay = float(retry)
                            delay = max(1, min(delay, 86400)) if math.isfinite(delay) else 60
                        except ValueError:
                            try:
                                retry_at = parsedate_to_datetime(retry)
                                if retry_at.tzinfo is None:
                                    retry_at = retry_at.replace(tzinfo=timezone.utc)
                                delay = max(1, (retry_at - datetime.now(timezone.utc)).total_seconds())
                            except (ValueError, TypeError):
                                delay = 2 ** attempt
                        delay = max(1, min(delay, 86400)) if math.isfinite(delay) else 60
                        until = time.time() + delay
                        self._cooldowns[host] = until
                        if self.store and hasattr(self.store, "set_meta"):
                            self.store.set_meta(cooldown_key, until)
                        if delay > 30 or attempt >= self.retries:
                            raise ExtractionError(f"Fuente HTTP {response.status_code}; pausa solicitada por el servidor")
                        await asyncio.sleep(delay)
                        continue
                    if response.status_code in (500, 502, 504) and attempt < self.retries:
                        await asyncio.sleep(2 ** attempt)
                        continue
                    response.raise_for_status()
                    content_type = response.headers.get("Content-Type", "").lower()
                    if content_type and not any(x in content_type for x in ("html", "json", "xml", "text/")):
                        raise ExtractionError("Tipo de respuesta inesperado")
                    chunks, size = [], 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > self.max_bytes:
                            raise ExtractionError("Respuesta de fuente demasiado grande")
                        chunks.append(chunk)
                    body = b"".join(chunks).decode(response.encoding or "utf-8", errors="replace")
                    record = {"body": body, "etag": response.headers.get("ETag"),
                              "last_modified": response.headers.get("Last-Modified")}
                    # Cache is transport data, never an accepted source snapshot.
                    # An invalid cached response still fails parsing on the next 304.
                    if self.store:
                        self.store.set_http_cache(url, **record)
                    else:
                        self._cache[url] = record
                        while len(self._cache) > 128:
                            self._cache.popitem(last=False)
                    return body
            except httpx.TransportError:
                if attempt >= self.retries:
                    raise ExtractionError("Error de red al consultar la fuente") from None
                await asyncio.sleep(2 ** attempt)
            except httpx.HTTPStatusError as exc:
                raise ExtractionError(f"Fuente HTTP {exc.response.status_code}") from None
        raise ExtractionError("Consulta agotada")
