from __future__ import annotations

from dataclasses import dataclass

from .models import Event


@dataclass(frozen=True)
class Decision:
    notify: bool
    require_analysis: bool = False


class RuleEngine:
    """An allow-list of independent OR rules; filters inside each rule are AND."""

    def __init__(self, rules: list[dict]):
        seen = set()
        allowed = {"id", "enabled", "sources", "kinds", "event_types", "keywords", "states", "require_analysis"}
        for rule in rules:
            if not isinstance(rule, dict) or set(rule) - allowed or not isinstance(rule.get("id"), str) or not rule["id"].strip() or rule["id"] in seen:
                raise ValueError("Regla inválida o identificador duplicado")
            seen.add(rule["id"])
            for key in ("enabled", "require_analysis"):
                if key in rule and type(rule[key]) is not bool:
                    raise ValueError(f"Regla: {key} debe ser booleano")
            for key in ("sources", "kinds", "event_types", "keywords", "states"):
                if key in rule and (not isinstance(rule[key], list) or any(not isinstance(x, str) or not x for x in rule[key])):
                    raise ValueError(f"Regla: {key} debe ser una lista de texto")
        self.rules = rules

    def decide(self, event: Event) -> Decision:
        matches = []
        for rule in self.rules:
            if not rule.get("enabled", True):
                continue
            values = {"sources": event.source, "kinds": event.data["current"]["kind"], "event_types": event.event_type, "states": event.data["current"]["state"]}
            if any(rule.get(key) and value not in rule[key] for key, value in values.items()):
                continue
            text = (event.title + " " + event.data["current"].get("content", "")).casefold()
            if rule.get("keywords") and not any(keyword.casefold() in text for keyword in rule["keywords"]):
                continue
            matches.append(rule)
        return Decision(bool(matches), bool(matches) and all(rule.get("require_analysis", False) for rule in matches))
