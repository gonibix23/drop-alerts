"""Publication-relative dates must not compete with a physical release date."""
from pathlib import Path

import pytest

from drop_alerts.release_dates import extract_release_schedule
from drop_alerts.schedule_enrichment import enrich_item
from drop_alerts.sources.pokemon import PokemonPressSource


@pytest.mark.parametrize("content", [
    "The company announced today that the product launches November 6, 2026.",
    "Today the company announced that the product launches November 6, 2026.",
    "The company revealed today that the product launches November 6, 2026.",
    "New release\nToday the company announced that the product launches November 6, 2026.",
    "La empresa ha anunciado hoy que el producto saldrá el 6 de noviembre de 2026.",
    "Hoy la empresa ha anunciado que el producto saldrá el 6 de noviembre de 2026.",
    "La empresa reveló hoy que el lanzamiento será el 6 de noviembre de 2026.",
])
def test_editorial_today_does_not_conflict_with_actual_product_release(content):
    result = extract_release_schedule(content, "2026-08-20")
    assert result["date"] == "2026-11-06" and result["certainty"] == "explicit"


@pytest.mark.parametrize("content", [
    "Today the company announced a new product.",
    "The company revealed today a new collection.",
    "La empresa ha anunciado hoy una nueva colección.",
    "Hoy la empresa anunció una nueva expansión.",
])
def test_editorial_today_without_launch_date_remains_unknown(content):
    assert extract_release_schedule(content, "2026-08-20")["date"] is None


@pytest.mark.parametrize("content", ["Available today.", "Disponible hoy.", "The company announced today and the drop is available today."])
def test_actual_relative_sale_today_still_uses_publication_anchor(content):
    result = extract_release_schedule(content, "2026-08-20")
    assert result["date"] == "2026-08-20" and result["date_kind"] == "sale"
    assert result["certainty"] == "estimated"


@pytest.mark.parametrize("content", [
    "Sale announced for November 2, 2026.",
    "On sale announced for November 2, 2026.",
    "Sale was announced today for November 2, 2026.",
])
def test_announced_sale_target_date_is_not_excluded_as_publication(content):
    result = extract_release_schedule(content, "2026-08-20")
    assert result["date"] == "2026-11-02" and result["date_kind"] == "sale"


def test_real_pokemon_press_note_has_physical_release_date_not_editorial_today():
    fixtures = Path(__file__).parent / "fixtures"
    source = PokemonPressSource()
    item = next(item for item in source.parse_listing((fixtures / "pokemon_press_listing.html").read_text(encoding="utf-8")) if "nueva-expansion" in item.url)
    source.parse_article((fixtures / "pokemon_press_article.html").read_text(encoding="utf-8"), item)
    enrich_item(item)
    result = item.data["release_schedule"]
    assert result["date"] == "2026-11-06" and result["certainty"] == "explicit"
    assert item.data["published_at"] == "2026-08-20"
    assert item.state == "ANNOUNCED" and item.data["availability_verified"] is False
