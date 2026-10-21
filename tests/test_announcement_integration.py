"""Configuration and scheduling contracts for the expanded announcement sources."""
import asyncio
from pathlib import Path

import pytest

from drop_alerts.config import Settings
from drop_alerts.models import ExtractionError, FetchResult, Item
from drop_alerts.registry import SOURCE_FACTORIES, build_sources
from drop_alerts.runtime import Monitor
from drop_alerts.storage import Store


OFFICIAL = {
    "secret_lair_eu", "magic_news", "chaos_vault_eu", "secret_lair_bluesky",
    "wpn_news", "magiccon_news", "weekly_mtg",
}
SECONDARY = {"magicspoiler", "mtggoldfish", "mtgdrops", "scg_news"}


def test_default_configuration_builds_seven_official_sources_without_secondary_feeds():
    settings = Settings.from_env({})
    store = Store(":memory:")
    try:
        sources = build_sources(settings, store)
        assert {source.id for source in sources} == OFFICIAL
        assert len(sources) == 7
        assert all(not settings.sources[source]["enabled"] for source in SECONDARY)
        assert SECONDARY <= SOURCE_FACTORIES.keys()
    finally:
        store.close()


def test_example_toml_builds_the_same_sources_and_slower_editorial_intervals():
    example = Path(__file__).resolve().parents[1] / "config.example.toml"
    settings = Settings.from_env({"CONFIG_PATH": str(example)})
    store = Store(":memory:")
    try:
        assert {source.id for source in build_sources(settings, store)} == OFFICIAL
        assert all(not settings.sources[source]["enabled"] for source in SECONDARY)
        assert settings.sources["wpn_news"]["interval_seconds"] == 900
        assert settings.sources["magiccon_news"]["interval_seconds"] == 1800
        assert settings.sources["weekly_mtg"]["interval_seconds"] == 900
    finally:
        store.close()


def test_secondary_feed_is_built_only_when_explicitly_enabled():
    settings = Settings.from_env({})
    settings.sources["magicspoiler"]["enabled"] = True
    store = Store(":memory:")
    try:
        assert {source.id for source in build_sources(settings, store)} == OFFICIAL | {"magicspoiler"}
    finally:
        store.close()


def test_toml_with_only_interval_enables_that_source_and_keeps_absent_sources_off(tmp_path):
    path = tmp_path / "one-source.toml"
    path.write_text("[sources.wpn_news]\ninterval_seconds = 900\n", encoding="utf-8")
    settings = Settings.from_env({"CONFIG_PATH": str(path)})
    store = Store(":memory:")
    try:
        assert [source.id for source in build_sources(settings, store)] == ["wpn_news"]
    finally:
        store.close()


