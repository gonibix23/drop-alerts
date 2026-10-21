"""Evidence-based sale/release dates. No current-year or commercial-state guesses."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date as Date, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ReleaseSchedule(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    date: Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}$")] | None
    time: Annotated[str, Field(pattern=r"^\d{2}:\d{2}$")] | None
    timezone: Annotated[str, Field(min_length=1, max_length=80)] | None
    end_date: Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}$")] | None
    certainty: Literal["explicit", "estimated", "unknown", "conflicting"]
    date_kind: Literal["sale", "preorder", "release", "unknown"]
    evidence: Annotated[list[Annotated[str, Field(min_length=1, max_length=500)]], Field(max_length=4)]
    note: Annotated[str, Field(max_length=300)]
    engine: Literal["deterministic", "model"]
    year_inferred: bool

    @field_validator("date", "end_date")
    @classmethod
    def calendar_date(cls, value):
        if value is not None:
            Date.fromisoformat(value)
        return value

    @field_validator("time")
    @classmethod
    def clock_time(cls, value):
        if value is not None and not (0 <= int(value[:2]) <= 23 and 0 <= int(value[3:]) <= 59):
            raise ValueError("Hora inválida")
        return value

    @field_validator("timezone")
    @classmethod
    def known_timezone(cls, value):
        if value is not None:
            try:
                ZoneInfo(value)
            except (ZoneInfoNotFoundError, ValueError):
                raise ValueError("Zona horaria inválida") from None
        return value

    @model_validator(mode="after")
    def consistent(self):
        if self.date is None and any((self.time, self.timezone, self.end_date)):
            raise ValueError("Hora o ventana sin fecha")
        if self.date and self.end_date and self.end_date < self.date:
            raise ValueError("Ventana temporal invertida")
        if self.certainty in ("unknown", "conflicting") and self.date is not None:
            raise ValueError("Fecha categórica con resultado incierto")
        if self.certainty == "explicit" and self.date is None:
            raise ValueError("Resultado explícito sin fecha")
        if self.date is not None and self.date_kind == "unknown":
            raise ValueError("Fecha sin identificar su significado")
        if self.year_inferred and self.certainty != "estimated":
            raise ValueError("Un año inferido necesita incertidumbre explícita")
        if self.date is not None and not self.evidence:
            raise ValueError("Fecha sin evidencia")
        return self


MONTHS = {
    "january": 1, "jan": 1, "enero": 1, "ene": 1,
    "february": 2, "feb": 2, "febrero": 2,
    "march": 3, "mar": 3, "marzo": 3,
    "april": 4, "apr": 4, "abril": 4, "abr": 4,
    "may": 5, "mayo": 5,
    "june": 6, "jun": 6, "junio": 6,
    "july": 7, "jul": 7, "julio": 7,
    "august": 8, "aug": 8, "agosto": 8, "ago": 8,
    "september": 9, "sept": 9, "sep": 9, "septiembre": 9, "setiembre": 9,
    "october": 10, "oct": 10, "octubre": 10,
    "november": 11, "nov": 11, "noviembre": 11,
    "december": 12, "dec": 12, "diciembre": 12, "dic": 12,
}
MONTH = "(?:" + "|".join(sorted(MONTHS, key=len, reverse=True)) + ")"
ABSOLUTE = re.compile(
    r"\b(?:(?P<iso>20\d{2}-\d{2}-\d{2})|"
    r"(?P<m1>" + MONTH + r")\.?\s+(?P<d1>\d{1,2})(?:st|nd|rd|th)?(?:\s*,?\s*(?P<y1>20\d{2}))?|"
    r"(?P<d2>\d{1,2})(?:st|nd|rd|th)?\s+(?:de\s+)?(?P<m2>" + MONTH + r")\.?(?:\s+(?:de\s+)?(?P<y2>20\d{2}))?)\b", re.I)
SALE = re.compile(r"\bon\s+sale\b|\bsales?\s+(?:begin|start|open)|\bsale\s+(?:window|date)\b|\bfecha\s+de\s+venta\b|\b(?:available|availability|available\s+to\s+order)\b|(?<!pre-)(?<!pre )\border(?:ing|s)?\s+(?:open|begin|start)|\ba\s+la\s+venta\b|\bdisponible\b|\bventa(?:s)?\s+(?:empieza|comienza|abre)", re.I)
PREORDER = re.compile(r"\bpre[ -]?order(?:s|ing)?\b|\bpreventa\b|\breservas?\s+(?:abre|comienza|empieza)", re.I)
RELEASE = re.compile(r"\blaunch(?:es|ing)?\b|\breleas(?:e|es|ing)\b|\barriv(?:e|es|ing)\b|\bcoming(?:\s+to)?\b|\bdrop\s+date\b|\b(?:drop|superdrop|kit|collection|product)\s+(?:(?:is|comes|will\s+be)\s+)?out\s+(?:on\s+)?|(?:^|[—–:])\s*out\s+(?:on\s+)?|\blanzamiento\b|\bse\s+lanza\b|\bllega\b|\bsale\s+el\b|\bsaldr[aá]\b", re.I)
EXCLUDED = re.compile(r"\bship(?:s|ped|ping)?\b|\bfulfil(?:lment|ment)\b|\bdeliver(?:y|ies|ed)?\b|\blegal(?:ity)?\b|\bformats?\b|\bprerelease\s+events?\b|\bsold\s+out\b|\bagotad[oa]\b|\bpublished\b|\bpublication\b|\bposted\b|\bupdated\b|\benv[ií]o\b|\bentrega\b|\blegalidad\b|\bpublicad[oa]\b|\bpublicaci[oó]n\b|\bactualizad[oa]\b|\bconvenci[oó]n\b|\bconvention\b", re.I)
TENTATIVE = re.compile(r"\bexpected\b|\bestimat(?:ed|e)\b|\btentative\b|\bapproximately\b|\baround\b|\bmight\b|\bmay\s+(?:arrive|release|launch|be)\b|\bestimad[oa]\b|\baproximad[oa]\b|\bpodr[ií]a\b|\bprevist[oa]\b", re.I)
BOUND = re.compile(r"\b(?:shortly\s+)?(?:after|before|following|until)\b|\bdespu[eé]s\s+de\b|\bantes\s+de\b|\bhasta\b", re.I)
NEGATED = re.compile(r"\bnot\b|\bno\s+longer\b|\bno\s+(?:estar[aá]|saldr[aá]|se\s+lanza|disponible|a\s+la\s+venta)|\bcancel(?:led|ed)?\b|\bcancelad[oa]\b", re.I)
HISTORICAL = re.compile(r"\boriginally\b|\bpreviously\b|\binitially\b|\boriginalmente\b|\banteriormente\b", re.I)
CORRECTED = re.compile(r"\bnow\b|\binstead\b|\brescheduled\b|\bahora\b|\breprogramad[oa]\b", re.I)
RELATIVE = re.compile(r"\b(?:tomorrow|today|ma[ñn]ana|hoy)\b", re.I)
UNSAFE_INSTRUCTION = re.compile(r"\b(?:ignore|disregard|obey)\b.{0,70}\b(?:instructions?|rules?|prompts?)\b|\b(?:system(?:\s+prompt)?|instructions?|pretend|override|commands?|execute|configuration|configuraci[oó]n|ejecuta|instrucciones|assistant|reveal\s+secrets?|return\s+json|output\s+json)\b|\b(?:set|use|return|output)\b.{0,30}\b(?:release_date|date_kind|date)\b", re.I)
DELAYED = re.compile(r"\bdelay(?:ed|s)?\b|\bpostponed\b|\bretrasad[oa]\b|\baplazad[oa]\b", re.I)
CORROBORATION_EXCLUDED = re.compile(r"\b(?:birthday|anniversary|cumplea[ñn]os|aniversario|convention|convenci[oó]n|tournament|torneo|historical|hist[oó]rico|celebration|celebraci[oó]n|event\s+date|fecha\s+del\s+evento)\b", re.I)
TIME = re.compile(r"(?<!\d)(?P<h>\d{1,2})(?::(?P<m>\d{2}))?\s*(?P<ampm>a\.?\s*m\.?|p\.?\s*m\.?)?(?:\s*(?P<tz>Pacific(?:\s+Time)?|Eastern(?:\s+Time)?|PT|PST|PDT|ET|EST|EDT|UTC|GMT|CET|CEST|hora\s+peninsular|Europe/Madrid))?(?!\w)", re.I)
TZ = {"pt": "America/Los_Angeles", "pacific": "America/Los_Angeles", "pacific time": "America/Los_Angeles",
      "pst": "Etc/GMT+8", "pdt": "Etc/GMT+7", "et": "America/New_York", "eastern": "America/New_York", "eastern time": "America/New_York",
      "est": "Etc/GMT+5", "edt": "Etc/GMT+4", "utc": "UTC", "gmt": "Etc/GMT", "cet": "Etc/GMT-1", "cest": "Etc/GMT-2",
      "hora peninsular": "Europe/Madrid", "europe/madrid": "Europe/Madrid"}


@dataclass
class _Candidate:
    date: Date | None
    end: Date | None
    time: str | None
    zone: str | None
    kind: str
    certainty: str
    evidence: str
    inferred: bool
    note: str = ""


def _unknown(note="No se ha encontrado una fecha de venta o lanzamiento verificable.", *, evidence=None, certainty="unknown", kind="unknown"):
    return ReleaseSchedule(date=None, time=None, timezone=None, end_date=None, certainty=certainty,
                           date_kind=kind, evidence=evidence or [], note=note, engine="deterministic", year_inferred=False).model_dump()


def _publication(value, zone=None) -> Date | None:
    if not isinstance(value, str) or not value.strip():
        return None
    value = value.strip()
    try:
        instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return instant.astimezone(ZoneInfo(zone)).date() if zone and instant.tzinfo else instant.date()
    except ValueError:
        pass
    try:
        instant = parsedate_to_datetime(value)
        return instant.astimezone(ZoneInfo(zone)).date() if zone and instant.tzinfo else instant.date()
    except (ValueError, TypeError, OverflowError):
        pass
    found = list(ABSOLUTE.finditer(value))
    if len(found) == 1 and found[0].start() <= 10:
        month, day, year = _parts(found[0])
        if year:
            try:
                return Date(year, month, day)
            except ValueError:
                pass
    return None


def _parts(match):
    if match.group("iso"):
        year, month, day = map(int, match.group("iso").split("-"))
        return month, day, year
    return MONTHS[(match.group("m1") or match.group("m2")).lower()], int(match.group("d1") or match.group("d2")), int(match.group("y1") or match.group("y2")) if match.group("y1") or match.group("y2") else None


def _resolve(month, day, year, publication):
    inferred = year is None
    if inferred:
        if publication is None:
            return None, False
        year = publication.year
        # A late-year announcement for January/February crosses a calendar year.
        if publication.month >= 10 and month <= 2:
            year += 1
    try:
        return Date(year, month, day), inferred
    except (ValueError, TypeError):
        return None, inferred


def _kind(segment, start, end):
    before, after = segment[:start], segment[end:]
    markers = []
    for pattern, kind in ((SALE, "sale"), (PREORDER, "preorder"), (RELEASE, "release"), (EXCLUDED, "excluded")):
        matches = list(pattern.finditer(before))
        if matches and start - matches[-1].end() <= 180:
            markers.append((matches[-1].end(), kind, matches[-1].start()))
    if markers:
        _, kind, cue_start = max(markers)
        excluded = list(EXCLUDED.finditer(before))
        if kind != "excluded" and excluded and excluded[-1].end() < cue_start:
            subject = before[excluded[-1].end():cue_start]
            # "shipping is available" and "cards legal and available for play"
            # describe that non-sale subject, even though available is nearer.
            if not re.search(r"\b(?:drop|superdrop|product|collection|kit|bundle|secret\s+lair)\b", subject, re.I):
                kind = "excluded"
        return kind, before[-180:]
    # English often writes "October 23 release date" after the date itself.
    following = []
    for pattern, kind in ((EXCLUDED, "excluded"), (SALE, "sale"), (PREORDER, "preorder"), (RELEASE, "release")):
        match = pattern.search(after[:180])
        if match:
            following.append((match.start(), kind))
    if following:
        _, kind = min(following)
        return kind, before[-180:]
    return None, before[-80:]


def _clock(segment, date_start, date_end):
    found = []
    for match in TIME.finditer(segment):
        if match.start() < date_end and match.end() > date_start:
            continue
        if re.search(r"(?:UTC|GMT)\s*[+-]\s*$", segment[max(0, match.start() - 10):match.start()], re.I):
            continue
        # A bare day/year or "24 hours" is never an opening time.
        if not (match.group("ampm") or match.group("m") or match.group("tz")):
            continue
        distance = min(abs(match.start() - date_end), abs(match.end() - date_start))
        if distance > 75:
            continue
        hour, minute = int(match.group("h")), int(match.group("m") or 0)
        ampm = re.sub(r"[.\s]", "", match.group("ampm") or "").lower()
        if minute > 59 or (ampm and not 1 <= hour <= 12) or (not ampm and hour > 23):
            continue
        if ampm:
            hour = hour % 12 + (12 if ampm == "pm" else 0)
        raw_zone = " ".join((match.group("tz") or "").lower().split())
        zone = TZ.get(raw_zone)
        # UTC/GMT followed by a numeric offset is not the zero-offset zone.
        # Keep the announced clock time, but do not convert unsupported offsets.
        if raw_zone in ("utc", "gmt") and re.match(r"\s*[+-]\s*\d", segment[match.end():]):
            zone = None
        found.append((distance, f"{hour:02}:{minute:02}", zone))
    return min(found, default=(0, None, None))[1:]


def _segments(content):
    masked = re.sub(r"\b[ap]\.\s*m\.", lambda match: match.group().replace(".", "·"), content, flags=re.I)
    start = 0
    for match in re.finditer(r"[\n!?;]|\.(?=\s+[A-ZÁÉÍÓÚ])", masked):
        fragment = content[start:match.end()].strip()
        # Preserve a short semantic heading with a date on its following line.
        if match.group() == "\n" and len(fragment) <= 200 and not ABSOLUTE.search(fragment) and any(pattern.search(fragment) for pattern in (SALE, PREORDER, RELEASE, EXCLUDED, NEGATED, UNSAFE_INSTRUCTION, CORROBORATION_EXCLUDED, DELAYED)):
            continue
        yield fragment
        start = match.end()
    yield content[start:].strip()


def has_temporal_hint(content: str) -> bool:
    """Select ambiguous date-bearing inputs for optional semantic interpretation."""
    if not isinstance(content, str):
        return False
    content = content[:24000]
    unambiguous_months = "|".join(month for month in MONTHS if month != "may")
    return bool(ABSOLUTE.search(content) or RELATIVE.search(content)
                or re.search(r"\b(?:" + unambiguous_months + r")\b|\bin\s+May\b|\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b", content, re.I))


def corroborate_release_quote(content: str, quote: str, published_at: str | None = None,
                              date_kind: Literal["sale", "preorder", "release"] | None = None) -> dict:
    """Check a literal quote in its full original semantic segment, never alone.

    An optional model-proposed relationship may classify an otherwise unknown
    short segment. Its single literal date is still normalised in code and the
    result is always estimated. It cannot bypass a negative original context.
    """
    if (not isinstance(content, str) or not isinstance(quote, str) or not quote.strip()
            or len(quote) > 500 or quote not in content[:24000]):
        return _unknown("La cita no es un fragmento literal verificable del contenido.")
    segments = [segment for segment in _segments(content[:24000]) if quote in segment]
    if not segments:
        return _unknown("La cita cruza contextos distintos y no permite corroborar una fecha.")
    if any(any(pattern.search(segment) for pattern in (EXCLUDED, NEGATED, BOUND, HISTORICAL, UNSAFE_INSTRUCTION, CORROBORATION_EXCLUDED, DELAYED)) for segment in segments):
        return _unknown("El contexto original contiene exclusiones o instrucciones que impiden corroborar una salida.")
    results = []
    for segment in segments:
        result = extract_release_schedule(segment, published_at)
        if result["certainty"] == "unknown" and date_kind in ("sale", "preorder", "release") and len(segment) <= 1000:
            matches = list(ABSOLUTE.finditer(segment))
            if len(matches) == 1:
                match = matches[0]
                month, day, year = _parts(match)
                value, inferred = _resolve(month, day, year, _publication(published_at))
                if value:
                    clock, zone = _clock(segment, match.start(), match.end())
                    left, right = max(0, match.start() - 170), min(len(segment), match.end() + 75)
                    result = ReleaseSchedule(date=value.isoformat(), time=clock, timezone=zone, end_date=None,
                        certainty="estimated", date_kind=date_kind, evidence=[segment[left:right]],
                        note="Relación con la salida propuesta por IA; fecha literal comprobada en el texto.",
                        engine="model", year_inferred=inferred).model_dump()
        results.append(result)
    if any(result["date"] is None for result in results):
        return _unknown("El contexto original de la cita no acredita una fecha de venta o lanzamiento.")
    facts = {(result["date"], result["end_date"], result["time"], result["timezone"], result["date_kind"]) for result in results}
    if len(facts) != 1:
        return _unknown("La cita aparece en contextos incompatibles; requiere revisión.")
    best = min(results, key=lambda result: result["certainty"] != "explicit")
    return {**best, "evidence": list(dict.fromkeys(quote for result in results for quote in result["evidence"]))[:4]}


def extract_release_schedule(content: str, published_at: str | None = None) -> dict:
    """Extract only dates attached to sale/preorder/release language in the input.

    A publication anchor may supply an omitted year, always marked estimated.
    The wall clock and observation time are deliberately never consulted.
    """
    if not isinstance(content, str) or not content.strip():
        return _unknown()
    publication = _publication(published_at)
    candidates, unclear = [], []
    for segment in _segments(content[:24000]):
        if not segment:
            continue
        matches = list(ABSOLUTE.finditer(segment))[:40]
        consumed = set()
        for index, match in enumerate(matches):
            if index in consumed:
                continue
            kind, cue = _kind(segment, match.start(), match.end())
            if kind is None or kind == "excluded":
                continue
            if NEGATED.search(cue[-65:]):
                continue
            old, corrected = list(HISTORICAL.finditer(cue)), list(CORRECTED.finditer(cue))
            if old and (not corrected or corrected[-1].end() < old[-1].end()):
                continue
            month, day, year = _parts(match)
            endpoint, end_match = None, None
            if index + 1 < len(matches):
                following = matches[index + 1]
                between = segment[match.end():following.start()]
                if re.fullmatch(r"\s*(?:[–—-]|to|through|until|hasta|al|a)\s*", between, re.I):
                    end_month, end_day, end_year = _parts(following)
                    # A year at the end of a written date range applies to both ends.
                    if year is None and end_year is not None:
                        year = end_year - (1 if month > end_month else 0)
                    value, inferred = _resolve(month, day, year, publication)
                    endpoint, endpoint_inferred = _resolve(end_month, end_day, end_year or (value.year + (end_month < month) if value else None), publication)
                    inferred = inferred or endpoint_inferred
                    end_match = following
                    consumed.add(index + 1)
                else:
                    value, inferred = _resolve(month, day, year, publication)
            else:
                value, inferred = _resolve(month, day, year, publication)
            if end_match is None:
                # Same-month range: "November 2–9, 2026".
                short = re.match(r"\s*[–—-]\s*(\d{1,2})(?:\s*,?\s*(20\d{2}))?\b", segment[match.end():])
                if short:
                    range_year = int(short.group(2)) if short.group(2) else year
                    value, inferred = _resolve(month, day, range_year, publication)
                    try:
                        endpoint = Date(value.year, month, int(short.group(1))) if value else None
                    except ValueError:
                        endpoint = None
            if value is None:
                unclear.append(segment[:500])
                continue
            if endpoint and endpoint < value:
                unclear.append(segment[:500])
                continue
            local_context = cue[-100:] + segment[match.start():min(len(segment), (end_match.end() if end_match else match.end()) + 35)]
            if BOUND.search(cue[-60:]):
                unclear.append(segment[:500])
                continue
            clock, zone = _clock(segment, match.start(), end_match.end() if end_match else match.end())
            estimated = inferred or bool(TENTATIVE.search(local_context))
            note = "Año inferido de la fecha de publicación." if inferred else ""
            if clock and not zone:
                note = (note + " Zona horaria sin determinar.").strip()
            evidence_start = max(0, match.start() - 170)
            evidence_end = min(len(segment), max(match.end(), end_match.end() if end_match else 0) + 75)
            candidates.append(_Candidate(value, endpoint, clock, zone, kind, "estimated" if estimated else "explicit",
                                         segment[evidence_start:evidence_end][:500], inferred, note))
        for match in RELATIVE.finditer(segment):
            kind, cue = _kind(segment, match.start(), match.end())
            if kind is None or kind == "excluded" or NEGATED.search(cue[-65:]):
                continue
            if publication is None:
                unclear.append(segment[:500])
                continue
            offset = 1 if match.group().lower() in ("tomorrow", "mañana", "manana") else 0
            clock, zone = _clock(segment, match.start(), match.end())
            anchor = _publication(published_at, zone) if zone else publication
            value = anchor + timedelta(days=offset)
            candidates.append(_Candidate(value, None, clock, zone, kind, "estimated", segment[:500], False,
                                         "Fecha relativa calculada desde la publicación; requiere confirmar el contexto horario."))
    if not candidates:
        return _unknown("La fuente no permite fijar un día exacto con seguridad." if unclear else "No se ha encontrado una fecha de venta o lanzamiento verificable.", evidence=list(dict.fromkeys(unclear))[:2])
    rank = {"sale": 0, "preorder": 1, "release": 2}
    priority = min(rank[candidate.kind] for candidate in candidates)
    preferred = [candidate for candidate in candidates if rank[candidate.kind] == priority]
    dates = {candidate.date for candidate in preferred}
    ends = {candidate.end for candidate in preferred if candidate.end}
    if len(dates) > 1 or len(ends) > 1:
        return _unknown("La fuente contiene fechas incompatibles para el mismo tipo de salida; consulta el anuncio.",
                        evidence=list(dict.fromkeys(candidate.evidence for candidate in preferred))[:4], certainty="conflicting", kind=preferred[0].kind)
    clocks = {candidate.time for candidate in preferred if candidate.time}
    zones = {candidate.zone for candidate in preferred if candidate.zone}
    if len(clocks) > 1 or len(zones) > 1:
        return _unknown("La fuente contiene horas incompatibles; consulta el anuncio.",
                        evidence=list(dict.fromkeys(candidate.evidence for candidate in preferred))[:4], certainty="conflicting", kind=preferred[0].kind)
    best = min(preferred, key=lambda candidate: (candidate.certainty != "explicit", candidate.time is None, candidate.zone is None))
    return ReleaseSchedule(date=best.date.isoformat(), time=next(iter(clocks), None), timezone=next(iter(zones), None),
                           end_date=next(iter(ends)).isoformat() if ends else None,
                           certainty=best.certainty, date_kind=best.kind,
                           evidence=list(dict.fromkeys(candidate.evidence for candidate in preferred))[:4],
                           note=best.note, engine="deterministic", year_inferred=best.inferred).model_dump()
