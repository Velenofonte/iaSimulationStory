"""Rough token estimates for context-size monitoring (not billing-accurate)."""

from __future__ import annotations

from typing import TypeVar

T = TypeVar("T")


def estimate_tokens(text: str) -> int:
    """Approx tokens for Latin/JSON prompts (~4 chars/token)."""
    if not text:
        return 0
    return max(1, (len(text) + 3) // 4)


def estimate_prompt_tokens(system: str, user: str) -> int:
    return estimate_tokens(system) + estimate_tokens(user)


def fit_text(text: str, max_tokens: int) -> str:
    """Truncate text to ~max_tokens at a word/sentence boundary.

    max_tokens <= 0 means no limit (return text unchanged).
    """
    if max_tokens <= 0 or not text:
        return text
    max_chars = max_tokens * 4
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars]
    for sep in (". ", "! ", "? ", "; ", ", ", " "):
        idx = cut.rfind(sep)
        if idx > max_chars // 2:
            return cut[: idx + len(sep)].rstrip()
    return cut.rstrip()


def fill_by_priority(items: list[T], budget: int, *, size_fn=None) -> list[T]:
    """Keep items in order until estimated size exceeds budget.

    budget <= 0 disables limiting (return all items).
    size_fn(item) -> int token estimate; default uses str(item).
    """
    if budget <= 0:
        return list(items)
    if size_fn is None:
        size_fn = lambda item: estimate_tokens(str(item))  # noqa: E731
    kept: list[T] = []
    used = 0
    for item in items:
        cost = size_fn(item)
        if kept and used + cost > budget:
            break
        if not kept and cost > budget:
            # Always keep at least the first item (caller may truncate it).
            kept.append(item)
            break
        kept.append(item)
        used += cost
    return kept
