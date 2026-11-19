"""Read-only operator inspection and explicitly requested Discord previews.

No Store instance, model request, source fetch, delivery queue or schema migration
is involved. Sending a preview is a separate, single HTTP operation.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

from .models import Event, safe_url
from .notifications import discord_payload
from .profiles import TCG_LABELS, event_profile, normalize_tcg, source_scope_enabled
from .rules import RuleEngine

KINDS = ("announcement", "article", "event", "product")


class InspectionError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


ERROR_MESSAGES = {
    "database_missing": "La base de datos todavía no existe. Espera a la primera comprobación del servicio.",
    "database_unreadable": "No se pudo leer la base de datos. Revisa la ruta, los permisos y el estado del servicio.",
    "webhook_missing": "Falta configurar DISCORD_WEBHOOK_URL o DISCORD_WEBHOOK_URL_FILE.",
}


def tcg_filter(value: str) -> str:
    normalized = normalize_tcg(value)
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,49}", normalized):
        raise ValueError("El TCG debe ser un nombre o identificador válido")
    return normalized


def select_events(settings, *, tcg: str | None = None, kind: str | None = None, source: str | None = None, limit: int = 10) -> list[Event]:
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("El límite debe estar entre 1 y 100")
    if kind is not None and kind not in KINDS:
        raise ValueError("Tipo de elemento no admitido")
    if source is not None and (not isinstance(source, str) or not source.strip()):
        raise ValueError("Fuente no válida")
    tcg = tcg_filter(tcg) if tcg is not None else None
    try:
        path = Path(settings.database_path).resolve()
        if not path.is_file():
            raise InspectionError("database_missing")
    except OSError:
        raise InspectionError("database_unreadable") from None
    engine, selected = RuleEngine(settings.rules), []
    enabled_tcgs = {normalize_tcg(value) for value in settings.enabled_tcgs}
    try:
        db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=5)
        try:
            db.execute("PRAGMA query_only=ON")
            # Sort small row identities, not all retained article/model bodies.
            # Payloads are read one at a time, until enough matching events exist.
            rows = db.execute("SELECT rowid FROM events WHERE payload IS NOT NULL ORDER BY created DESC,rowid DESC")
            for (rowid,) in rows:
                raw = db.execute("SELECT payload FROM events WHERE rowid=?", (rowid,)).fetchone()
                if raw is None or raw[0] is None:
                    continue
                try:
                    event = Event(**json.loads(raw[0]))
                    if source is not None and event.source != source:
                        continue
                    current = event.data["current"]
                    if not isinstance(current, dict):
                        continue
                    cfg = settings.sources.get(event.source)
                    if not isinstance(cfg, dict) or not cfg.get("enabled", True):
                        continue
                    if not source_scope_enabled(event.source, current, cfg):
                        continue
                    profile = event_profile(current, event.source)
                    game = profile.get("tcg")
                    if game is not None and game not in enabled_tcgs:
                        continue
                    if tcg is not None and game != tcg:
                        continue
                    if kind is not None and current.get("kind") != kind:
                        continue
                    decision = engine.decide(event)
                    if not decision.notify or (decision.require_analysis and not event.analysis):
                        continue
                    # An invalid historical URL must not become a preview link.
                    event.url = safe_url(event.url)
                except (ValueError, TypeError, KeyError, AttributeError):
                    continue
                selected.append(event)
                if len(selected) >= limit:
                    break
        finally:
            db.close()
    except sqlite3.Error:
        raise InspectionError("database_unreadable") from None
    return selected


def event_record(event: Event) -> dict:
    profile = event_profile(event.data["current"], event.source)
    game = profile.get("tcg")
    return {"title": event.title, "tcg": game, "game": TCG_LABELS.get(game, game or "Sin TCG asignado"),
            "source": event.source, "occurred_at": event.occurred_at,
            "event_type": event.event_type, "kind": event.data["current"].get("kind"), "url": event.url}


def _console_text(value, limit=2000):
    return re.sub(r"[\x00-\x1f\x7f\u202a-\u202e\u2066-\u2069]", " ", str(value))[:limit]


def format_events(events: list[Event], timezone: str) -> str:
    if not events:
        return "No hay alertas guardadas que coincidan con estos filtros y las reglas actuales."
    lines = []
    for event in events:
        record = event_record(event)
        try:
            instant = datetime.fromisoformat(event.occurred_at)
            date = instant.astimezone(ZoneInfo(timezone)).strftime("%d/%m/%Y %H:%M %Z") if instant.tzinfo else event.occurred_at
        except (TypeError, ValueError):
            date = event.occurred_at
        lines.extend([f"{_console_text(record['game'])} · {_console_text(date)}",
                      _console_text(record["title"]),
                      f"Fuente: {_console_text(event.source)} · Evento: {_console_text(event.event_type)}",
                      _console_text(record["url"]), ""])
    return "\n".join(lines).rstrip()


def preview_payload(event: Event, timezone: str) -> dict:
    payload = discord_payload(event, timezone)
    payload["content"] = "🧪 VISTA PREVIA MANUAL · Evento guardado con su fecha original."
    return payload


@dataclass(frozen=True)
class PreviewDelivery:
    sent: bool
    http_status: int | None = None
    retry_after: float | None = None
    error: str | None = None


def _retry_delay(body: bytes, headers) -> float:
    try:
        value = json.loads(body).get("retry_after", headers.get("Retry-After", 1))
        delay = float(value)
    except (ValueError, TypeError, AttributeError):
        try:
            delay = float(headers.get("Retry-After", 60))
        except (ValueError, TypeError):
            delay = 60
    return max(1, min(delay, 86400)) if math.isfinite(delay) else 60


async def send_preview(settings, payload: dict, *, client: httpx.AsyncClient | None = None) -> PreviewDelivery:
    if not settings.discord_webhook_url:
        raise InspectionError("webhook_missing")
    # Never let debug logging print the configured webhook URL.
    logging.getLogger("httpx").setLevel(logging.CRITICAL)
    logging.getLogger("httpcore").setLevel(logging.CRITICAL)
    if client is None:
        async with httpx.AsyncClient(limits=httpx.Limits(max_connections=1), follow_redirects=False) as owned:
            return await send_preview(settings, payload, client=owned)
    timeout = min(30, settings.http_timeout_seconds)
    try:
        async with asyncio.timeout(timeout):
            async with client.stream("POST", settings.discord_webhook_url, params={"wait": "true"},
                                     json=payload, timeout=timeout, follow_redirects=False) as response:
                status = response.status_code
                if status in (200, 204):
                    return PreviewDelivery(True, http_status=status)
                if status == 429:
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(body) + len(chunk) > 32768:
                            break
                        body.extend(chunk)
                    return PreviewDelivery(False, http_status=status, retry_after=_retry_delay(body, response.headers))
                return PreviewDelivery(False, http_status=status)
    except (httpx.HTTPError, TimeoutError) as exc:
        return PreviewDelivery(False, error=type(exc).__name__)


async def inspect_command(settings, command: str, *, tcg=None, kind=None, source=None, limit=10, send=False, as_json=False) -> int:
    try:
        events = select_events(settings, tcg=tcg, kind=kind, source=source, limit=1 if command == "preview" else limit)
        if command == "events":
            print(json.dumps([event_record(event) for event in events], ensure_ascii=False, indent=2)
                  if as_json else format_events(events, settings.timezone))
            return 0
        if not events:
            print("Todavía no hay alertas guardadas que coincidan con estos filtros y las reglas actuales.")
            return 1
        payload = preview_payload(events[0], settings.timezone)
        if not send:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0
        outcome = await send_preview(settings, payload)
        if outcome.sent:
            print("Vista previa enviada a Discord. La base de datos y la cola conservan su estado.")
            return 0
        if outcome.http_status == 429:
            print(f"Discord limita los envíos. Espera al menos {outcome.retry_after:g} segundos antes de repetir.")
        elif outcome.http_status is not None:
            print(f"Discord devolvió HTTP {outcome.http_status}. Revisa el webhook y su configuración.")
        else:
            print(f"No se pudo confirmar el envío ({outcome.error}). Comprueba el canal antes de repetir.")
        return 1
    except InspectionError as exc:
        print(ERROR_MESSAGES.get(exc.code, "No se pudo completar la consulta."))
        return 2
