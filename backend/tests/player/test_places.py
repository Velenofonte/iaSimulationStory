"""Place id aliases shared by clock, fronts, and reviews."""

from app.services.places import (
    infer_location_kind,
    is_subplace,
    is_travel_intent,
    normalize_place_id,
    place_ancestors,
    player_at_place,
)


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
    assert not is_travel_intent("corro lungo il sentiero")


def test_along_move_intent() -> None:
    from app.services.places import is_along_move_intent, is_scene_departure_intent

    assert is_along_move_intent("corro lungo il sentiero fino al bivio")
    assert is_along_move_intent("cammino sul ciglio")
    assert is_along_move_intent("avanzo")
    assert is_along_move_intent("mi allontano")
    assert is_along_move_intent("continuo sul sentiero verso sud")
    assert is_along_move_intent("seguo la strada")
    assert not is_along_move_intent("guardo intorno")
    assert not is_along_move_intent('"Sette" dico')
    assert not is_along_move_intent("aspetto")
    # travel still counts as scene departure
    assert is_scene_departure_intent("mi dirigo alla gilda", location_changed=False)
    assert is_scene_departure_intent("corro lungo il muro", location_changed=False)
    assert is_scene_departure_intent("guardo", location_changed=True)
    assert not is_scene_departure_intent("guardo intorno", location_changed=False)


def test_infer_location_kind() -> None:
    assert infer_location_kind("rovine-sud") == ("ruin", "high")
    assert infer_location_kind("gilda-avventurieri") == ("settlement", "low")
    assert infer_location_kind("great-wall") == ("fortress", "high")
    assert infer_location_kind("grande-muro") == ("fortress", "high")


def test_is_subplace() -> None:
    assert is_subplace("great-wall-south-trail", "great-wall")
    assert is_subplace("e-rantel-tavern", "e-rantel")
    assert not is_subplace("great-wall", "great-wall")
    assert not is_subplace("e-rantel", "carne")
    assert not is_subplace("wall", "great-wall")


def test_place_ancestors() -> None:
    assert place_ancestors("great-wall-south-trail") == [
        "great-wall-south",
        "great-wall",
        "great",
    ]
    assert place_ancestors("e-rantel-tavern") == ["e-rantel", "e"]
    assert place_ancestors("carne") == []
    assert place_ancestors("") == []
    # Inheritance skips unknown keys; great-wall is found before "great"
    assert "great-wall" in place_ancestors("great-wall-south-trail")


def test_player_at_place_includes_subplaces() -> None:
    assert player_at_place("carne", "carne")
    assert player_at_place("carne", "carne_outskirts")
    assert player_at_place("great-wall-south-trail", "great-wall")
    assert player_at_place("great-wall", "great-wall-south-trail")
    assert not player_at_place("e-rantel", "carne")
    assert player_at_place("carne_village", "carne")
    assert player_at_place("Villaggio di Carne", "carne")
    assert player_at_place("Carne Village", "carne")
