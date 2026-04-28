#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from typing import Any, Dict, List


def registry_path() -> str:
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "pipeline",
        "stage_registry.json",
    )


def load_stage_registry(path: str | None = None) -> Dict[str, Any]:
    resolved = path or registry_path()
    with open(resolved, "r", encoding="utf-8") as handle:
        return json.load(handle)


def stage_order(registry: Dict[str, Any]) -> List[str]:
    return [stage["id"] for stage in registry.get("stages", [])]


def stage_by_id(registry: Dict[str, Any], stage_id: str) -> Dict[str, Any]:
    for stage in registry.get("stages", []):
        if stage.get("id") == stage_id:
            return stage
    raise KeyError(f"Unknown stage id: {stage_id}")


def method_ids(stage: Dict[str, Any]) -> List[str]:
    return [method["id"] for method in stage.get("methods", [])]


def method_by_id(stage: Dict[str, Any], method_id: str) -> Dict[str, Any]:
    for method in stage.get("methods", []):
        if method.get("id") == method_id:
            return method
    raise KeyError(f"Unknown method id for {stage.get('id')}: {method_id}")


def default_method_for_purpose(stage: Dict[str, Any], purpose: str) -> str:
    defaults = stage.get("default_method_by_purpose", {})
    default = defaults.get(purpose) or defaults.get("general")
    if not default:
        raise KeyError(f"No default method configured for {stage.get('id')}")
    return default


def validate_selection(registry: Dict[str, Any], stage_id: str, method_id: str) -> None:
    stage = stage_by_id(registry, stage_id)
    if method_id not in method_ids(stage):
        options = ", ".join(method_ids(stage))
        raise ValueError(f"Invalid method `{method_id}` for {stage_id}. Valid options: {options}")
