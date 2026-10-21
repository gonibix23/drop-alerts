"""A model-picked quote must not discard a source heading that changes its meaning."""
import pytest

from drop_alerts.schedule_enrichment import effective_release_schedule


@pytest.mark.parametrize("heading", ["Shipping availability:", "Legal availability:", "Not available for sale:"])
def test_selected_quote_retains_a_previous_heading_excluding_commercial_release(heading):
    quote = "Available November 2, 2026."
    current = {"title": "Secret Lair", "content": heading + "\n" + quote,
               "data": {"published_at": "2026-10-16"}}
    model = {"task": "release_schedule", "engine": "model", "verified": False,
             "result": {"date_kind": "sale", "date_quote": quote, "evidence": [quote],
                        "confidence": 0.8, "needs_review": False}}
    assert effective_release_schedule(current)["date"] is None
    assert effective_release_schedule(current, model)["date"] is None


@pytest.mark.parametrize("content", [
    "No longer available on November 2, 2026.",
    "No longer on sale on November 2, 2026.",
    "No disponible el 2 de noviembre de 2026.",
])
def test_negative_availability_is_not_a_commercial_opening_date(content):
    current = {"title": "Secret Lair", "content": content,
               "data": {"published_at": "2026-10-16"}}
    assert effective_release_schedule(current)["date"] is None
