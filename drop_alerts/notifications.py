from __future__ import annotations

import asyncio
import json
import random
import re
import time
from datetime import date, datetime, timezone as datetime_timezone
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx

from .models import Event, safe_url
from .profiles import TCG_LABELS


class DeliveryError(Exception):
    def __init__(self, code: str, retry_after: float = 0, permanent: bool = False):
        super().__init__(code)
        self.code, self.retry_after, self.permanent = code, retry_after, permanent


SOURCE_LABELS = {
    "secret_lair_eu": "Secret Lair · Tienda EU",
    "chaos_vault_eu": "Secret Lair · Chaos Vault EU",
    "secret_lair_bluesky": "Secret Lair · Bluesky oficial",
    "magic_news": "Magic · Noticias oficiales",
    "wpn_news": "WPN · Noticias para tiendas",
    "magiccon_news": "MagicCon · Noticias oficiales",
    "weekly_mtg": "WeeklyMTG · YouTube oficial",
    "magicspoiler": "MagicSpoiler · Medio complementario",
    "mtggoldfish": "MTGGoldfish · Medio complementario",
    "mtgdrops": "MTGDrops · Calendario complementario",
    "scg_news": "Star City Games · Medio complementario",
    "one_piece_news": "One Piece · Noticias oficiales",
    "one_piece_products": "One Piece · Catálogo oficial",
    "one_piece_topics": "One Piece · Anuncios oficiales",
    "one_piece_jp_news": "One Piece · Noticias oficiales de Japón",
    "one_piece_jp_products": "One Piece · Catálogo oficial de Japón",
    "pokemon_news": "Pokémon · Noticias oficiales",
    "pokemon_news_es": "Pokémon · Noticias oficiales en español",
    "pokemon_products": "Pokémon TCG · Catálogo oficial",
    "pokemon_tcg_products": "Pokémon TCG · Catálogo oficial",
    "pokemon_jp_news": "Pokémon · Noticias oficiales de Japón",
    "pokemon_products_es": "Pokémon TCG · Galería oficial en español",
    "pokemon_tcg_news_es": "Pokémon TCG · Noticias oficiales en español",
    "pokemon_press_es": "Pokémon · Prensa oficial en español",
    "pokemon_products_us": "Pokémon TCG · Galería oficial de Estados Unidos",
    "pokemon_news_jp": "Pokémon Card Game · Noticias oficiales de Japón",
    "local_tcg_events": "dondejugarTCG · Alcalá y Torrejón",
    "local_tcg_events_madrid": "dondejugarTCG · Madrid y alrededores",
    "mundicomics_events": "Mundicomics · Eventos",
    "gladius_events": "Gladius · Eventos",
    "nextdice_events": "Next Dice · Eventos",
    "arte9_events": "Arte 9 · Eventos",
    "ludoteca_events": "Ludoteca Maldita · Eventos",
    "jupiter_guadalajara_events": "Júpiter Guadalajara · Eventos",
    "tabletop_gamers": "Tabletop Gamers · Tienda online",
    "jjcollection": "JJ Collection · Tienda online",
}
TCG_COLORS = {"one_piece": 0xE75B56, "pokemon": 0xF2C94C}
REGION_LABELS = {"EU": "Europa", "ES": "España", "US": "Estados Unidos", "NA": "Norteamérica",
                 "UK": "Reino Unido", "GB": "Reino Unido", "JP": "Japón", "GLOBAL": "Internacional",
                 "global": "Internacional", "WESTERN": "Occidente · incluye Europa",
                 "OC": "Oceanía", "LATAM": "Latinoamérica", "ME": "Oriente Medio"}
LANGUAGE_LABELS = {"en": "Inglés", "es": "Español", "ja": "Japonés", "jp": "Japonés",
                   "fr": "Francés", "de": "Alemán", "it": "Italiano", "pt": "Portugués"}
