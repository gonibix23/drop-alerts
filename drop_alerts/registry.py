"""The only composition root that knows concrete source adapters."""
from .sources import MagicNewsSource, SecretLairSource
from .sources.bluesky import BlueskySource
from .sources.feeds import FeedSource
from .sources.official_announcements import ChaosVaultSource, WPNNewsSource, MagicConNewsSource


SOURCE_FACTORIES = {
    "secret_lair_eu": lambda settings, store: SecretLairSource(max_products=settings.source_max_items, max_duration_seconds=max(30, min(120, settings.poll_interval_seconds / 2))),
    "magic_news": lambda settings, store: MagicNewsSource(max_articles=min(15, settings.source_max_items), max_duration_seconds=max(30, min(120, settings.poll_interval_seconds / 2))),
    "chaos_vault_eu": lambda settings, store: ChaosVaultSource(max_products=min(30, settings.source_max_items), max_duration_seconds=max(30, min(120, settings.poll_interval_seconds / 2))),
    "secret_lair_bluesky": lambda settings, store: BlueskySource(max_items=min(30, settings.source_max_items)),
    "wpn_news": lambda settings, store: WPNNewsSource(max_articles=min(8, settings.source_max_items)),
    "magiccon_news": lambda settings, store: MagicConNewsSource(max_articles=min(8, settings.source_max_items)),
    "weekly_mtg": lambda settings, store: FeedSource("weekly_mtg", "https://www.youtube.com/feeds/videos.xml?playlist_id=PL3rP64NRtmbjdg_j75RqbTu5Ffpc-Q_9s", ("www.youtube.com",), max_items=min(30, settings.source_max_items), official=True, youtube_channel="UC8ZGymAvfP97qJabgqUkz4A"),
    "magicspoiler": lambda settings, store: FeedSource("magicspoiler", "https://www.magicspoiler.com/feed/", ("www.magicspoiler.com", "magicspoiler.com"), max_items=settings.source_max_items),
    "mtggoldfish": lambda settings, store: FeedSource("mtggoldfish", "https://www.mtggoldfish.com/feed", ("www.mtggoldfish.com",), max_items=settings.source_max_items),
    "mtgdrops": lambda settings, store: FeedSource("mtgdrops", "https://mtgdrops.com/feed.xml", ("mtgdrops.com",), max_items=settings.source_max_items),
    "scg_news": lambda settings, store: FeedSource("scg_news", "https://articles.starcitygames.com/feed/", ("articles.starcitygames.com",), max_items=settings.source_max_items),
}


def build_sources(settings, store):
    return [factory(settings, store) for name, factory in SOURCE_FACTORIES.items()
            if name in settings.sources and settings.sources[name].get("enabled", True)]
