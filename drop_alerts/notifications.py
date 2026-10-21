from __future__ import annotations

import asyncio
import json
import random
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx

from .models import Event


class DeliveryError(Exception):
    def __init__(self, code: str, retry_after: float = 0, permanent: bool = False):
        super().__init__(code)
        self.code, self.retry_after, self.permanent = code, retry_after, permanent


def discord_payload(event: Event, timezone: str = "Europe/Madrid") -> dict:
    current, previous = event.data["current"], event.data.get("previous")
    labels = {"product.new": "Nuevo producto", "collection.new": "Nueva colección", "announcement.new": "Nuevo anuncio", "publication.new": "Nueva publicación", "availability.changed": "Cambio de disponibilidad", "price.changed": "Cambio de precio", "content.changed": "Información actualizada", "change.uncertain": "Cambio incierto"}
    fields = [{"name": "Evento", "value": labels.get(event.event_type, event.event_type)[:1024]}, {"name": "Fuente", "value": event.source[:1024]}]
    if previous and previous["state"] != current["state"]:
        fields.append({"name": "Estado", "value": f"{previous['state']} → {current['state']}"[:1024]})
    elif current["state"] != "UNKNOWN":
        fields.append({"name": "Estado observado", "value": current["state"][:1024]})
    if current["data"].get("price") is not None:
        price = f"{current['data']['price']} {current['data'].get('currency') or ''}".strip()
        if event.event_type == "price.changed" and previous and previous["data"].get("price") is not None:
            price = f"{previous['data']['price']} {previous['data'].get('currency') or ''} → {price}"
        fields.append({"name": "Precio observado", "value": price[:1024]})
    uncertain = current["state"] == "UNKNOWN" or event.event_type == "change.uncertain"
    if event.analysis:
        result = event.analysis["result"]
        uncertain = uncertain or result.get("needs_review", False)
        fields.append({"name": "Análisis semántico (sin verificar)", "value": ("Requiere revisión" if result.get("needs_review", False) else "Clasificación orientativa: " + result.get("category", event.analysis["task"]))[:1024]})
    description = "Cambio detectado en los datos de la fuente."
    if event.event_type.endswith(".new"):
        description = "La fuente ha publicado un nuevo elemento."
    if uncertain:
        description += " Disponibilidad o interpretación incierta; consulta el enlace oficial."
    local = datetime.fromisoformat(event.occurred_at).astimezone(ZoneInfo(timezone)).strftime("%d/%m/%Y %H:%M %Z")
    fields.append({"name": "Fecha", "value": local})
    return {"allowed_mentions": {"parse": [], "users": [], "roles": [], "replied_user": False}, "embeds": [{"title": event.title[:256], "url": event.url[:2048], "description": description, "fields": fields, "timestamp": event.occurred_at, "footer": {"text": "Drop Alerts · " + event.id[:16]}, "color": 0xF1C40F if uncertain else 0x3498DB}]}


class DiscordChannel:
    def __init__(self, settings, store, client: httpx.AsyncClient):
        self.settings, self.store, self.client = settings, store, client
        self.blocked_until = float(store.get_meta("discord_blocked_until") or 0)

    @property
    def enabled(self):
        return bool(self.settings.discord_webhook_url)

    def block(self, delay: float):
        self.blocked_until = max(self.blocked_until, time.time() + max(0, delay))
        self.store.set_meta("discord_blocked_until", str(self.blocked_until))

    async def send(self, event: Event):
        try:
            async with asyncio.timeout(self.settings.http_timeout_seconds):
                await self._send(event)
        except TimeoutError:
            raise DeliveryError("discord_network", 30) from None

    async def _send(self, event: Event):
        if not self.settings.discord_webhook_url:
            raise DeliveryError("webhook_not_configured", 300)
        if self.blocked_until > time.time():
            raise DeliveryError("discord_rate_limit", self.blocked_until - time.time())
        try:
            async with self.client.stream("POST", self.settings.discord_webhook_url, params={"wait": "true"}, json=discord_payload(event, self.settings.timezone), timeout=self.settings.http_timeout_seconds, follow_redirects=False) as response:
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > 32768:
                        raise DeliveryError("discord_response_too_large", 60)
                if response.status_code == 429:
                    try:
                        delay = float(json.loads(body).get("retry_after", 1))
                    except (ValueError, TypeError, AttributeError):
                        try:
                            delay = float(response.headers.get("retry-after", "1"))
                        except ValueError:
                            delay = 60
                    # Reject NaN/inf; a negative or huge server value must not busy-loop.
                    import math
                    delay = max(1, min(delay, 86400)) if math.isfinite(delay) else 60
                    self.block(delay)
                    raise DeliveryError("discord_429", delay)
                if response.status_code >= 500:
                    raise DeliveryError(f"discord_{response.status_code}", 60)
                if response.status_code not in (200, 204):
                    raise DeliveryError(f"discord_{response.status_code}", permanent=True)
                if response.headers.get("x-ratelimit-remaining") == "0":
                    try:
                        self.block(min(86400, max(1, float(response.headers.get("x-ratelimit-reset-after", "1")))))
                    except ValueError:
                        self.block(1)
        except httpx.HTTPError:
            raise DeliveryError("discord_network", 30) from None


class NotificationWorker:
    def __init__(self, settings, store, channel):
        self.settings, self.store, self.channel = settings, store, channel

    async def tick(self):
        if not getattr(self.channel, "enabled", True) or getattr(self.channel, "blocked_until", 0) > time.time():
            return
        for event, attempts in self.store.due_notifications(self.settings.notification_batch_size):
            if getattr(self.channel, "blocked_until", 0) > time.time():
                break
            try:
                await self.channel.send(event)
            except DeliveryError as exc:
                attempts += 1
                delay = max(exc.retry_after, min(21600, 5 * 2 ** min(attempts, 12))) + random.uniform(0, 1)
                self.store.notification_result(event.id, self.settings.notification_max_attempts if exc.permanent else attempts, exc.code, delay, self.settings.notification_max_attempts)
                self.store.diagnostic("discord", exc.code, "Entrega pendiente" if not exc.permanent else "Entrega rechazada")
            else:
                self.store.notification_result(event.id, attempts + 1)
            await asyncio.sleep(0.05)