CHANNEL_LABELS = {"online": "Venta online", "retail": "Tiendas", "event": "Evento / presencial",
                  "catalog": "Catálogo", "catalogue": "Catálogo", "news": "Noticias y anuncios",
                  "editorial": "Noticias y anuncios", "social": "Red social", "video": "Vídeo",
                  "promotion": "Promoción", "promo": "Promoción", "announcement": "Anuncio",
                  "local_event": "Evento local"}
EVENT_STYLES = {
    "announcement.new": ("📣", "Nuevo anuncio", 0x9B6DFF),
    "publication.new": ("📰", "Nueva publicación", 0x60A5FA),
    "product.new": ("✨", "Nuevo producto", 0x34D399),
    "collection.new": ("🗂️", "Nueva colección", 0x2DD4BF),
    "availability.changed": ("🔔", "Cambio de disponibilidad", 0x34D399),
    "price.changed": ("💶", "Cambio de precio", 0xFBBF24),
    "release_date.changed": ("🗓️", "Cambio de fecha", 0xFBBF24),
    "content.changed": ("📝", "Información actualizada", 0x60A5FA),
    "change.uncertain": ("🔎", "Cambio pendiente de confirmar", 0xF59E0B),
    "event.new": ("📅", "Nuevo evento", 0x60A5FA),
    "event.schedule_changed": ("🗓️", "Cambio de horario", 0xFBBF24),
    "event.cancelled": ("🚫", "Evento cancelado", 0xF87171),
    "event.updated": ("📝", "Evento actualizado", 0x60A5FA),
}
STATE_LABELS = {"ANNOUNCED": "Anunciado", "UPCOMING": "Próximamente", "AVAILABLE": "Disponible",
                "UNAVAILABLE": "No disponible", "UNKNOWN": "Sin confirmar", "SCHEDULED": "Programado",
                "CANCELLED": "Cancelado", "POSTPONED": "Aplazado", "RESCHEDULED": "Reprogramado", "ONGOING": "En curso",
                "COMPLETED": "Finalizado", "REGISTRATION_OPEN": "Inscripción abierta",
                "REGISTRATION_CLOSED": "Inscripción cerrada"}


def _units(value: str) -> int:
    # A conservative UTF-16 budget also covers Discord clients' string lengths.
    return len(value.encode("utf-16-le")) // 2


def _clip(value: str, limit: int) -> str:
    if _units(value) <= limit:
        return value
    if limit <= 0:
        return ""
    result, used = [], 0
    for character in value:
        length = _units(character)
        if used + length > limit - 1:
            break
        result.append(character)
        used += length
    return "".join(result).rstrip() + "…"


def _discord_text(value, limit: int) -> str:
    # Source text is data: it must not become a ping, masked link or Markdown UI.
    value = re.sub(r"[\x00-\x1f\x7f\u202a-\u202e\u2066-\u2069]", " ", str(value or ""))
    value = " ".join(value.split()).replace("@", "@\u200b")
    value = re.sub(r"([\\`*_~|\[\]()<>#])", r"\\\1", value)
    return _clip(value, limit)


def _http_url(value) -> str | None:
    if not isinstance(value, str) or len(value) > 2048 or any(character.isspace() or ord(character) < 32 for character in value):
        return None
    try:
        return safe_url(value)
    except ValueError:
        return None


def _price(item: dict | None) -> str | None:
    if not item:
        return None
    data = item.get("data", {})
    # Old persisted adapters predate the flag; explicit unverified data is hidden.
    if data.get("price_verified") is False or not re.fullmatch(r"[A-Z]{3}", str(data.get("currency", ""))):
        return None
    try:
        price = Decimal(str(data.get("price")))
        if not price.is_finite() or price < 0 or price > Decimal("1000000000") or price.as_tuple().exponent < -8:
            return None
    except (InvalidOperation, ValueError):
        return None
    return f"{format(price, 'f')} {data['currency']}"


