"""The only composition root that knows concrete source adapters."""
from .sources import MagicNewsSource, SecretLairSource
from .sources.bluesky import BlueskySource
from .sources.feeds import FeedSource
from .sources.official_announcements import ChaosVaultSource, WPNNewsSource, MagicConNewsSource
from .sources.one_piece import OnePieceProductsSource, OnePieceNewsSource
from .sources.pokemon import PokemonProductsSource, PokemonUSProductsSource, PokemonTCGNewsSource, PokemonPressSource, PokemonJapanNewsSource
from .sources.local_events import LocalTCGEventsSource, MundicomicsEventsSource, MADRID_STORES
from .profiles import SOURCE_PROFILES


def _store_calendar(name, settings):
    from .sources.store_calendars import GladiusEventsSource, NextDiceEventsSource, Arte9EventsSource, LudotecaEventsSource
    classes = {"gladius_events": GladiusEventsSource, "nextdice_events": NextDiceEventsSource,
               "arte9_events": Arte9EventsSource, "ludoteca_events": LudotecaEventsSource}
    return classes[name](max_items=min(80, settings.source_max_items))


def _jupiter_calendar(settings):
    from .sources.jupiter_events import JupiterGuadalajaraEventsSource
    return JupiterGuadalajaraEventsSource(max_items=min(80, settings.source_max_items))


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
    "one_piece_products": lambda settings, store: OnePieceProductsSource(max_items=min(8, settings.source_max_items)),
    "one_piece_news": lambda settings, store: OnePieceNewsSource(max_items=min(8, settings.source_max_items)),
    "pokemon_tcg_news_es": lambda settings, store: PokemonTCGNewsSource(max_items=min(30, settings.source_max_items)),
    "pokemon_press_es": lambda settings, store: PokemonPressSource(max_articles=min(6, settings.source_max_items)),
    "pokemon_products_es": lambda settings, store: PokemonProductsSource(max_items=min(50, settings.source_max_items)),
    "pokemon_products_us": lambda settings, store: PokemonUSProductsSource(max_items=min(50, settings.source_max_items)),
    "pokemon_news_jp": lambda settings, store: PokemonJapanNewsSource(max_items=min(30, settings.source_max_items)),
    "local_tcg_events": lambda settings, store: LocalTCGEventsSource(max_items=settings.source_max_items),
    "local_tcg_events_madrid": lambda settings, store: LocalTCGEventsSource(id="local_tcg_events_madrid", stores=MADRID_STORES, max_items=settings.source_max_items),
    "mundicomics_events": lambda settings, store: MundicomicsEventsSource(max_items=settings.source_max_items),
    **{name: (lambda settings, store, source_id=name: _store_calendar(source_id, settings))
       for name in ("gladius_events", "nextdice_events", "arte9_events", "ludoteca_events")},
    "jupiter_guadalajara_events": lambda settings, store: _jupiter_calendar(settings),
}


def build_sources(settings, store):
    result = []
    for name, factory in SOURCE_FACTORIES.items():
        if name not in settings.sources or not settings.sources[name].get("enabled", True):
            continue
        profile = SOURCE_PROFILES.get(name, {})
        if profile.get("tcg") and profile["tcg"] not in settings.enabled_tcgs:
            continue
        if profile.get("tcgs") and not set(profile["tcgs"]).intersection(settings.enabled_tcgs):
            continue
        result.append(factory(settings, store))
    return result