@pytest.mark.parametrize("value", ['"900"', "true", "false", "900.0", "nan", "29", "86401", "0", "-1"])
def test_toml_rejects_non_integer_or_out_of_range_source_intervals(tmp_path, value):
    path = tmp_path / "invalid.toml"
    path.write_text(f"[sources.wpn_news]\nenabled = true\ninterval_seconds = {value}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="interval_seconds"):
        Settings.from_env({"CONFIG_PATH": str(path)})


@pytest.mark.parametrize("value", [30, 86400])
def test_toml_accepts_supported_source_interval_boundaries(tmp_path, value):
    path = tmp_path / "valid.toml"
    path.write_text(f"[sources.wpn_news]\nenabled = true\ninterval_seconds = {value}\n", encoding="utf-8")
    settings = Settings.from_env({"CONFIG_PATH": str(path)})
    assert settings.sources["wpn_news"]["interval_seconds"] == value


class Source:
    def __init__(self, source_id, error=None, release=None):
        self.id, self.error, self.release, self.calls = source_id, error, release, 0

    async def fetch(self, http):
        self.calls += 1
        if self.release:
            self.release.set()
        if self.error:
            raise self.error
        return FetchResult([Item(id="announcement", source=self.id, title="Secret Lair special announcement",
                                 url=f"https://example.test/{self.id}", kind="announcement", state="ANNOUNCED")])


def monitor_settings(**overrides):
    values = {"bootstrap_mode": "notify", "llm_enabled": False, "rules": [{"id": "all"}],
              "sources": {"wpn_news": {"enabled": True, "interval_seconds": 900},
                          "magiccon_news": {"enabled": True, "interval_seconds": 1800}}}
    values.update(overrides)
    return Settings(**values)


async def test_monitor_respects_persisted_source_intervals_after_restart(tmp_path, monkeypatch):
    clock = {"now": 1000.0}
    monkeypatch.setattr("drop_alerts.runtime.time.time", lambda: clock["now"])
    settings = monitor_settings()
    path = str(tmp_path / "state.db")
    first_sources = [Source("wpn_news"), Source("magiccon_news")]
    store = Store(path)
    await Monitor(settings, store, first_sources, object()).tick()
    assert [source.calls for source in first_sources] == [1, 1]
    assert float(store.get_meta("source_next_check:wpn_news")) == 1900.0
    assert float(store.get_meta("source_next_check:magiccon_news")) == 2800.0
    store.close()

    clock["now"] = 1500.0
    store = Store(path)
    try:
        restarted_sources = [Source("wpn_news"), Source("magiccon_news")]
        monitor = Monitor(settings, store, restarted_sources, object())
        await monitor.tick()
        assert [source.calls for source in restarted_sources] == [0, 0]
        clock["now"] = 1900.0
        await monitor.tick()
        assert [source.calls for source in restarted_sources] == [1, 0]
        clock["now"] = 2800.0
        await monitor.tick()
        assert [source.calls for source in restarted_sources] == [2, 1]
    finally:
        store.close()


async def test_forced_monitor_check_checks_all_sources_even_when_not_due(monkeypatch):
    monkeypatch.setattr("drop_alerts.runtime.time.time", lambda: 1000.0)
    store = Store(":memory:")
    try:
        sources = [Source("wpn_news"), Source("magiccon_news")]
        for source in sources:
            store.set_meta("source_next_check:" + source.id, "99999")
        monitor = Monitor(monitor_settings(), store, sources, object())
        await monitor.tick(force=True)
        assert [source.calls for source in sources] == [1, 1]
        assert float(store.get_meta("source_next_check:wpn_news")) == 1900.0
        assert float(store.get_meta("source_next_check:magiccon_news")) == 2800.0
    finally:
        store.close()


async def test_source_without_custom_interval_uses_global_poll_interval(monkeypatch):
    clock = {"now": 1000.0}
    monkeypatch.setattr("drop_alerts.runtime.time.time", lambda: clock["now"])
    store = Store(":memory:")
    try:
        source = Source("wpn_news")
        settings = monitor_settings(poll_interval_seconds=300, sources={"wpn_news": {"enabled": True}})
        monitor = Monitor(settings, store, [source], object())
        await monitor.tick()
        assert float(store.get_meta("source_next_check:wpn_news")) == 1300.0
        clock["now"] = 1299.0
        await monitor.tick()
        assert source.calls == 1
        clock["now"] = 1300.0
        await monitor.tick()
        assert source.calls == 2
    finally:
        store.close()


async def test_failing_announcement_source_is_isolated_and_retains_its_retry_interval(monkeypatch):
    clock = {"now": 1000.0}
    monkeypatch.setattr("drop_alerts.runtime.time.time", lambda: clock["now"])
    other_started = asyncio.Event()

    class FailingSource(Source):
        async def fetch(self, http):
            self.calls += 1
            await other_started.wait()
            raise ExtractionError("simulated source outage")

    sources = [FailingSource("wpn_news"), Source("magiccon_news", release=other_started)]
    store = Store(":memory:")
    try:
        monitor = Monitor(monitor_settings(), store, sources, object())
        await asyncio.wait_for(monitor.tick(), timeout=1)
        status = {source["id"]: source for source in store.stats()["sources"]}
        assert status["wpn_news"]["failures"] == 1
        assert status["magiccon_news"]["last_success"]
        assert store.item("magiccon_news", "announcement")[0] is not None
        assert len(store.due_notifications(10)) == 1
        clock["now"] = 1100.0
        await monitor.tick()
        assert [source.calls for source in sources] == [1, 1]
    finally:
        store.close()


async def test_invalid_persisted_schedule_does_not_disable_a_source(monkeypatch):
    monkeypatch.setattr("drop_alerts.runtime.time.time", lambda: 1000.0)
    store = Store(":memory:")
    try:
        source = Source("wpn_news")
        store.set_meta("source_next_check:wpn_news", "invalid-timestamp")
        await Monitor(monitor_settings(), store, [source], object()).tick()
        assert source.calls == 1
    finally:
        store.close()