def _state(item: dict | None) -> str | None:
    if not item:
        return None
    state, data = item.get("state", "UNKNOWN"), item.get("data", {})
    editorial = item.get("kind") in ("article", "announcement")
    event = item.get("kind") == "event"
    if state == "UNKNOWN" or (data.get("availability_verified") is False and not event and not (editorial and state in ("ANNOUNCED", "UPCOMING"))):
        return None
    return STATE_LABELS.get(state, _discord_text(state, 100))


def _release_schedule_text(schedule: dict, target_timezone: str) -> str:
    """Display only the validated schedule supplied by the enrichment boundary."""
    certainty = schedule.get("certainty", "unknown")
    if certainty == "conflicting":
        return "Fechas contradictorias · consultar fuente"
    if certainty not in ("explicit", "estimated") or not schedule.get("date"):
        return "Sin fecha confirmada"
    try:
        day = date.fromisoformat(schedule["date"])
    except (ValueError, TypeError):
        return "Sin fecha confirmada"
    value = day.strftime("%d/%m/%Y")
    hour, origin = schedule.get("time"), schedule.get("timezone")
    if hour:
        try:
            if not isinstance(hour, str) or not re.fullmatch(r"\d{2}:\d{2}", hour):
                raise ValueError("Hora inválida")
            local = datetime.fromisoformat(f"{day.isoformat()}T{hour}")
            if origin:
                zone = ZoneInfo(origin)
                aware = local.replace(tzinfo=zone)
                # Skip nonexistent or ambiguous clock readings around DST changes.
                roundtrip = aware.astimezone(datetime_timezone.utc).astimezone(zone)
                ambiguous = aware.utcoffset() != local.replace(tzinfo=zone, fold=1).utcoffset()
                if roundtrip.replace(tzinfo=None) != local or ambiguous:
                    value += " · hora pendiente de confirmar"
                else:
                    converted = aware.astimezone(ZoneInfo(target_timezone))
                    place = "hora de Madrid" if target_timezone == "Europe/Madrid" else target_timezone
                    value = converted.strftime("%d/%m/%Y · %H:%M %Z") + " · " + place
            else:
                value += f" · {hour} (zona horaria no especificada)"
        except (ValueError, TypeError, ZoneInfoNotFoundError):
            value += " · hora pendiente de confirmar"
    else:
        value += " · hora sin confirmar"
    if schedule.get("end_date"):
        try:
            end = date.fromisoformat(schedule["end_date"])
            if end >= day:
                # A closing date has no implied time or timezone conversion.
                value += "\nHasta " + end.strftime("%d/%m/%Y")
                if origin:
                    place = {"America/Los_Angeles": "del Pacífico", "Europe/Madrid": "de Madrid", "UTC": "en UTC"}.get(origin, "en " + origin)
                    value += " · fecha " + place
                value += " · hora de cierre sin confirmar"
        except (ValueError, TypeError):
            pass
    if certainty == "estimated" or schedule.get("year_inferred") or schedule.get("engine") == "model":
        value = "Orientativa · " + value
        if schedule.get("year_inferred"):
            value += "\nAño inferido a partir del anuncio"
    return value


def _release_schedule_field(current: dict, previous: dict | None, analysis: dict | None, timezone: str, editorial: bool) -> dict | None:
    from .schedule_enrichment import effective_release_schedule

    schedule = effective_release_schedule(current, analysis)
    if not editorial and not schedule.get("date") and "release_schedule" not in current.get("data", {}):
        return None
    names = {"sale": "🗓️ Venta prevista", "preorder": "🗓️ Preventa prevista", "release": "🗓️ Lanzamiento previsto"}
    value = _release_schedule_text(schedule, timezone)
    if previous and schedule.get("date") and schedule.get("certainty") in ("explicit", "estimated"):
        old = effective_release_schedule(previous)
        keys = ("date", "time", "timezone", "end_date")
        if (old.get("date") and old.get("certainty") in ("explicit", "estimated")
                and any(old.get(key) != schedule.get(key) for key in keys)):
            value = _release_schedule_text(old, timezone) + "\n→ " + value
    return {"name": names.get(schedule.get("date_kind"), "🗓️ Lanzamiento previsto"),
            "value": _clip(value, 1024), "inline": False}


