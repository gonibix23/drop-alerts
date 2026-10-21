"""Deterministic topic filter; never interprets a teaser as commercial availability."""
import re


SPECIAL_TOPICS = (
    "secret lair", "chaos vault", "superdrop", "doomsdrop", "festival in a box",
    "secret gallery", "secret lair roadshow", "mystery booster commander", "zeta set", "countdown kit",
)


def relevant_announcement(value: str) -> bool:
    normalized = re.sub(r"[\s\u2010-\u2015_-]+", " ", value.casefold())
    return any(topic in normalized for topic in SPECIAL_TOPICS) or bool(re.search(
        r"\b(?:exclusive|limited edition)\b.{0,60}\bpromo(?:tional)? cards?\b", normalized))
