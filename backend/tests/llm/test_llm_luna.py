"""GPT-5.6 Luna / DeepSeek: disable reasoning and pin JSON output."""

from __future__ import annotations

from types import SimpleNamespace

from app.models.turn import NarrativeRenderResult, TurnResolution
from app.services.llm_client import (
    _is_deepseek_model,
    _is_gpt56_luna,
    _json_schema_response_format,
    _message_text,
    _openai_chat_kwargs,
    _should_disable_reasoning,
)


def test_detects_luna_slugs() -> None:
    assert _is_gpt56_luna("openai/gpt-5.6-luna")
    assert _is_gpt56_luna("openai/gpt-5.6-luna-pro")
    assert _is_gpt56_luna("~openai/gpt-5.6-luna")
    assert _is_gpt56_luna("gpt-5.6-luna")
    assert not _is_gpt56_luna("openai/gpt-4.1-mini")
    assert not _is_gpt56_luna("deepseek/deepseek-v4-flash-0731")


def test_detects_deepseek_and_reasoning_off() -> None:
    assert _is_deepseek_model("deepseek/deepseek-v4-flash-0731")
    assert _should_disable_reasoning("openai/gpt-5.6-luna")
    assert _should_disable_reasoning("deepseek/deepseek-v4-flash-0731")
    assert not _should_disable_reasoning("openai/gpt-4.1-mini")


def test_luna_complete_disables_reasoning_without_schema() -> None:
    kwargs = _openai_chat_kwargs(
        model="openai/gpt-5.6-luna",
        system="sys",
        user="usr",
        temperature=0.3,
    )
    assert kwargs["extra_body"]["reasoning"] == {"enabled": False, "effort": "none"}
    assert kwargs["extra_body"]["provider"]["ignore"] == ["OpenAI Flex"]
    assert kwargs["extra_body"]["provider"]["sort"] == "latency"
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
    assert kwargs["extra_body"]["reasoning"]["enabled"] is False


def test_deepseek_render_forces_json_object_and_disables_thinking() -> None:
    kwargs = _openai_chat_kwargs(
        model="deepseek/deepseek-v4-flash-0731",
        system="sys",
        user="usr",
        temperature=0.8,
        response_schema=NarrativeRenderResult,
    )
    assert kwargs["response_format"] == {"type": "json_object"}
    assert kwargs["extra_body"]["reasoning"]["enabled"] is False
    assert kwargs["extra_body"]["thinking"] == {"type": "disabled"}
    assert kwargs["extra_body"]["provider"]["sort"] == "latency"
    assert "ignore" not in kwargs["extra_body"]["provider"]


def test_mini_has_no_reasoning_or_schema() -> None:
    kwargs = _openai_chat_kwargs(
        model="openai/gpt-4.1-mini",
        system="sys",
        user="usr",
        temperature=0.2,
        response_schema=TurnResolution,
    )
    assert "response_format" not in kwargs
    assert kwargs["extra_body"]["provider"]["sort"] == "latency"
    assert "reasoning" not in kwargs["extra_body"]


def test_json_schema_format_is_not_strict() -> None:
    fmt = _json_schema_response_format(NarrativeRenderResult)
    assert fmt["json_schema"]["strict"] is False
    assert fmt["json_schema"]["schema"]["properties"]["text"]["type"] == "string"


def test_message_text_falls_back_to_reasoning_content() -> None:
    empty = SimpleNamespace(content="", reasoning_content='{"text": "ok"}', parsed=None)
    assert _message_text(empty) == '{"text": "ok"}'
    filled = SimpleNamespace(content='{"text": "hi"}', reasoning_content="ignore")
    assert _message_text(filled) == '{"text": "hi"}'
