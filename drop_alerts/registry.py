"""The only composition root that knows concrete source adapters."""
from .sources import MagicNewsSource, SecretLairSource


SOURCE_FACTORIES = {
    "secret_lair_eu": lambda settings, store: SecretLairSource(max_products=settings.source_max_items, max_duration_seconds=max(30, min(120, settings.poll_interval_seconds / 2))),
    "magic_news": lambda settings, store: MagicNewsSource(max_articles=min(15, settings.source_max_items), max_duration_seconds=max(30, min(120, settings.poll_interval_seconds / 2))),
}


def build_sources(settings, store):
    return [factory(settings, store) for name, factory in SOURCE_FACTORIES.items() if settings.sources.get(name, {}).get("enabled", False)]
