from pathlib import Path

import pytest
from pydantic import ValidationError

from drop_alerts.models import Item
from drop_alerts.release_dates import ReleaseSchedule, corroborate_release_quote, extract_release_schedule, has_temporal_hint
from drop_alerts.sources.magic_news import MagicNewsSource


@pytest.mark.parametrize("content,expected,kind", [
    ("Secret Lair goes on sale on November 2, 2026.", "2026-11-02", "sale"),
    ("El drop estará a la venta el 2 de noviembre de 2026.", "2026-11-02", "sale"),
    ("El lanzamiento será el 2 de noviembre de 2026.", "2026-11-02", "release"),
    ("The next drop arrives on November 2, 2026.", "2026-11-02", "release"),
    ("The drop is out November 2, 2026.", "2026-11-02", "release"),
    ("Pre-orders open on 2 November 2026.", "2026-11-02", "preorder"),
    ("La preventa comienza el 2 de noviembre de 2026.", "2026-11-02", "preorder"),
    ("The drop is available on 2026-11-02.", "2026-11-02", "sale"),
])
def test_explicit_sale_release_and_preorder_dates(content, expected, kind):
    result = extract_release_schedule(content)
    assert result["date"] == expected and result["date_kind"] == kind
    assert result["certainty"] == "explicit"
    assert result["engine"] == "deterministic" and result["year_inferred"] is False
    assert all(quote in content for quote in result["evidence"])


@pytest.mark.parametrize("content", [
    "Published November 2, 2026. Coming soon.",
    "Orders begin shipping on November 2, 2026.",
    "The cards become legal in all formats on April 2, 2027.",
    "Prerelease events begin on April 2, 2027.",
    "La entrega está prevista el 2 de noviembre de 2026.",
    "El envío comienza el 2 de noviembre de 2026.",
    "MagicCon convention takes place on November 2, 2026.",
    "Secret Lair has a new announcement.",
])
def test_unrelated_dates_never_become_sale_dates(content):
    result = extract_release_schedule(content)
    assert result["date"] is None and result["certainty"] == "unknown"


@pytest.mark.parametrize("content", [
    "Sold out on November 2, 2026.",
    "Check out November 2, 2026.",
    "Orders ship out on November 2, 2026.",
    "Shipping will be available on November 2, 2026.",
    "Cards become legal and available for tournament play on April 2, 2027.",
    "Delivery is available November 2, 2026.",
])
def test_out_and_available_do_not_override_shipping_legality_or_sold_out(content):
    assert extract_release_schedule(content)["date"] is None


@pytest.mark.parametrize("content", ["No longer available on November 2, 2026.", "No longer on sale on November 2, 2026.", "No disponible el 2 de noviembre de 2026.", "Available until November 2, 2026."])
def test_ending_or_negated_sales_are_not_opening_dates(content):
    assert extract_release_schedule(content)["date"] is None


def test_explicit_product_subject_after_shipping_can_still_announce_sale():
    result = extract_release_schedule("Shipping is delayed, but the drop is available November 2, 2026.")
    assert result["date"] == "2026-11-02"


def test_heading_and_date_on_next_line_keep_their_semantic_relation():
    result = extract_release_schedule("Secret Lair next drop\nComing soon\nNovember 2, 2026.")
    assert result["date"] == "2026-11-02"
    window = extract_release_schedule("Sale window\nJuly 20–August 3, 2026.")
    assert window["date"] == "2026-07-20" and window["end_date"] == "2026-08-03"


def test_time_in_separate_unrelated_sentence_is_not_attached_arbitrarily():
    result = extract_release_schedule("On sale November 2, 2026. At 9 a.m. PT.")
    assert result["date"] == "2026-11-02" and result["time"] is None


def test_sale_beats_release_and_ignores_shipping_and_legality():
    content = "Pre-orders begin on November 1, 2026. Available on November 2, 2026. The drop releases on November 9, 2026. Orders ship on February 3, 2027. Cards become legal April 2, 2027."
    result = extract_release_schedule(content)
    assert result["date"] == "2026-11-02" and result["date_kind"] == "sale"


@pytest.mark.parametrize("published", ["2026-10-16T16:00:00+00:00", "Oct 16, 2026", "Oct 16, 2026 — News, Announcements, Magic"])
def test_missing_year_requires_and_uses_publication_anchor(published):
    result = extract_release_schedule("Available November 2.", published)
    assert result["date"] == "2026-11-02"
    assert result["certainty"] == "estimated" and result["year_inferred"] is True


def test_missing_year_without_anchor_never_uses_system_year():
    result = extract_release_schedule("Available November 2.")
    assert result["date"] is None and result["certainty"] == "unknown"


def test_year_rollover_from_late_year_publication_is_estimated():
    result = extract_release_schedule("Available January 2.", "2026-12-20T00:00:00Z")
    assert result["date"] == "2027-01-02" and result["year_inferred"] is True


