"""Tournament dates are distinct from product release and shipping dates."""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, model_validator


class EventSchedule(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    start_at: str | None
    end_at: str | None
    start_date: str | None
    timezone: str | None
    certainty: Literal["explicit", "estimated", "unknown"]
    evidence: list[str] = Field(max_length=6)
    note: str = Field(default="", max_length=300)

    @model_validator(mode="after")
    def valid_calendar(self):
        if self.timezone:
            ZoneInfo(self.timezone)
        if self.start_date:
            date.fromisoformat(self.start_date)
        for value in (self.start_at, self.end_at):
            if value:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    raise ValueError("Evento con hora sin zona")
        if self.end_at and not self.start_at:
            raise ValueError("Final sin comienzo")
        if self.start_at and self.end_at and datetime.fromisoformat(self.end_at.replace("Z", "+00:00")) < datetime.fromisoformat(self.start_at.replace("Z", "+00:00")):
            raise ValueError("Final anterior al comienzo")
        if (self.start_at or self.start_date) and (not self.evidence or self.certainty == "unknown"):
            raise ValueError("Fecha sin evidencia")
        if self.start_at and self.start_date and datetime.fromisoformat(self.start_at.replace("Z", "+00:00")).date().isoformat() != self.start_date:
            raise ValueError("Día y hora no concuerdan")
        return self


def normalize_event_schedule(start: str | None, end: str | None = None, venue_timezone: str | None = None) -> dict:
    result = {"start_at": None, "end_at": None, "start_date": None, "timezone": None,
              "certainty": "unknown", "evidence": [], "note": "Fecha del evento por confirmar."}
    if not isinstance(start, str) or not start.strip():
        return result
    start = start.strip()
    try:
        if len(start) == 10:
            day = date.fromisoformat(start)
            result.update(start_date=day.isoformat(), certainty="explicit", evidence=[start], note="Hora por confirmar.")
        else:
            instant = datetime.fromisoformat(start.replace("Z", "+00:00"))
            estimated = instant.tzinfo is None
            if estimated:
                if not venue_timezone:
                    return result
                origin = ZoneInfo(venue_timezone)
                aware = instant.replace(tzinfo=origin)
                if (aware.astimezone(timezone.utc).astimezone(origin).replace(tzinfo=None) != instant
                        or aware.utcoffset() != instant.replace(tzinfo=origin, fold=1).utcoffset()):
                    return result
                instant = aware
            result.update(start_at=instant.isoformat(), start_date=instant.date().isoformat(),
                          timezone=venue_timezone, certainty="estimated" if estimated else "explicit",
                          evidence=[start], note="Zona deducida de la ubicación del local." if estimated else "")
            if isinstance(end, str) and end.strip():
                try:
                    finish = datetime.fromisoformat(end.strip().replace("Z", "+00:00"))
                except ValueError:
                    finish = None
                if finish is not None and finish.tzinfo is None:
                    if venue_timezone:
                        end_zone = ZoneInfo(venue_timezone)
                        local_end = finish
                        aware_end = local_end.replace(tzinfo=end_zone)
                        if (aware_end.astimezone(timezone.utc).astimezone(end_zone).replace(tzinfo=None) != local_end
                                or aware_end.utcoffset() != local_end.replace(tzinfo=end_zone, fold=1).utcoffset()):
                            finish = None
                        else:
                            finish = aware_end
                    else:
                        finish = None
                if finish is not None and finish.tzinfo is not None and finish >= instant:
                    result.update(end_at=finish.isoformat(), evidence=[start, end.strip()])
        return EventSchedule.model_validate(result).model_dump(mode="json")
    except (ValueError, TypeError, KeyError, OverflowError):
        return {**result, "start_at": None, "end_at": None, "start_date": None, "timezone": None,
                "certainty": "unknown", "evidence": [], "note": "Fecha del evento por confirmar."}


def validated_event_schedule(current: dict) -> dict | None:
    data = current.get("data", {})
    schedule = data.get("event_schedule") if isinstance(data, dict) else None
    if not isinstance(schedule, dict):
        return None
    try:
        result = EventSchedule.model_validate(schedule).model_dump(mode="json")
    except (ValueError, TypeError, KeyError):
        return None
    content = str(current.get("content", ""))
    if any(quote not in content for quote in result["evidence"]):
        return None
    return result


def event_schedule_identity(current: dict) -> tuple | None:
    schedule = validated_event_schedule(current)
    if not schedule or schedule["certainty"] == "unknown":
        return None
    if schedule["start_at"]:
        start = datetime.fromisoformat(schedule["start_at"].replace("Z", "+00:00")).astimezone(timezone.utc).isoformat()
        end = datetime.fromisoformat(schedule["end_at"].replace("Z", "+00:00")).astimezone(timezone.utc).isoformat() if schedule["end_at"] else None
        return ("datetime", start, end)
    return ("date", schedule["start_date"])


def event_schedule_changed(previous: dict, current: dict) -> bool:
    old, new = validated_event_schedule(previous), validated_event_schedule(current)
    if not old or not new or old["certainty"] == "unknown" or new["certainty"] == "unknown":
        return False
    if old["start_at"] and new["start_at"]:
        before = datetime.fromisoformat(old["start_at"].replace("Z", "+00:00"))
        after = datetime.fromisoformat(new["start_at"].replace("Z", "+00:00"))
        if before != after:
            return True
    elif old["start_date"] and new["start_date"] and old["start_date"] != new["start_date"]:
        return True
    if old["end_at"] and new["end_at"]:
        return datetime.fromisoformat(old["end_at"].replace("Z", "+00:00")) != datetime.fromisoformat(new["end_at"].replace("Z", "+00:00"))
    # Missing details are uncertainty, never a categorical reschedule.
    return False
