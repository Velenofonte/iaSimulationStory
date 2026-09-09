"""Tests for token budget helpers and narrative payload knobs."""

from pathlib import Path

import frontmatter

from app.config import settings
from app.models import CharacterCard, GameState, PlayerState
from app.models.narrative import NarrativeRequest
from app.services.narrative_engine import NarrativeEngine
from app.services.prompt_builder import PromptBuilder
from app.services.save_manager import SaveManager
from app.services.token_estimate import estimate_tokens, fill_by_priority, fit_text
from app.services.wiki_query import WikiQuery
from app.services.wiki_writer import WikiWriter


def test_fit_text_no_limit() -> None:
    assert fit_text("hello world", 0) == "hello world"
    assert fit_text("hello world", -1) == "hello world"


def test_fit_text_truncates() -> None:
    long = "alpha beta gamma delta epsilon zeta eta theta"
    out = fit_text(long, 3)  # ~12 chars
    assert len(out) <= 12
    assert out


def test_fill_by_priority_disabled() -> None:
    items = ["a" * 40, "b" * 40, "c" * 40]
    assert fill_by_priority(items, 0) == items


def test_fill_by_priority_cuts() -> None:
    items = ["aaaa", "bbbb", "cccc"]  # ~1 tok each at 4 chars
    kept = fill_by_priority(items, 2, size_fn=estimate_tokens)
    assert kept == ["aaaa", "bbbb"]


def test_prompt_card_default_matches_legacy_order(monkeypatch) -> None:
    monkeypatch.setattr(settings, "card_budget_minimal", 0)
    monkeypatch.setattr(settings, "card_section_chars", 300)
    body = (
        "# Personalita\nGentile e coraggiosa.\n\n"
        "# Aspetto fisico\nCapelli castani.\n\n"
        "# Obiettivi\nProteggere il villaggio.\n\n"
        "# Knowledge scope\nsa: goblin.\nnon sa: Nazarick.\n\n"
        "# Memorie\nHa visto cavalieri.\n\n"
        "# Open threads\n- Aiuto dal regno\n"
    )
    card = CharacterCard(id="enri", name="Enri", tier="minimal", body=body)
    text = PromptBuilder().build_prompt_card(card)
    # Legacy order: Personalita before Aspetto before Knowledge
    assert text.index("Personalita:") < text.index("Aspetto fisico:")
    assert text.index("Aspetto fisico:") < text.index("Knowledge scope:")


def test_prompt_card_tier_budget_prioritizes_knowledge(monkeypatch) -> None:
    monkeypatch.setattr(settings, "card_budget_minimal", 80)
    monkeypatch.setattr(settings, "card_section_chars", 300)
    body = (
        "# Personalita\n" + ("Gentile. " * 40) + "\n\n"
        "# Aspetto fisico\n" + ("Capelli. " * 40) + "\n\n"
        "# Knowledge scope\nsa: goblin e villaggio.\nnon sa: Nazarick.\n"
    )
    card = CharacterCard(id="enri", name="Enri", tier="minimal", body=body)
    text = PromptBuilder().build_prompt_card(card)
    assert "Knowledge scope:" in text
    # Aspetto is lowest priority — likely dropped under tight budget
    assert estimate_tokens(text) <= 90


def _seed_session(tmp_path: Path, *, with_npc: bool = True) -> tuple[GameState, NarrativeEngine]:
    saves_root = tmp_path / "saves"
    sm = SaveManager(root=saves_root)
    state = GameState(
        session_id="tok-test",
        player=PlayerState(name="Tester", location="carne"),
        characters_active=["enri"] if with_npc else [],
        situations=["voci di armati"],
    )
    sm.save_game_state(state)
    wiki_dir = sm.wiki_dir(state.session_id)
    wiki_dir.mkdir(parents=True, exist_ok=True)
    (wiki_dir / "index.md").write_text(
        "- [[carne]] -> locations/carne.md\n"
        "- [[enri]] -> characters/enri.md\n"
        "- [[tester]] -> characters/tester.md\n",
        encoding="utf-8",
    )
    (wiki_dir / "locations").mkdir(parents=True, exist_ok=True)
    (wiki_dir / "characters").mkdir(parents=True, exist_ok=True)
    (wiki_dir / "locations" / "carne.md").write_text(
        "---\nid: carne\nname: Carne\ntype: location\n---\n# Descrizione\nVillaggio di frontiera.\n",
        encoding="utf-8",
    )
    (wiki_dir / "characters" / "tester.md").write_text(
        "---\nid: tester\nname: Tester\ntype: character\ntier: minimal\nrole: player\n---\n"
        "# Capacita di combattimento\n- Lv 100; immune a magie di basso livello.\n"
        "# Equipaggiamento\n- Bastone leggendario.\n- Anelli occultanti.\n"
        "# Knowledge scope\nsa: YGGDRASIL.\n",
        encoding="utf-8",
    )
    if with_npc:
        (wiki_dir / "characters" / "enri.md").write_text(
            "---\nid: enri\nname: Enri\ntype: canonical\ntier: minimal\n---\n"
            "# Personalita\nGentile.\n# Knowledge scope\nsa: goblin.\n",
            encoding="utf-8",
        )
    (wiki_dir / "spellbooks").mkdir(parents=True, exist_ok=True)
    post = frontmatter.Post(
        "# Spellbook\n- Luce — magia di tier 1\n- Fly — volare\n",
        id="tester",
        name="Tester",
        type="spellbook",
    )
    (wiki_dir / "spellbooks" / "tester.md").write_text(
        frontmatter.dumps(post), encoding="utf-8"
    )
    (saves_root / state.session_id / "chat.jsonl").write_text("", encoding="utf-8")

    wiki = WikiWriter(wiki_dir=wiki_dir)
    query = WikiQuery(wiki_dir=wiki_dir)
    engine = NarrativeEngine(wiki=query, wiki_writer=wiki, saves=sm)
    return state, engine


