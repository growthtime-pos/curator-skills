#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional


def iso_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def repo_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def default_data_dir() -> str:
    return os.path.join(repo_root(), "data")


def slugify_timestamp(value: str) -> str:
    return value.replace(":", "").replace("-", "").replace("+", "_")


def write_json(path: str, payload: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def read_json_if_exists(path: str) -> Optional[Dict[str, Any]]:
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def feature_dir(data_dir: str, feature_name: str) -> str:
    return os.path.join(data_dir, "features", feature_name)


def stage_dir(data_dir: str, stage_name: str) -> str:
    return os.path.join(data_dir, "artifacts", stage_name)


def persist_feature_state(
    data_dir: str,
    feature_name: str,
    payload: Dict[str, Any],
    generated_at: Optional[str] = None,
) -> Dict[str, str]:
    generated = generated_at or ((payload.get("meta") or {}).get("generated_at")) or iso_now()
    base_dir = feature_dir(data_dir, feature_name)
    latest_path = os.path.join(base_dir, "latest.json")
    history_path = os.path.join(base_dir, "history", f"{slugify_timestamp(generated)}.json")
    wrapped = {
        "meta": {
            "feature_name": feature_name,
            "generated_at": generated,
            "data_dir": os.path.abspath(data_dir),
        },
        "payload": payload,
    }
    write_json(latest_path, wrapped)
    write_json(history_path, wrapped)
    return {
        "latest_path": os.path.abspath(latest_path),
        "history_path": os.path.abspath(history_path),
    }


def persist_stage_artifact(
    data_dir: str,
    stage_name: str,
    payload: Dict[str, Any],
    generated_at: Optional[str] = None,
    suffix: str = "json",
) -> str:
    generated = generated_at or ((payload.get("meta") or {}).get("generated_at")) or iso_now()
    output_path = os.path.join(stage_dir(data_dir, stage_name), f"{slugify_timestamp(generated)}.{suffix}")
    write_json(output_path, payload)
    return os.path.abspath(output_path)
