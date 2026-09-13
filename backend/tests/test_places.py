"""Place id aliases shared by clock, fronts, and reviews."""

from app.services.places import infer_location_kind, is_travel_intent, normalize_place_id


def test_normalize_place_id_aliases() -> None:
    assert normalize_place_id("carne_village") == "carne"
    assert normalize_place_id("carne-village") == "carne"
    assert normalize_place_id("Carne Village") == "carne"
    assert normalize_place_id("villaggio della carne") == "carne"
    assert normalize_place_id("e-rantel") == "e-rantel"
    assert normalize_place_id("  ") == ""


def test_guild_faction_is_not_a_place() -> None:
    assert normalize_place_id("adventurers-guild") == "gilda-avventurieri"
    assert normalize_place_id("sede della gilda") == "gilda-avventurieri"
    assert normalize_place_id("gilda") == "gilda-avventurieri"


def test_travel_intent() -> None:
    assert is_travel_intent("Mi dirigo alla sede della gilda")
    assert is_travel_intent("Si sono pronto partiamo pure e mi avvio")
    assert is_travel_intent("cammino verso E-Rantel")
    assert is_travel_intent("torno alla locanda")
    assert is_travel_intent("esco dalla gilda")
    assert not is_travel_intent("guardo il medaglione")
    assert not is_travel_intent('"Sette" dico')


def test_infer_location_kind() -> None:
    assert infer_location_kind("rovine-sud") == ("ruin", "high")
    assert infer_location_kind("gilda-avventurieri") == ("settlement", "low")
    assert infer_location_kind("avamposto-bosco-silente") == ("outpost", "medium")
