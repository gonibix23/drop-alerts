from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping
from zoneinfo import ZoneInfo

from .models import safe_url


def secret(env: Mapping[str, str], key: str) -> str:
    if env.get(key) and env.get(key + "_FILE"):
        raise ValueError(f"Configura {key} o {key}_FILE, solo uno")
    if env.get(key + "_FILE"):
        return Path(env[key + "_FILE"]).read_text(encoding="utf-8").strip()
    return env.get(key, "").strip()


@dataclass(repr=False)
class Settings:
    discord_webhook_url: str = ""
    poll_interval_seconds: int = 300
    timezone: str = "Europe/Madrid"
    bootstrap_mode: str = "silent"
    database_path: str = "data/drop-alerts.db"
    log_level: str = "INFO"
    heartbeat_path: str = "data/heartbeat.json"
    llm_enabled: bool = True
    llm_base_url: str = "https://llama.gonibix23.com/v1"
    llm_model: str = "qwen3:8b-q4_k_m"
    llm_api_key: str = ""
    llm_timeout_seconds: int = 45
    llm_max_retries: int = 1
    llm_temperature: float = 0.1
    llm_max_input_chars: int = 12000
    llm_cache_enabled: bool = True
    llm_max_output_tokens: int = 1200
    http_timeout_seconds: int = 20
    http_max_retries: int = 1
    max_pending_analyses: int = 100
    analyses_per_tick: int = 4
    analysis_max_attempts: int = 3
    notification_max_attempts: int = 12
    notification_batch_size: int = 10
    retention_days: int = 90
    source_max_bytes: int = 2000000
    source_max_items: int = 100
    sources: dict = field(default_factory=lambda: {"secret_lair_eu": {"enabled": True}, "magic_news": {"enabled": True}})
    rules: list[dict] = field(default_factory=lambda: [
        {"id": "store", "sources": ["secret_lair_eu"]},
        {"id": "secret-lair-news", "sources": ["magic_news"], "keywords": ["secret lair"]},
    ])

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Settings":
        env = os.environ if env is None else env
        result = cls()
        for name in result.__dataclass_fields__:
            if name in ("sources", "rules", "discord_webhook_url", "llm_api_key"):
                continue
            key = name.upper()
            if key not in env:
                continue
            value = env[key]
            default = getattr(result, name)
            if isinstance(default, bool):
                if value.lower() not in ("true", "false", "1", "0"):
                    raise ValueError(f"{key} debe ser true o false")
                value = value.lower() in ("true", "1")
            elif isinstance(default, int):
                value = int(value)
            elif isinstance(default, float):
                value = float(value)
            setattr(result, name, value)
        result.discord_webhook_url = secret(env, "DISCORD_WEBHOOK_URL")
        result.llm_api_key = secret(env, "LLM_API_KEY")
        if env.get("CONFIG_PATH"):
            with open(env["CONFIG_PATH"], "rb") as stream:
                config = tomllib.load(stream)
            if set(config) - {"sources", "rules"}:
                raise ValueError("Sección de configuración desconocida")
            result.sources = config.get("sources", result.sources)
            result.rules = config.get("rules", result.rules)
        result.validate()
        return result

    def validate(self) -> None:
        ZoneInfo(self.timezone)
        if self.bootstrap_mode not in ("silent", "notify"):
            raise ValueError("BOOTSTRAP_MODE debe ser silent o notify")
        if self.log_level not in ("DEBUG", "INFO", "WARNING", "ERROR"):
            raise ValueError("LOG_LEVEL inválido")
        bounds = {
            "poll_interval_seconds": (30, 86400), "llm_timeout_seconds": (1, 300),
            "llm_max_retries": (0, 1), "llm_max_input_chars": (100, 100000),
            "llm_max_output_tokens": (100, 8000), "http_timeout_seconds": (1, 120),
            "http_max_retries": (0, 3), "max_pending_analyses": (1, 10000),
            "analyses_per_tick": (1, 100), "analysis_max_attempts": (1, 10),
            "notification_max_attempts": (1, 100), "notification_batch_size": (1, 100),
            "retention_days": (1, 3650), "source_max_bytes": (10000, 10000000),
            "source_max_items": (1, 1000),
        }
        for key, (low, high) in bounds.items():
            if not low <= getattr(self, key) <= high:
                raise ValueError(f"{key.upper()} fuera de rango [{low}, {high}]")
        if not 0 <= self.llm_temperature <= 2 or not self.llm_model.strip():
            raise ValueError("Configuración LLM inválida")
        self.llm_base_url = safe_url(self.llm_base_url).rstrip("/")
        from urllib.parse import urlsplit
        if urlsplit(self.llm_base_url).query:
            raise ValueError("LLM_BASE_URL no admite query")
        if self.discord_webhook_url:
            parts = urlsplit(safe_url(self.discord_webhook_url))
            if parts.scheme != "https" or parts.hostname not in ("discord.com", "discordapp.com", "canary.discord.com", "ptb.discord.com") or not parts.path.startswith("/api/webhooks/"):
                raise ValueError("DISCORD_WEBHOOK_URL debe ser un webhook HTTPS de Discord")
        if not isinstance(self.sources, dict) or not isinstance(self.rules, list):
            raise ValueError("sources/rules inválidos")
        from .registry import SOURCE_FACTORIES
        if set(self.sources) - SOURCE_FACTORIES.keys():
            raise ValueError("Adaptador sin registrar; añade el módulo en registry.py")
        for cfg in self.sources.values():
            if not isinstance(cfg, dict) or set(cfg) - {"enabled"} or not isinstance(cfg.get("enabled", True), bool):
                raise ValueError("Opciones de fuente inválidas")
        from .rules import RuleEngine
        RuleEngine(self.rules)
