"""Load story-local episode / notoriety packs with agnostic engine defaults."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from app.config import settings

# Generic defaults: no setting lore. Story packs override.
_DEFAULT_TIERS: dict[int, str] = {
    0: "niente",
    1: "segno",
    2: "gancio",
    3: "frizione",
    4: "complicazione",
    5: "minaccia",
    6: "svolta",
}

_DEFAULT_LOCATION_KINDS: dict[str, list[float]] = {
    "default": [61, 0, 16, 10, 7, 4, 2],
    "settlement": [56, 0, 24, 12, 5, 2, 1],
    "inn": [52, 0, 28, 15, 4, 1, 0.2],
    "road": [53, 0, 15, 12, 12, 7, 1],
    "wilderness": [41, 0, 11, 8, 16, 18, 6],
    "outpost": [50, 0, 15, 10, 14, 9, 2],
    "ruin": [44, 0, 14, 10, 15, 12, 5],
}

_DEFAULT_MODIFIERS: dict[str, list[float]] = {
    "night": [0.7, 0.0, 0.7, 0.9, 1.2, 1.5, 1.3],
    "alone": [1.0, 0.0, 0.5, 0.6, 1.1, 1.4, 1.1],
    "indoor": [1.1, 0.0, 1.3, 1.3, 0.8, 0.5, 0.4],
    "stance_wait": [0.35, 0.0, 1.2, 1.2, 1.3, 1.4, 1.2],
    "stance_wait_repeat": [6.0, 0.0, 0.5, 0.4, 0.3, 0.2, 0.15],
    "stance_dialogue": [3.0, 0.0, 0.6, 0.5, 0.35, 0.2, 0.12],
    "cooldown": [3.0, 0.0, 0.5, 0.45, 0.3, 0.15, 0.1],
    "quiet_streak": [0.85, 0.0, 1.1, 1.1, 1.15, 1.2, 1.15],
    "baseline_calm": [1.15, 0.0, 1.05, 0.95, 0.95, 0.95, 0.95],
}

_DEFAULT_KINDS: dict[str, dict[str, Any]] = {
    "threat": {
        "tiers": [4, 5, 6],
        "by_location": {
            "default": 1.0,
            "settlement": 0.4,
            "inn": 0.2,
            "road": 1.2,
            "wilderness": 1.8,
            "outpost": 1.1,
            "ruin": 1.4,
        },
    },
    "social": {
        "tiers": [2, 3, 4],
        "by_location": {
            "default": 1.0,
            "settlement": 1.5,
            "inn": 2.0,
            "road": 0.6,
            "wilderness": 0.2,
            "outpost": 0.7,
            "ruin": 0.4,
        },
    },
    "discovery": {
        "tiers": [2, 4],
        "by_location": {
            "default": 1.0,
            "settlement": 0.6,
            "inn": 0.4,
            "road": 1.0,
            "wilderness": 1.3,
            "outpost": 1.1,
            "ruin": 1.6,
        },
    },
    "arrival": {
        "tiers": [2, 3, 4, 5],
        "by_location": {
            "default": 1.0,
            "settlement": 1.2,
            "inn": 1.3,
            "road": 0.8,
            "wilderness": 0.5,
            "outpost": 1.4,
            "ruin": 0.7,
        },
    },
    "environmental": {
        "tiers": [3, 4, 5],
        "by_location": {
            "default": 1.0,
            "settlement": 0.5,
            "inn": 0.3,
            "road": 1.1,
            "wilderness": 1.5,
            "outpost": 1.0,
            "ruin": 1.2,
        },
    },
    "opportunity": {
        "tiers": [2, 3],
        "by_location": {
            "default": 1.0,
            "settlement": 1.4,
            "inn": 1.6,
            "road": 0.7,
            "wilderness": 0.3,
            "outpost": 0.8,
            "ruin": 0.5,
        },
    },
    "mystery": {
        "tiers": [2, 4, 6],
        "by_location": {
            "default": 1.0,
            "settlement": 0.8,
            "inn": 0.7,
            "road": 0.9,
            "wilderness": 1.2,
            "outpost": 1.3,
            "ruin": 1.5,
        },
    },
}

_DEFAULT_NOTORIETY_KIND_WEIGHTS: dict[str, dict[str, float]] = {
    "low": {
        "social": 1.2,
        "opportunity": 1.3,
        "discovery": 1.1,
        "threat": 0.8,
        "arrival": 1.0,
        "environmental": 1.0,
        "mystery": 0.9,
    },
    "high": {
        "social": 0.7,
        "opportunity": 0.6,
        "discovery": 0.8,
        "threat": 0.9,
        "arrival": 1.4,
        "environmental": 0.7,
        "mystery": 1.5,
    },
    "gap_high": {
        "social": 0.8,
        "opportunity": 0.7,
        "discovery": 0.9,
        "threat": 0.8,
        "arrival": 1.3,
        "environmental": 0.6,
        "mystery": 1.6,
    },
}

_DEFAULT_EXPOSURE: dict[str, Any] = {
    "witness_reach": {
        "civilian": "local",
        "merchant": "city",
        "adventurer": "city",
        "guard": "city",
        "clerk": "city",
        "noble": "region",
        "priest": "region",
        "officer": "region",
        "agent": "nation",
    },
    "thresholds": {"low": 0, "medium": 2, "high": 5},
}

_DEFAULT_SCALE_BANDS: dict[str, dict[str, Any]] = {
    "F": {"weight": 1, "expected_label_rank": 0},
    "E": {"weight": 2, "expected_label_rank": 1},
    "D": {"weight": 4, "expected_label_rank": 2},
    "C": {"weight": 8, "expected_label_rank": 3},
    "B": {"weight": 16, "expected_label_rank": 4},
    "A": {"weight": 32, "expected_label_rank": 5},
    "A+": {"weight": 48, "expected_label_rank": 6},
    "A++": {"weight": 72, "expected_label_rank": 7},
    "100+": {"weight": 120, "expected_label_rank": 8},
}

_DEFAULT_FORMAL_LABELS: dict[str, int] = {
    "copper": 0,
    "iron": 1,
    "silver": 2,
    "gold": 3,
    "platinum": 4,
    "mithril": 5,
    "orichalcum": 6,
    "adamantite": 7,
}

_DEFAULT_REACH_ORDER = ["none", "local", "city", "region", "nation", "beyond"]

_DEFAULT_BENEFICIARY_REACH: dict[str, str] = {
    "none": "none",
    "civilian": "local",
    "merchant": "city",
    "noble": "region",
    "faction": "nation",
    "nation": "beyond",
}

_DEFAULT_DECAY: dict[str, Any] = {
    "score_per_day": 0.5,
    "legend_per_day": 0.2,
    "persistent_evidence_exempt": True,
}

_TIER_COUNT = 7


def _as_tier_vector(raw: Any, *, fallback: list[float] | None = None) -> list[float]:
    base = list(fallback or [1.0] * _TIER_COUNT)
    if isinstance(raw, dict):
        out = list(base)
        for key, val in raw.items():
            try:
                idx = int(key)
            except (TypeError, ValueError):
                continue
            if 0 <= idx < _TIER_COUNT:
                out[idx] = float(val)
        return out
    if isinstance(raw, list) and raw:
        out = [float(x) for x in raw[:_TIER_COUNT]]
        while len(out) < _TIER_COUNT:
            out.append(base[len(out)])
        return out
    return base


def _merge_dict(base: dict[str, Any], overlay: dict[str, Any] | None) -> dict[str, Any]:
    out = deepcopy(base)
    if not isinstance(overlay, dict):
        return out
    for key, val in overlay.items():
        if isinstance(val, dict) and isinstance(out.get(key), dict):
            out[key] = _merge_dict(out[key], val)
        else:
            out[key] = deepcopy(val)
    return out


@dataclass
class EpisodePack:
    tiers: dict[int, str] = field(default_factory=lambda: dict(_DEFAULT_TIERS))
    location_kinds: dict[str, list[float]] = field(
        default_factory=lambda: deepcopy(_DEFAULT_LOCATION_KINDS)
    )
    modifiers: dict[str, list[float]] = field(
        default_factory=lambda: deepcopy(_DEFAULT_MODIFIERS)
    )
    kinds: dict[str, dict[str, Any]] = field(
        default_factory=lambda: deepcopy(_DEFAULT_KINDS)
    )
    notoriety_kind_weights: dict[str, dict[str, float]] = field(
        default_factory=lambda: deepcopy(_DEFAULT_NOTORIETY_KIND_WEIGHTS)
    )
    exposure: dict[str, Any] = field(default_factory=lambda: deepcopy(_DEFAULT_EXPOSURE))
    scale_bands: dict[str, dict[str, Any]] = field(
        default_factory=lambda: deepcopy(_DEFAULT_SCALE_BANDS)
    )
    formal_labels: dict[str, int] = field(
        default_factory=lambda: dict(_DEFAULT_FORMAL_LABELS)
    )
    reach_order: list[str] = field(default_factory=lambda: list(_DEFAULT_REACH_ORDER))
    beneficiary_reach: dict[str, str] = field(
        default_factory=lambda: dict(_DEFAULT_BENEFICIARY_REACH)
    )
    decay: dict[str, Any] = field(default_factory=lambda: dict(_DEFAULT_DECAY))

    def tier_label(self, tier: int) -> str:
        return self.tiers.get(int(tier), str(tier))

    def location_profile(self, location_kind: str | None) -> list[float]:
        key = (location_kind or "default").strip().lower() or "default"
        if key in self.location_kinds:
            return list(self.location_kinds[key])
        return list(self.location_kinds.get("default", _DEFAULT_LOCATION_KINDS["default"]))

    def modifier(self, name: str) -> list[float] | None:
        vec = self.modifiers.get(name)
        return list(vec) if vec else None

    def scale_weight(self, band: str) -> float:
        entry = self.scale_bands.get(band) or {}
        try:
            return float(entry.get("weight") or 0)
        except (TypeError, ValueError):
            return 0.0

    def expected_label_rank(self, band: str) -> int:
        entry = self.scale_bands.get(band) or {}
        try:
            return int(entry.get("expected_label_rank") or 0)
        except (TypeError, ValueError):
            return 0

    def label_rank(self, label: str) -> int | None:
        key = (label or "").strip().lower()
        if key not in self.formal_labels:
            return None
        return int(self.formal_labels[key])

    def reach_index(self, reach: str) -> int:
        key = (reach or "none").strip().lower()
        try:
            return self.reach_order.index(key)
        except ValueError:
            return 0

    def max_reach(self, reaches: list[str]) -> str:
        if not reaches:
            return "none"
        best = max(reaches, key=self.reach_index)
        return best if best in self.reach_order else "none"


def parse_episode_pack(data: dict[str, Any] | None) -> EpisodePack:
    raw = data if isinstance(data, dict) else {}
    tiers_raw = raw.get("tiers") or {}
    tiers: dict[int, str] = dict(_DEFAULT_TIERS)
    if isinstance(tiers_raw, dict):
        for key, label in tiers_raw.items():
            try:
                tiers[int(key)] = str(label)
            except (TypeError, ValueError):
                continue

    location_kinds = deepcopy(_DEFAULT_LOCATION_KINDS)
    for key, vec in (raw.get("location_kinds") or {}).items():
        location_kinds[str(key)] = _as_tier_vector(
            vec, fallback=location_kinds.get("default")
        )

    modifiers = deepcopy(_DEFAULT_MODIFIERS)
    for key, vec in (raw.get("modifiers") or {}).items():
        modifiers[str(key)] = _as_tier_vector(vec, fallback=[1.0] * _TIER_COUNT)

    kinds = deepcopy(_DEFAULT_KINDS)
    for key, spec in (raw.get("kinds") or {}).items():
        if not isinstance(spec, dict):
            continue
        base = deepcopy(kinds.get(str(key), {"tiers": [1, 2, 3], "by_location": {}}))
        if "tiers" in spec and isinstance(spec["tiers"], list):
            base["tiers"] = [int(x) for x in spec["tiers"]]
        if isinstance(spec.get("by_location"), dict):
            base["by_location"] = {
                **base.get("by_location", {}),
                **{str(k): float(v) for k, v in spec["by_location"].items()},
            }
        kinds[str(key)] = base

    notoriety_kind_weights = _merge_dict(
        _DEFAULT_NOTORIETY_KIND_WEIGHTS, raw.get("notoriety_kind_weights")
    )
    exposure = _merge_dict(_DEFAULT_EXPOSURE, raw.get("exposure"))
    scale_bands = _merge_dict(_DEFAULT_SCALE_BANDS, raw.get("scale_bands"))
    formal_labels = dict(_DEFAULT_FORMAL_LABELS)
    for key, rank in (raw.get("formal_labels") or {}).items():
        try:
            formal_labels[str(key).lower()] = int(rank)
        except (TypeError, ValueError):
            continue
    reach_order = list(raw.get("reach_order") or _DEFAULT_REACH_ORDER)
    beneficiary_reach = dict(_DEFAULT_BENEFICIARY_REACH)
    for key, reach in (raw.get("beneficiary_reach") or {}).items():
        beneficiary_reach[str(key)] = str(reach)
    decay = {**_DEFAULT_DECAY, **(raw.get("decay") or {})}

    return EpisodePack(
        tiers=tiers,
        location_kinds=location_kinds,
        modifiers=modifiers,
        kinds=kinds,
        notoriety_kind_weights=notoriety_kind_weights,
        exposure=exposure,
        scale_bands=scale_bands,
        formal_labels=formal_labels,
        reach_order=[str(x) for x in reach_order],
        beneficiary_reach=beneficiary_reach,
        decay=decay,
    )


class EpisodePackLoader:
    def __init__(self) -> None:
        self._cache: dict[str, EpisodePack] = {}

    def load(self, story_id: str, *, force: bool = False) -> EpisodePack:
        key = (story_id or "").strip() or settings.default_story_id
        if not force and key in self._cache:
            return self._cache[key]
        path = settings.story_dir(key) / "events.yaml"
        data: dict[str, Any] | None = None
        if path.is_file():
            loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = loaded
        pack = parse_episode_pack(data)
        self._cache[key] = pack
        return pack

    def clear_cache(self) -> None:
        self._cache.clear()


_default_loader = EpisodePackLoader()


def load_episode_pack(story_id: str, *, force: bool = False) -> EpisodePack:
    return _default_loader.load(story_id, force=force)


def default_episode_pack() -> EpisodePack:
    return parse_episode_pack(None)