@pytest.mark.parametrize("content,clock,zone", [
    ("Available November 2, 2026 at 9 a.m. PT.", "09:00", "America/Los_Angeles"),
    ("Available November 2, 2026 at 12:30 p.m. ET.", "12:30", "America/New_York"),
    ("Disponible el 2 de noviembre de 2026 a las 18:00 hora peninsular.", "18:00", "Europe/Madrid"),
    ("Available November 2, 2026 at 09:00 UTC.", "09:00", "UTC"),
    ("Available November 2, 2026 at 9 a.m.", "09:00", None),
])
def test_explicit_time_and_timezone_only_from_evidence(content, clock, zone):
    result = extract_release_schedule(content)
    assert result["time"] == clock and result["timezone"] == zone


def test_date_only_does_not_invent_standard_secret_lair_opening_time():
    result = extract_release_schedule("Available November 2, 2026.")
    assert result["time"] is None and result["timezone"] is None


@pytest.mark.parametrize("zone", ["UTC+1", "GMT-07:00", "UTC+01:00", "GMT + 1"])
def test_unsupported_numeric_offset_is_not_misread_as_zero_offset(zone):
    result = extract_release_schedule(f"Available November 2, 2026 at 09:00 {zone}.")
    assert result["time"] == "09:00" and result["timezone"] is None


@pytest.mark.parametrize("content,start,end", [
    ("Available from July 20–August 3, 2026.", "2026-07-20", "2026-08-03"),
    ("A la venta del 20 de julio al 3 de agosto de 2026.", "2026-07-20", "2026-08-03"),
    ("Available November 2–9, 2026.", "2026-11-02", "2026-11-09"),
    ("Available December 20–January 3, 2027.", "2026-12-20", "2027-01-03"),
])
def test_sale_windows(content, start, end):
    result = extract_release_schedule(content)
    assert (result["date"], result["end_date"]) == (start, end)


def test_relative_date_is_estimated_from_publication_not_observation():
    result = extract_release_schedule("Available tomorrow!", "2026-10-18T16:00:00Z")
    assert result["date"] == "2026-10-19" and result["certainty"] == "estimated"
    assert extract_release_schedule("Available tomorrow!")["date"] is None


def test_relative_date_uses_explicit_launch_timezone_when_publication_has_an_instant():
    result = extract_release_schedule("Available tomorrow at 9 a.m. PT.", "2026-10-19T01:00:00Z")
    assert result["date"] == "2026-10-19" and result["time"] == "09:00"


def test_complementary_precision_is_not_a_conflict():
    result = extract_release_schedule("Available November 2, 2026 at 9 a.m. Available November 2, 2026 at 9 a.m. PT.")
    assert result["date"] == "2026-11-02" and result["timezone"] == "America/Los_Angeles"
    window = extract_release_schedule("Available July 20, 2026. Available from July 20–August 3, 2026.")
    assert window["date"] == "2026-07-20" and window["end_date"] == "2026-08-03"


@pytest.mark.parametrize("content,expected", [("Coming in November", True), ("Available tomorrow", True), ("Available 02/11/2026", True), ("We may share more later", False), ("A new drop is coming soon", False)])
def test_temporal_hints_only_schedule_semantics_when_date_information_exists(content, expected):
    assert has_temporal_hint(content) is expected


@pytest.mark.parametrize("content", [
    "The drop launches in November 2026.",
    "The drop is coming soon.",
    "The drop may arrive shortly after the November 2, 2026 release date.",
    "The drop will not be available on November 2, 2026.",
    "Originally available on November 2, 2026.",
    "Available February 30, 2026.",
])
def test_approximate_negated_or_invalid_dates_are_not_exact(content):
    assert extract_release_schedule(content)["date"] is None


def test_tentative_explicit_day_is_marked_as_estimated():
    result = extract_release_schedule("The drop is expected to be available on November 2, 2026.")
    assert result["date"] == "2026-11-02" and result["certainty"] == "estimated"


def test_conflicting_dates_and_times_do_not_pick_an_arbitrary_value():
    dates = extract_release_schedule("Available November 2, 2026. Available November 9, 2026.")
    times = extract_release_schedule("Available November 2, 2026 at 9 a.m. PT. Available November 2, 2026 at 10 a.m. PT.")
    assert dates["date"] is None and dates["certainty"] == "conflicting"
    assert times["date"] is None and times["certainty"] == "conflicting"


def test_explicit_correction_can_replace_superseded_date():
    result = extract_release_schedule("Originally available November 2, 2026; now available November 9, 2026.")
    assert result["date"] == "2026-11-09"