def test_build_request_no_output_schema_hint(tmp_path: Path) -> None:
    state, engine = _seed_session(tmp_path)
    req = engine.build_request(state=state, user_message="guardo intorno")
    payload = req.model_dump()
    assert "output_schema_hint" not in payload
    assert isinstance(req, NarrativeRequest)


def test_build_request_compact_json(tmp_path: Path) -> None:
    state, engine = _seed_session(tmp_path)
    req = engine.build_request(state=state, user_message="guardo")
    dumped = req.model_dump_json()
    assert "\n  " not in dumped  # no pretty indent


def test_dedup_world_cards(tmp_path: Path, monkeypatch) -> None:
    state, engine = _seed_session(tmp_path)
    monkeypatch.setattr(settings, "narrative_dedup_world_cards", True)
    req = engine.build_request(state=state, user_message="parlo con Enri")
    world_ids = {p.id.lower() for p in req.world_pages}
    assert "enri" not in world_ids
    assert any(p.id.lower() == "carne" for p in req.world_pages)
    assert req.character_cards  # enri still as card
    assert any("ID: tester" in c or "ID: Tester" in c or "Nome: Tester" in c for c in req.character_cards)


def test_player_sheet_always_in_character_cards(tmp_path: Path) -> None:
    state, engine = _seed_session(tmp_path, with_npc=False)
    req = engine.build_request(state=state, user_message="guardo i miei anelli")
    assert len(req.character_cards) >= 1
    player_card = req.character_cards[0]
    assert "Nome: Tester" in player_card or "ID: tester" in player_card
    assert "Capacita di combattimento:" in player_card
    assert "immune a magie di basso livello" in player_card
    assert "Equipaggiamento:" in player_card
    assert "Anelli occultanti" in player_card
    assert "Ruolo: player" in player_card


def test_prompt_card_includes_equipment(monkeypatch) -> None:
    monkeypatch.setattr(settings, "card_budget_minimal", 0)
    monkeypatch.setattr(settings, "card_section_chars", 300)
    body = (
        "# Capacita di combattimento\nLv 100; immune basso livello.\n\n"
        "# Skill / build YGGDRASIL\nDivine Wizard.\n\n"
        "# Equipaggiamento\n- Anelli occultanti.\n\n"
        "# Knowledge scope\nsa: tutto.\n"
    )
    card = CharacterCard(id="bliss", name="Bliss", tier="minimal", role="player", body=body)
    text = PromptBuilder().build_prompt_card(card)
    assert "Capacita di combattimento:" in text
    assert "Skill / build YGGDRASIL:" in text
    assert "Equipaggiamento:" in text
    assert "Anelli occultanti" in text


def test_player_sheet_never_truncated(monkeypatch) -> None:
    monkeypatch.setattr(settings, "card_budget_minimal", 40)
    monkeypatch.setattr(settings, "card_section_chars", 80)
    long_equip = (
        "- Bastone leggendario mascherato.\n"
        "- Vestigia divine mascherate.\n"
        "- Anelli di occultamento.\n"
        "- Inventario YGGDRASIL completo: può estrarre monete d'oro convertite "
        "nella valuta del Nuovo Mondo e item rari leggendari divini."
    )
    assert len(long_equip) > 80
    body = (
        "# Personalita\n" + ("Misterioso. " * 20) + "\n\n"
        "# Capacita di combattimento\nImmune a magie di basso livello.\n\n"
        f"# Equipaggiamento\n{long_equip}\n\n"
        "# Knowledge scope\nsa: YGGDRASIL.\n"
    )
    card = CharacterCard(id="rayan", name="Rayan", tier="minimal", role="player", body=body)
    text = PromptBuilder().build_prompt_card(card)
    assert "Capacita di combattimento:" in text
    assert "Inventario YGGDRASIL completo" in text
    assert "monete d'oro" in text
    assert "Misterioso." in text



def test_spellbook_on_demand_names_only(tmp_path: Path, monkeypatch) -> None:
    state, engine = _seed_session(tmp_path)
    monkeypatch.setattr(settings, "narrative_spellbook_on_demand", True)
    req = engine.build_request(state=state, user_message="guardo intorno")
    assert all(s.description == "" for s in req.spellbook)
    assert {s.name for s in req.spellbook} >= {"Luce", "Fly"}


def test_spellbook_on_demand_full_when_cited(tmp_path: Path, monkeypatch) -> None:
    state, engine = _seed_session(tmp_path)
    monkeypatch.setattr(settings, "narrative_spellbook_on_demand", True)
    req = engine.build_request(state=state, user_message="lancio [Luce]")
    luce = next(s for s in req.spellbook if s.name == "Luce")
    assert "tier 1" in luce.description


def test_global_budget_trims(tmp_path: Path, monkeypatch) -> None:
    state, engine = _seed_session(tmp_path)
    monkeypatch.setattr(settings, "narrative_token_budget", 200)
    req = engine.build_request(
        state=state,
        user_message="guardo intorno lungamente e descrivo tutto",
    )
    assert estimate_tokens(req.model_dump_json()) <= 280


def test_state_slice_smaller_than_full_dump(tmp_path: Path, monkeypatch) -> None:
    from app.services.consequence_engine import ConsequenceEngine

    state, _engine = _seed_session(tmp_path)
    eng = ConsequenceEngine(saves=SaveManager(root=tmp_path / "saves"))
    full = state.model_dump_json(indent=2)
    monkeypatch.setattr(settings, "review_state_slice", True)
    sliced = eng._format_game_state(state)
    assert len(sliced) < len(full)
    assert "characters_active" in sliced