def _event_datetime(value, origin: str | None, target: str) -> tuple[str | None, datetime | None]:
    if not isinstance(value, str):
        return None, None
    try:
        instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if instant.tzinfo is None:
            if not origin:
                return instant.strftime("%d/%m/%Y · %H:%M") + " · zona horaria sin confirmar", None
            local, zone = instant, ZoneInfo(origin)
            instant = local.replace(tzinfo=zone)
            ambiguous = instant.utcoffset() != local.replace(tzinfo=zone, fold=1).utcoffset()
            if ambiguous or instant.astimezone(datetime_timezone.utc).astimezone(zone).replace(tzinfo=None) != local:
                return local.strftime("%d/%m/%Y") + " · hora pendiente de confirmar", None
        converted = instant.astimezone(ZoneInfo(target))
        place = "hora de Madrid" if target == "Europe/Madrid" else target
        return converted.strftime("%d/%m/%Y · %H:%M %Z") + " · " + place, instant
    except (ValueError, TypeError, OverflowError, ZoneInfoNotFoundError):
        return None, None


def _event_fields(current: dict, timezone: str) -> list[dict]:
    from .event_schedule import validated_event_schedule

    data = current.get("data", {})
    schedule = validated_event_schedule(current)
    fields = []
    value = None
    if schedule:
        value, start = _event_datetime(schedule.get("start_at"), schedule.get("timezone"), timezone)
        end_text, end = _event_datetime(schedule.get("end_at"), schedule.get("timezone"), timezone)
        if value and end_text and start and end and end >= start:
            value += "\nHasta " + end_text
        if not value and schedule.get("start_date"):
            try:
                value = date.fromisoformat(schedule["start_date"]).strftime("%d/%m/%Y") + " · hora sin confirmar"
            except (ValueError, TypeError):
                pass
        if value and schedule.get("certainty") == "estimated":
            value = "Orientativa · " + value
    if value:
        fields.append({"name": "📅 Fecha del evento", "value": _clip(value, 1024), "inline": False})
    else:
        period = data.get("event_period_text")
        content = str(current.get("content", "")) + "\n" + str(data.get("summary", ""))
        if isinstance(period, str) and period.strip() and period in content:
            fields.append({"name": "📅 Período publicado del evento", "value": _discord_text(period, 700), "inline": False})
        else:
            fields.append({"name": "📅 Fecha del evento", "value": "Fecha u horario por confirmar", "inline": False})
    location = []
    for key in ("venue", "address", "city"):
        value = data.get(key)
        if isinstance(value, str) and value.strip() and value not in location:
            location.append(value)
    if location:
        fields.append({"name": "📍 Lugar", "value": "\n".join(_discord_text(value, 300) for value in location)[:1024], "inline": False})
    if data.get("entry_price_verified") is True:
        price = _price({"data": {"price": data.get("entry_price"), "currency": data.get("entry_currency"), "price_verified": True}})
        if price:
            fields.append({"name": "🎟️ Inscripción", "value": price, "inline": True})
    return fields


