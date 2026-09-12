"""GPT-5.6 Luna: disable reasoning and pin json_schema on structured calls."""

from __future__ import annotations

from app.models.turn import NarrativeRenderResult, TurnResolution
from app.services.llm_client import (
    _is_gpt56_luna,
    _json_schema_response_format,
    _openai_chat_kwargs,
)


def test_detects_luna_slugs() -> None:
    assert _is_gpt56_luna("openai/gpt-5.6-luna")
    assert _is_gpt56_luna("openai/gpt-5.6-luna-pro")
    assert _is_gpt56_luna("~openai/gpt-5.6-luna")
    assert _is_gpt56_luna("gpt-5.6-luna")
    assert not _is_gpt56_luna("openai/gpt-4.1-mini")
    assert not _is_gpt56_luna("deepseek/deepseek-v4-flash-0731")


def test_luna_complete_disables_reasoning_without_schema() -> None:
    kwargs = _openai_chat_kwargs(
        model="openai/gpt-5.6-luna",
        system="sys",
        user="usr",
        temperature=0.3,
    )
    assert kwargs["extra_body"]["reasoning"] == {"effort": "none"}
    assert "response_format" not in kwargs


def test_luna_complete_json_adds_json_schema() -> None:
    kwargs = _openai_chat_kwargs(
        model="openai/gpt-5.6-luna",
        system="sys",
        user="usr",
        temperature=0.3,
        response_schema=TurnResolution,
    )
    fmt = kwargs["response_format"]
    assert fmt["type"] == "json_schema"
    assert fmt["json_schema"]["name"] == "TurnResolution"
    assert fmt["json_schema"]["strict"] is False
    schema = fmt["json_schema"]["schema"]
    assert "present_leave" in schema["properties"]
    assert kwargs["extra_body"]["reasoning"] == {"effort": "none"}


def test_non_luna_has_no_reasoning_or_schema() -> None:
    kwargs = _openai_chat_kwargs(
        model="deepseek/deepseek-v4-flash-0731",
        system="sys",
        user="usr",
        temperature=0.8,
        response_schema=NarrativeRenderResult,
    )
    assert "extra_body" not in kwargs
    assert "response_format" not in kwargs


def test_json_schema_format_is_not_strict() -> None:
    fmt = _json_schema_response_format(NarrativeRenderResult)
    assert fmt["json_schema"]["strict"] is False
    assert fmt["json_schema"]["schema"]["properties"]["text"]["type"] == "string"
