from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol
from urllib.parse import urlsplit, urlunsplit


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def fingerprint(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def safe_url(value: str) -> str:
    parts = urlsplit(value)
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password:
        raise ValueError("URL HTTP(S) inválida")
    return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ""))


@dataclass
class Item:
    id: str
    source: str
    title: str
    url: str
    kind: str = "unknown"
    state: str = "UNKNOWN"
    data: dict[str, Any] = field(default_factory=dict)
    content: str = ""
    observed_at: str = field(default_factory=utcnow)
    engine: str = "deterministic"

    def __post_init__(self) -> None:
        self.url = safe_url(self.url)
        if not self.id or not self.source or not self.title.strip():
            raise ValueError("Elemento sin identidad, fuente o título")

    @property
    def digest(self) -> str:
        value = {k: v for k, v in asdict(self).items() if k not in ("observed_at", "engine")}
        # Presentation/identity hints must not turn an adapter upgrade into an alert.
        value["data"] = {k: v for k, v in value["data"].items()
                         if k not in ("image_url", "image_verified", "announcement_url")}
        return fingerprint(value)


@dataclass
class FetchResult:
    items: list[Item]
    not_modified: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Event:
    id: str
    source: str
    item_id: str
    event_type: str
    occurred_at: str
    title: str
    url: str
    fingerprint: str
    data: dict[str, Any]
    analysis: dict[str, Any] | None = None


class SourceAdapter(Protocol):
    id: str

    async def fetch(self, http: Any) -> FetchResult: ...


class Analyzer(Protocol):
    async def analyze(self, task: str, content: str) -> dict[str, Any] | None: ...


class NotificationChannel(Protocol):
    async def send(self, event: Event) -> None: ...


class ExtractionError(Exception):
    """An invalid/incomplete source response must never replace stored state."""
