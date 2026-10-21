"""Evidence-bound date enrichment, independent from crawling and notification IO."""
from __future__ import annotations

import re
from dataclasses import asdict
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from .models import Item
from .release_dates import ReleaseSchedule, extract_release_schedule, corroborate_release_quote

SCHEDULE_VERSION = "1"


def source_text(current: dict) -> str:
    data = current.get("data", {})
    return (str(current.get("title", "")) + "\n" + str(current.get("content") or data.get("summary", "")))[:16000]


def effective_release_schedule(current: dict, analysis: dict | None = None) -> dict:
    """Revalidate source text even for legacy events or a proposed model excerpt.

    A model can focus attention on an excerpt, never provide an ISO date itself.
    Existing deterministic dates and contradictions always take precedence.
    """
    content = source_text(current)
    published = current.get("data", {}).get("published_at")
    base = ReleaseSchedule.model_validate(extract_release_schedule(content, published)).model_dump(mode="json")
    if base["date"] or base["certainty"] == "conflicting" or not isinstance(analysis, dict) or analysis.get("task") != "release_schedule":
        return base
    result = analysis.get("result")
    if not isinstance(result, dict):
        return base
    # Reapply strict task validation for stored or manually supplied event payloads.
    from .ai.client import InvalidAnalysis, parse_result
    from .models import canonical_json
    try:
        result = parse_result("release_schedule", canonical_json(result), content)
    except (InvalidAnalysis, ValueError, TypeError):
        return base
    quote = result.get("date_quote")
    if not quote or quote not in content:
        return base
    # The parser retains semantic headings, negation and logistics qualifiers;
    # a model-picked substring must not erase the context before a date.
    proposal = ReleaseSchedule.model_validate(corroborate_release_quote(content, quote, published, date_kind=result["date_kind"])).model_dump(mode="json")
    if (not proposal["date"] or proposal["certainty"] in ("unknown", "conflicting")
            or proposal["date_kind"] != result["date_kind"]):
        return base
    proposal.update(certainty="estimated", engine="model", note="Interpretación orientativa de un fragmento del anuncio; consulta la fuente.")
    return ReleaseSchedule.model_validate(proposal).model_dump(mode="json")


def enrich_item(item: Item) -> None:
    if item.kind not in ("article", "announcement", "product", "collection"):
        return
    item.data["release_schedule"] = effective_release_schedule(asdict(item))
    item.data["release_schedule_version"] = SCHEDULE_VERSION


def should_analyze_schedule(item: Item) -> bool:
    """Use one existing analysis slot only when source dates need interpretation."""
    if item.kind not in ("article", "announcement"):
        return False
    schedule = item.data.get("release_schedule", {})
    if schedule.get("certainty") != "unknown":
        return False
    # A model cannot turn "coming soon" into a date or fill an absent year.
    content = source_text(asdict(item))
    concrete = list(re.finditer(r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?|enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)\s+\d{1,2}|\d{1,2}\s+(?:de\s+)?(?:enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)|\b\d{4}-\d{2}-\d{2}\b|\btomorrow\b|\bmañana\b", content, re.I))[:8]
    commercial_context = re.search(r"\bon sale\b|\bavailable\b|\blaunch|\breleas|\barriv|\bpre[ -]?order|\bcoming\b|\bout (?:on )?|\ba la venta\b|\blanza|\bdisponib|\bpreventa\b|\breservas?\b|\bpurchas|\bbuy\b|\bordering\b|\bcheckout\b|\bcompra|\badquirir\b", content, re.I)
    anchor = item.data.get("published_at")
    explicit_year = re.search(r"\b20\d{2}\b", content)
    if not concrete or not commercial_context or not (anchor or explicit_year):
        return False
    # Do not hold an alert for a date that even a valid semantic selection could
    # not normalize (shipping, negation, an absent year, etc.).
    return any(corroborate_release_quote(content, match.group(), anchor, date_kind="sale").get("date") for match in concrete)


def schedule_identity(schedule: dict) -> tuple | None:
    """Only normalized dates with evidence participate in deterministic changes."""
    if not schedule.get("date") or schedule.get("certainty") in ("unknown", "conflicting"):
        return None
    day, clock, zone = (schedule.get(key) for key in ("date", "time", "timezone"))
    if clock and zone:
        try:
            local = datetime.fromisoformat(f"{day}T{clock}")
            origin = ZoneInfo(zone)
            aware = local.replace(tzinfo=origin)
            unambiguous = aware.utcoffset() == local.replace(tzinfo=origin, fold=1).utcoffset()
            if unambiguous and aware.astimezone(timezone.utc).astimezone(origin).replace(tzinfo=None) == local:
                return ("instant", aware.astimezone(timezone.utc).isoformat(), schedule.get("end_date"))
        except (ValueError, TypeError, KeyError):
            pass
    return ("local", day, clock, zone, schedule.get("end_date"))
