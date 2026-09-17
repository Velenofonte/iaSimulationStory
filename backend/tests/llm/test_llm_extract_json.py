"""Tests for LLM JSON extraction (lenient with LLM quirks)."""

from __future__ import annotations

import json

import pytest

from app.services.llm_client import LLMClient


def test_extract_json_escapes_literal_newlines_in_strings() -> None:
    raw = '{\n  "text": "Ciao\nmondo e «dialogo»"\n}'
    payload = LLMClient().extract_json(raw)
    assert payload["text"] == "Ciao\nmondo e «dialogo»"


def test_extract_json_escapes_tabs_and_other_controls() -> None:
    raw = '{"text": "a\tb\x01c"}'
    payload = LLMClient().extract_json(raw)
    assert payload["text"] == "a\tb\x01c"


def test_extract_json_still_parses_valid_json() -> None:
    raw = '```json\n{"text": "ok", "n": 1}\n```'
    payload = LLMClient().extract_json(raw)
    assert payload == {"text": "ok", "n": 1}


def test_extract_json_rejects_non_object() -> None:
    with pytest.raises(json.JSONDecodeError):
        LLMClient().extract_json("not json at all")