def discord_payload(event: Event, timezone: str = "Europe/Madrid") -> dict:
    """Render source facts only; semantic analysis never supplies commercial claims."""
    current, previous = event.data["current"], event.data.get("previous")
    data = current.get("data", {})
    from .profiles import event_profile
    profile = event_profile(current, event.source)
    tcg = profile.get("tcg")
    is_event = current.get("kind") == "event" or event.event_type.startswith("event.")
    editorial = current.get("kind") in ("article", "announcement") or event.event_type in ("announcement.new", "publication.new") or is_event
    icon, label, color = EVENT_STYLES.get(event.event_type, ("🔔", event.event_type, 0x60A5FA))
    if event.event_type in ("announcement.new", "publication.new", "content.changed", "event.new", "event.updated"):
        color = TCG_COLORS.get(tcg, color)
    state = _state(current)
    uncertain = event.event_type == "change.uncertain" or (not editorial and state is None)
    result = event.analysis.get("result", {}) if event.analysis else {}
    uncertain = uncertain or result.get("needs_review") is True
    if uncertain:
        color = 0xF59E0B
    elif event.event_type == "availability.changed" and current.get("state") == "UNAVAILABLE":
        color = 0xF87171

    summary = _discord_text(data.get("summary"), 700)
    if not summary:
        summary = {"announcement.new": "La fuente ha publicado un anuncio. Consulta los detalles y las condiciones en el enlace.",
                   "publication.new": "Nueva publicación de la fuente. Consulta el artículo para conocer los detalles.",
                   "price.changed": "La fuente muestra un cambio en el precio del producto.",
                   "release_date.changed": "La fuente ha actualizado la fecha prevista. Consulta los detalles del anuncio.",
                   "availability.changed": "La fuente muestra un cambio en la disponibilidad del producto.",
                   "event.new": "La fuente ha anunciado un evento. Consulta la ubicación y las condiciones de participación.",
                   "event.schedule_changed": "La fuente ha actualizado el horario del evento.",
                   "event.cancelled": "La fuente indica que el evento ha sido cancelado.",
                   "event.updated": "La fuente ha actualizado la información del evento.",
                   "content.changed": "La fuente ha actualizado la información de este elemento."}.get(event.event_type, "Nuevo elemento detectado en la fuente.")
    if uncertain:
        summary += "\n\n🔎 Información o interpretación incierta; consulta la fuente antes de darla por confirmada."

    fields = []
    if tcg and tcg != "unknown":
        fields.append({"name": "🃏 Juego", "value": _discord_text(TCG_LABELS.get(tcg, tcg), 200), "inline": True})
    fields.append({"name": "📡 Fuente", "value": _discord_text(SOURCE_LABELS.get(event.source, event.source), 200), "inline": True})
    region = profile.get("region")
    if region:
        fields.append({"name": "🌍 Región", "value": _discord_text(REGION_LABELS.get(str(region), region), 100), "inline": True})
    language = profile.get("language")
    if language:
        fields.append({"name": "🌐 Idioma de la fuente", "value": _discord_text(LANGUAGE_LABELS.get(str(language), language), 100), "inline": True})
    channel = profile.get("channel")
    if channel:
        fields.append({"name": "🏷️ Canal", "value": _discord_text(CHANNEL_LABELS.get(str(channel), channel), 100), "inline": True})
    if state:
        old_state = _state(previous)
        value = f"{old_state} → {state}" if old_state and previous.get("state") != current.get("state") else state
        fields.append({"name": "📍 Estado" if editorial else "📦 Disponibilidad", "value": value, "inline": True})
    price = _price(current) if not is_event else None
    if price:
        old_price = _price(previous)
        if event.event_type == "price.changed" and old_price:
            price = f"{old_price} → {price}"
        fields.append({"name": "💶 Precio observado", "value": price, "inline": True})
    if is_event:
        fields.extend(_event_fields(current, timezone))
    else:
        release = _release_schedule_field(current, previous, event.analysis, timezone, editorial)
        if release:
            fields.append(release)
    try:
        instant = datetime.fromisoformat(event.occurred_at)
        if instant.tzinfo is None:
            raise ValueError("Fecha sin zona horaria")
        local = instant.astimezone(ZoneInfo(timezone)).strftime("%d/%m/%Y · %H:%M %Z")
        fields.append({"name": "🕒 Detectado", "value": local, "inline": True})
    except ValueError:
        instant = None
    if event.analysis:
        # Deliberately omit free-form model summaries, prices, URLs and categories.
        fields.append({"name": "🧠 Análisis semántico · sin verificar", "value": "Requiere revisión" if result.get("needs_review") else "Análisis orientativo disponible; los datos mostrados proceden de la fuente.", "inline": False})
    url = _http_url(event.url)
    if url:
        # Only the trusted adapter's event URL becomes a clickable Markdown link.
        link_url = url.replace("\\", "%5C").replace("(", "%28").replace(")", "%29").replace("<", "%3C").replace(">", "%3E")
        link = f"[Abrir {'evento' if is_event else 'anuncio' if editorial else 'fuente'} ↗](<{link_url}>)"
        fields.append({"name": "🔗 Detalles", "value": link if _units(link) <= 1024 else "Pulsa el título para consultar la fuente.", "inline": False})

    embed = {"author": {"name": _discord_text(f"{icon} {label}", 256)}, "title": _discord_text(event.title, 256) or "Nueva alerta",
             "description": _clip(summary, 4096), "color": color,
             "footer": {"text": "Drop Alerts · " + _discord_text(event.id, 12)}}
    if url:
        embed["url"] = url
    if instant:
        embed["timestamp"] = instant.isoformat()
    image_url = _http_url(data.get("image_url")) if data.get("image_verified") is True else None
    if image_url:
        embed["image"] = {"url": image_url}
    # Enforce the total embed budget after individual limits, including the author.
    remaining = 6000 - sum(_units(value) for value in (embed["author"]["name"], embed["title"], embed["description"], embed["footer"]["text"]))
    embed["fields"] = []
    for field in fields[:25]:
        name = _clip(field["name"], 256)
        limit = min(1024, remaining - _units(name))
        if limit < 1:
            break
        value = _clip(field["value"], limit)
        if value:
            embed["fields"].append({**field, "name": name, "value": value})
            remaining -= _units(name) + _units(value)
    return {"allowed_mentions": {"parse": [], "users": [], "roles": [], "replied_user": False}, "embeds": [embed]}


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

    def _configuration_allows(self, event: Event, rules) -> bool:
        from .profiles import SOURCE_PROFILES, event_profile, normalize_tcg

        cfg = self.settings.sources.get(event.source)
        if cfg is None:
            # Registered sources removed from the configuration are disabled.
            # Generic domains and third-party adapters keep their existing rules.
            if event.source in SOURCE_PROFILES:
                return False
        elif not isinstance(cfg, dict) or not cfg.get("enabled", True):
            return False
        game = event_profile(event.data["current"], event.source).get("tcg")
        if game is not None and game not in {normalize_tcg(value) for value in self.settings.enabled_tcgs}:
            return False
        decision = rules.decide(event)
        return decision.notify and (not decision.require_analysis or bool(event.analysis))

    async def tick(self):
        from .rules import RuleEngine

        if not getattr(self.channel, "enabled", True) or getattr(self.channel, "blocked_until", 0) > time.time():
            return
        rules = RuleEngine(self.settings.rules)
        remaining = self.settings.notification_batch_size
        # Disabled records do not consume HTTP slots or starve an allowed item
        # behind the first batch. Bound cleanup work when a large game is muted.
        scan_limit = max(100, remaining * 10)
        seen = set()
        while remaining and len(seen) < scan_limit:
            rows = self.store.due_notifications(min(remaining, scan_limit - len(seen)))
            if not rows:
                break
            progressed = False
            for event, attempts in rows:
                if event.id in seen:
                    continue
                if getattr(self.channel, "blocked_until", 0) > time.time():
                    return
                seen.add(event.id)
                progressed = True
                if not self._configuration_allows(event, rules):
                    self.store.notification_skipped(event.id, "configuration_disabled")
                    continue
                remaining -= 1
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
            if not progressed:
                break
