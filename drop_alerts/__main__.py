from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from pathlib import Path

import httpx

from .config import Settings
from .lock import ProcessLock
from .storage import Store


def health(settings) -> bool:
    try:
        heartbeat = json.loads(Path(settings.heartbeat_path).read_text(encoding="utf-8"))
        age = time.time() - float(heartbeat["timestamp"])
        return 0 <= age < 60
    except (OSError, ValueError, KeyError, TypeError):
        return False


async def doctor(settings) -> int:
    """Read-only connectivity probe. Never send a Discord message or inference."""
    from urllib.parse import urlsplit
    targets = [
        ("secret_lair_eu", "https://secretlair.wizards.com/eu/", {}),
        ("magic_news", "https://magic.wizards.com/en/news", {}),
    ]
    if settings.llm_enabled:
        headers = {"Authorization": "Bearer " + settings.llm_api_key} if settings.llm_api_key else {}
        targets.append(("llm_models", settings.llm_base_url + "/models", headers))
    failed = False
    async with httpx.AsyncClient(timeout=settings.http_timeout_seconds, follow_redirects=False) as client:
        for name, url, headers in targets:
            try:
                async with client.stream("GET", url, headers=headers) as response:
                    status = response.status_code
                    record = {"component": name, "host": urlsplit(url).hostname, "http_status": status}
                    if name == "llm_models" and status == 200:
                        body = bytearray()
                        async for chunk in response.aiter_bytes():
                            body.extend(chunk)
                            if len(body) > 1000000:
                                raise ValueError("Respuesta demasiado grande")
                        models = json.loads(body)
                        record["model_listed"] = any(x.get("id") == settings.llm_model for x in models.get("data", []) if isinstance(x, dict))
                        record["chat_inference_verified"] = False
                    failed |= status != 200 or record.get("model_listed") is False
                    print(json.dumps(record, ensure_ascii=False))
            except Exception as exc:
                failed = True
                print(json.dumps({"component": name, "error": type(exc).__name__, "hint": "Revisa DNS, TLS, proxy, firewall o autenticación; consulta docs/troubleshooting.md"}))
    return int(failed)


async def check_llm(settings) -> int:
    """Explicit operator probe: one bounded semantic job, no persistent side effects."""
    from .ai import LLMAnalyzer
    store = Store(":memory:")
    try:
        async with httpx.AsyncClient() as client:
            result = await LLMAnalyzer(settings, store, client).analyze("classification", "Noticia: Secret Lair anuncia una colección futura. No se indica precio ni disponibilidad.")
        print(json.dumps({"analysis_valid": result is not None, "category": result.get("category") if result else None, "needs_review": result.get("needs_review") if result else True, "note": "Valida conexión y esquema; no verifica la verdad de la interpretación"}, ensure_ascii=False))
        return 0 if result is not None else 1
    finally:
        store.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Drop Alerts")
    parser.add_argument("command", nargs="?", default="run", choices=["run", "once", "doctor", "check-llm", "status", "health", "prune", "retry-notifications"])
    args = parser.parse_args()
    try:
        settings = Settings.from_env()
    except Exception as exc:
        # Type only: parser exceptions can contain user-supplied secrets.
        print(f"Configuración inválida ({type(exc).__name__}); revisa .env.example y config.example.toml", file=sys.stderr)
        return 2
    if args.command == "health":
        return 0 if health(settings) else 1
    if args.command == "doctor":
        return asyncio.run(doctor(settings))
    if args.command == "check-llm":
        return asyncio.run(check_llm(settings))
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.CRITICAL)
    logging.getLogger("httpcore").setLevel(logging.CRITICAL)
    if args.command == "status":
        if not Path(settings.database_path).is_file():
            print("Base de datos aún no creada", file=sys.stderr)
            return 1
        store = Store(settings.database_path)
        try:
            print(json.dumps(store.stats(), ensure_ascii=False, indent=2))
        finally:
            store.close()
        return 0
    try:
        with ProcessLock(settings.database_path):
            store = Store(settings.database_path)
            try:
                if args.command == "prune":
                    store.prune(settings.retention_days)
                elif args.command == "retry-notifications":
                    store.db.execute("UPDATE outbox SET status='pending',attempts=0,next_attempt=0 WHERE status='dead' AND last_error NOT LIKE 'analysis_%' AND event_id IN (SELECT id FROM events WHERE payload IS NOT NULL)")
                    store.db.commit()
                else:
                    from .runtime import run
                    asyncio.run(run(settings, store, once=args.command == "once"))
            finally:
                store.close()
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        logging.error("Servicio detenido: %s", type(exc).__name__)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
