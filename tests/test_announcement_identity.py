from dataclasses import replace
import json

import pytest

from drop_alerts.config import Settings
from drop_alerts.detection import DetectionEngine
from drop_alerts.identities import announcement_url, referenced_announcement
from drop_alerts.models import FetchResult, Item
from drop_alerts.rules import RuleEngine
from drop_alerts.storage import Store

ARTICLE = "https://magic.wizards.com/en/news/announcements/secret-lair-example"


def article(source="magic_news", **overrides):
    values = dict(id=ARTICLE, source=source, title="Secret Lair example", url=ARTICLE,
                  kind="announcement", state="ANNOUNCED", data={"summary": "Future launch"})
    values.update(overrides)
    return Item(**values)


def ingest(store, items, settings, metadata=None):
    return store.ingest(items[0].source, FetchResult(items, metadata=metadata or {}), DetectionEngine(), RuleEngine(settings.rules), settings)


def settings(**overrides):
    return Settings(bootstrap_mode="notify", rules=[{"id": "all"}], **overrides)


def test_two_sources_linking_same_official_article_only_queue_one_notification_and_analysis(tmp_path):
    config = settings()
    store = Store(str(tmp_path / "state.db"))
    ingest(store, [article()], config)
    post = article("secret_lair_bluesky", id="post:one", url="https://bsky.app/profile/example/post/one", data={"announcement_url": ARTICLE})
    ingest(store, [post], config)
    assert len(store.due_notifications(10)) == 1
    assert len(store.due_analysis(10)) == 1
    assert store.db.execute("SELECT count(*) FROM events").fetchone()[0] == 2
    store.close()
    store = Store(str(tmp_path / "state.db"))
    ingest(store, [replace(post, id="post:two")], config)
    assert len(store.due_notifications(10)) == 1
    assert len(store.due_analysis(10)) == 1
    store.close()


def test_real_article_update_or_new_sale_window_is_not_suppressed():
    store = Store(":memory:")
    config = settings(llm_enabled=False)
    ingest(store, [article()], config)
    ingest(store, [article(content="Another sale window announced")], config)
    other = article(id=ARTICLE + "-update", url=ARTICLE + "-update")
    ingest(store, [other], config)
    assert [event.event_type for event, _ in store.due_notifications(10)] == ["announcement.new", "content.changed", "announcement.new"]


def test_related_titles_and_distinct_regional_products_are_not_fuzzy_merged():
    store = Store(":memory:")
    config = settings(llm_enabled=False)
    ingest(store, [article(url="https://example.com/a"), article(id="other", url="https://example.com/b")], config)
    assert len(store.due_notifications(10)) == 2
    assert referenced_announcement([ARTICLE, ARTICLE + "-other"]) is None
    assert announcement_url("https://secretlair.wizards.com/eu/") is None
    assert announcement_url("https://user:secret@magic.wizards.com/en/news/announcements/x") is None


def test_new_discovery_inventory_is_silent_on_existing_database_and_transactional(tmp_path):
    store = Store(str(tmp_path / "state.db"))
    config = Settings(rules=[{"id": "all"}], llm_enabled=False)
    ingest(store, [article()], config)
    historical = article(id=ARTICLE + "-old", url=ARTICLE + "-old")
    metadata = {"discovery_inventories": {"sitemap_v1": [historical.id, ARTICLE + "-later"]}}
    ingest(store, [historical], config, metadata)
    assert not store.due_notifications(10)
    ingest(store, [article(id=ARTICLE + "-later", url=ARTICLE + "-later")], config)
    assert not store.due_notifications(10)
    ingest(store, [article(id=ARTICLE + "-new", url=ARTICLE + "-new")], config)
    assert len(store.due_notifications(10)) == 1
    store.close()


def test_inventory_marker_rolls_back_with_failed_ingestion():
    store = Store(":memory:")
    class BrokenRules:
        def decide(self, event):
            raise RuntimeError("crash")
    with pytest.raises(RuntimeError):
        store.ingest("magic_news", FetchResult([article()], metadata={"discovery_inventories": {"new": [ARTICLE]}}), DetectionEngine(), BrokenRules(), Settings())
    assert store.get_meta("source_inventory:magic_news:new") is None


def test_schema_one_upgrade_backfills_prior_announcements_without_losing_deliveries(tmp_path):
    path = str(tmp_path / "state.db")
    store = Store(path)
    config = settings(llm_enabled=False)
    ingest(store, [article()], config)
    event = store.due_notifications(1)[0][0]
    store.notification_result(event.id, 1)
    store.db.execute("DROP TABLE announcement_claims")
    store.db.execute("UPDATE meta SET value='1' WHERE key='schema_version'")
    store.db.commit()
    store.close()
    store = Store(path)
    assert store.get_meta("schema_version") == "2"
    assert store.db.execute("SELECT status FROM outbox").fetchone()[0] == "sent"
    ingest(store, [article("other", id="other")], config)
    assert not store.due_notifications(10)


def test_presentation_metadata_does_not_create_fake_update():
    before = article()
    after = replace(before, data={**before.data, "image_url": "https://official.test/image.jpg", "image_verified": True, "announcement_url": ARTICLE})
    assert before.digest == after.digest
    assert DetectionEngine().detect(after, before, 2) == []