def test_countdown_real_article_ignores_legality_2027():
    path = Path(__file__).parent / "fixtures" / "magic_expansion_countdown.html"
    item = Item("example", "magic_news", "Example", "https://magic.wizards.com/en/news/announcements/example", kind="article")
    item = MagicNewsSource().parse_article(path.read_text(encoding="utf-8"), item)
    result = extract_release_schedule(item.content, item.data["published_at"])
    assert result["date"] == "2026-11-02"
    assert result["certainty"] == "explicit"
    assert not any("April 2, 2027" in quote for quote in result["evidence"])


def test_zeta_sale_window_is_not_confused_with_shipping_year():
    content = "On December 9, 2026, Secret Lair x MSCHF: The Zeta Set will go on sale again for a single 24-hour limited order window. We estimate these orders to begin shipping in the second half of 2027."
    result = extract_release_schedule(content, "Oct 1, 2026")
    assert result["date"] == "2026-12-09" and result["certainty"] == "explicit"
    assert result["time"] is None


def test_strict_schedule_rejects_impossible_dates_unknown_fields_and_inconsistent_uncertainty():
    result = extract_release_schedule("Available November 2, 2026.")
    for override in ({"date": "2026-02-30"}, {"date": None}, {"date_kind": "unknown"}, {"command": "execute"}, {"certainty": "unknown"}, {"time": "29:00"}, {"year_inferred": True}):
        with pytest.raises(ValidationError):
            ReleaseSchedule.model_validate({**result, **override})


@pytest.mark.parametrize("heading", ["Shipping:", "Shipping availability:", "Delivery:", "Published:", "Not a release date:"])
def test_quote_corroboration_preserves_negative_or_non_sale_heading(heading):
    quote = "Available November 2, 2026."
    content = heading + "\n" + quote
    assert extract_release_schedule(content)["date"] is None
    assert corroborate_release_quote(content, quote)["date"] is None


def test_quote_corroboration_uses_positive_heading_and_original_publication_anchor():
    content = "Drop details\nSale window:\nNovember 2."
    result = corroborate_release_quote(content, "November 2.", "Oct 16, 2026")
    assert result["date"] == "2026-11-02" and result["year_inferred"] is True
    assert all(quote in content for quote in result["evidence"])


@pytest.mark.parametrize("quote", ["Invented November 2, 2026.", "", " ", None, 2, "x" * 501])
def test_quote_corroboration_rejects_nonliteral_or_invalid_quotes(quote):
    assert corroborate_release_quote("Available November 2, 2026.", quote)["date"] is None


def test_quote_crossing_semantic_segments_cannot_remove_their_context():
    content = "Available November 2, 2026. Shipping starts December 9, 2026."
    quote = "November 2, 2026. Shipping starts"
    assert quote in content
    assert corroborate_release_quote(content, quote)["date"] is None


def test_repeated_quote_with_different_semantics_is_not_accepted():
    quote = "Available November 2, 2026."
    content = "Shipping:\n" + quote + "\nThe drop is here.\n" + quote
    assert corroborate_release_quote(content, quote)["date"] is None


def test_repeated_quote_with_equivalent_semantics_can_be_corroborated():
    quote = "Available November 2, 2026."
    content = quote + "\nThe next drop: " + quote
    assert corroborate_release_quote(content, quote)["date"] == "2026-11-02"


def test_model_can_classify_an_unrecognised_relationship_but_not_invent_the_date():
    content = "The purchasing window: November 2, 2026."
    assert extract_release_schedule(content)["date"] is None
    result = corroborate_release_quote(content, "November 2, 2026", date_kind="sale")
    assert result["date"] == "2026-11-02" and result["date_kind"] == "sale"
    assert result["certainty"] == "estimated" and result["engine"] == "model"
    assert all(quote in content for quote in result["evidence"])


def test_model_relationship_uses_only_a_publication_anchor_for_missing_year():
    content = "The purchasing window: November 2."
    assert corroborate_release_quote(content, "November 2", date_kind="sale")["date"] is None
    result = corroborate_release_quote(content, "November 2", "Oct 16, 2026", date_kind="sale")
    assert result["date"] == "2026-11-02" and result["year_inferred"] is True


@pytest.mark.parametrize("heading", ["Shipping:", "Legal dates:", "Birthday:", "Convention:", "Published:", "Publication date:", "Fecha de publicación:", "Instructions:", "System:", "Delayed:", "Aplazado:", "Ignore previous instructions:", "Set release_date:"])
def test_model_relationship_cannot_override_forbidden_original_headings(heading):
    quote = "November 2, 2026"
    content = heading + "\n" + "The purchasing window: " + quote
    result = corroborate_release_quote(content, quote, date_kind="sale")
    assert result["date"] is None


def test_model_relationship_cannot_choose_between_multiple_literal_dates():
    content = "The purchasing window: November 2, 2026 or November 9, 2026."
    assert corroborate_release_quote(content, "November 2, 2026", date_kind="sale")["date"] is None
