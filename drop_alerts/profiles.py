"""Deterministic game/source identities. Language never establishes sales region."""
from __future__ import annotations

import re
import unicodedata


TCG_LABELS = {"magic": "Magic: The Gathering", "one_piece": "One Piece Card Game", "pokemon": "Pokémon TCG"}
ALIASES = {"mtg": "magic", "magic_the_gathering": "magic", "onepiece": "one_piece",
           "one_piece_card_game": "one_piece", "one_piece_tcg": "one_piece", "onepiecetcg": "one_piece",
           "pokemon_tcg": "pokemon", "pokemontcg": "pokemon", "jcc_pokemon": "pokemon"}


def normalized_name(value: str) -> str:
    value = unicodedata.normalize("NFKD", value.casefold())
    value = "".join(char for char in value if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", "_", value).strip("_")


def normalize_tcg(value: str) -> str:
    name = normalized_name(value)
    return ALIASES.get(name, name)


SOURCE_PROFILES = {
    "secret_lair_eu": {"tcg": "magic", "region": "EU", "language": "en", "channel": "online"},
    "chaos_vault_eu": {"tcg": "magic", "region": "EU", "language": "en", "channel": "online"},
    **{name: {"tcg": "magic", "region": "GLOBAL", "language": "en", "channel": "news"}
       for name in ("magic_news", "secret_lair_bluesky", "wpn_news", "weekly_mtg", "magicspoiler", "mtggoldfish", "mtgdrops", "scg_news")},
    "magiccon_news": {"tcg": "magic", "region": "GLOBAL", "language": "en", "channel": "event"},
    "one_piece_products": {"tcg": "one_piece", "region": "WESTERN", "language": "en", "channel": "online"},
    "one_piece_news": {"tcg": "one_piece", "region": "WESTERN", "language": "en", "channel": "news"},
    "pokemon_products_es": {"tcg": "pokemon", "region": "GLOBAL", "language": "es", "channel": "online"},
    "pokemon_tcg_news_es": {"tcg": "pokemon", "region": "GLOBAL", "language": "es", "channel": "news"},
    "pokemon_press_es": {"tcg": "pokemon", "region": "GLOBAL", "language": "es", "channel": "news"},
    "pokemon_products_us": {"tcg": "pokemon", "region": "US", "language": "en", "channel": "online"},
    "pokemon_news_jp": {"tcg": "pokemon", "region": "JP", "language": "ja", "channel": "news"},
    **{name: {"region": "EU", "language": "es", "channel": "event", "timezone": "Europe/Madrid", "tcgs": ["magic", "one_piece", "pokemon"]}
       for name in ("local_tcg_events", "local_tcg_events_madrid", "mundicomics_events", "gladius_events", "nextdice_events", "arte9_events", "ludoteca_events", "jupiter_guadalajara_events")},
}


def event_profile(current: dict, source: str | None = None) -> dict:
    source = source or current.get("source", "")
    profile = dict(SOURCE_PROFILES.get(source, {}))
    data = current.get("data", {})
    if not isinstance(data, dict):
        return profile
    for key in ("region", "language", "channel", "city", "country", "venue", "timezone"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            profile[key] = value[:160]
    # Single-game registered adapters cannot be relabelled by content or AI.
    if not profile.get("tcg") and isinstance(data.get("tcg"), str):
        name = normalize_tcg(data["tcg"])
        if re.fullmatch(r"[a-z][a-z0-9_]{0,49}", name):
            profile["tcg"] = name
    regions = data.get("regions")
    if isinstance(regions, list) and all(isinstance(value, str) and value for value in regions):
        profile["regions"] = list(dict.fromkeys(regions))[:12]
    if profile.get("region"):
        profile.setdefault("regions", [profile["region"]])
    return profile


def enrich_game(item) -> None:
    profile = event_profile({"source": item.source, "data": item.data})
    if profile.get("tcg"):
        item.data["tcg"] = profile["tcg"]


def game_enabled(current: dict, enabled_tcgs: list[str]) -> bool:
    game = event_profile(current).get("tcg")
    # Preserve generic non-TCG domains; filtering only applies to game-tagged data.
    return game is None or game in enabled_tcgs


def infer_event_tcg(value: str) -> str | None:
    """Only explicit game labels on a specific event, never navigation text."""
    text = normalized_name(value).replace("_", " ")
    matches = []
    for game, pattern in (("magic", r"\bmagic(?: the gathering)?\b|\bmtg\b"),
                          ("one_piece", r"\bone\s*piece\b"), ("pokemon", r"\bpokemon\b")):
        if re.search(pattern, text):
            matches.append(game)
    return matches[0] if len(matches) == 1 else None
