"""Place id aliases shared by clock, fronts, and reviews."""

from app.services.places import normalize_place_id


def test_normalize_place_id_aliases() -> None:
    assert normalize_place_id("carne_village") == "carne"
    assert normalize_place_id("carne-village") == "carne"
    assert normalize_place_id("Carne Village") == "carne"
    assert normalize_place_id("villaggio della carne") == "carne"
    assert normalize_place_id("e-rantel") == "e-rantel"
    assert normalize_place_id("  ") == ""
