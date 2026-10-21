from __future__ import annotations

import asyncio
import json
import logging
import signal
import time
from pathlib import Path

import httpx

from .ai import LLMAnalyzer
from .detection import DetectionEngine
from .notifications import DiscordChannel, NotificationWorker
from .rules import RuleEngine

log = logging.getLogger("drop_alerts")


class Monitor:
    def __init__(self, settings, store, sources, http):
        self.settings, self.store, self.sources, self.http = settings, store, sources, http
        self.detector, self.rules = DetectionEngine(), RuleEngine(settings.rules)

    async def check(self, source):
        self.store.source_attempt(source.id)
        try:
            result = await asyncio.wait_for(source.fetch(self.http), timeout=max(60, min(240, self.settings.poll_interval_seconds)))
            count = self.store.ingest(source.id, result, self.detector, self.rules, self.settings)
            if result.metadata.get("errors"):
                self.store.diagnostic(source.id, "partial_extraction", f"Detalles no extraídos: {len(result.metadata['errors'])}")
            log.info("Fuente %s: %s elementos, %s eventos", source.id, len(result.items), count)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            code = type(exc).__name__
            self.store.source_error(source.id, code)
            log.warning("Fuente %s: %s", source.id, code)

    async def tick(self, force=False):
        due = []
        now = time.time()
        for source in self.sources:
            interval = self.settings.sources.get(source.id, {}).get("interval_seconds", self.settings.poll_interval_seconds)
            marker = "source_next_check:" + source.id
            try:
                next_check = float(self.store.get_meta(marker, 0))
            except (ValueError, TypeError):
                next_check = 0
            if force or next_check <= now:
                self.store.set_meta(marker, str(now + interval))
                due.append(source)
        await asyncio.gather(*(self.check(source) for source in due))


class AnalysisWorker:
    def __init__(self, settings, store, analyzer):
        self.settings, self.store, self.analyzer = settings, store, analyzer

    async def tick(self):
        if not self.settings.llm_enabled:
            return
        for job in self.store.due_analysis(self.settings.analyses_per_tick):
            try:
                result = await asyncio.wait_for(self.analyzer.analyze(job["task"], job["content"]), timeout=min(300, self.settings.llm_timeout_seconds * (3 + self.settings.llm_max_retries) + 5))
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.store.diagnostic("ai", type(exc).__name__, "Análisis no disponible; continúa la detección determinista")
                result = None
            self.store.finish_analysis(job, result, self.settings.analysis_max_attempts)


def heartbeat(settings):
    path = Path(settings.heartbeat_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps({"timestamp": time.time(), "version": "1.2.0"}), encoding="utf-8")
    temporary.replace(path)


async def run(settings, store, once: bool = False):
    from .http import SourceHTTP
    from .registry import build_sources
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(signum, stop.set)
        except NotImplementedError:
            signal.signal(signum, lambda *_: loop.call_soon_threadsafe(stop.set))
    limits = httpx.Limits(max_connections=8, max_keepalive_connections=6)
    async with httpx.AsyncClient(timeout=settings.http_timeout_seconds, limits=limits, follow_redirects=False) as source_client, httpx.AsyncClient(limits=httpx.Limits(max_connections=1)) as ai_client, httpx.AsyncClient(limits=httpx.Limits(max_connections=1)) as discord_client:
        http = SourceHTTP(source_client, store=store, max_bytes=settings.source_max_bytes, retries=settings.http_max_retries, timeout=settings.http_timeout_seconds)
        monitor = Monitor(settings, store, build_sources(settings, store), http)
        analyses = AnalysisWorker(settings, store, LLMAnalyzer(settings, store, ai_client))
        notifications = NotificationWorker(settings, store, DiscordChannel(settings, store, discord_client))
        if once:
            await monitor.tick(force=True)
            await analyses.tick()
            await notifications.tick()
            # A one-shot run must not make a stopped daemon appear healthy.
            return

        async def periodic(name, action, interval):
            while not stop.is_set():
                try:
                    await action()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    store.diagnostic(name, type(exc).__name__, "Fallo de componente; se reintentará")
                    log.error("Componente %s: %s", name, type(exc).__name__)
                try:
                    await asyncio.wait_for(stop.wait(), interval)
                except TimeoutError:
                    pass

        async def beat():
            heartbeat(settings)

        async def prune():
            store.prune(settings.retention_days)

        monitor_interval = min([settings.poll_interval_seconds] + [settings.sources.get(source.id, {}).get("interval_seconds", settings.poll_interval_seconds) for source in monitor.sources])
        tasks = [asyncio.create_task(periodic(name, action, interval)) for name, action, interval in (
            ("monitor", monitor.tick, monitor_interval),
            ("analysis", analyses.tick, 10), ("notifications", notifications.tick, 2),
            ("heartbeat", beat, 10), ("retention", prune, 86400),
        )]
        log.info("Drop Alerts iniciado; %s fuentes; IA %s", len(monitor.sources), settings.llm_enabled)
        try:
            await stop.wait()
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            Path(settings.heartbeat_path).unlink(missing_ok=True)
