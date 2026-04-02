#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from urllib import parse


LEGACY_CONFIG_PATH = os.path.expanduser("~/.confluence-curation.json")


@dataclass
class ConfigProbe:
    source: str
    path: str
    exists: bool
    valid: bool
    config: Dict[str, Any]
    load_error: Optional[str] = None


@dataclass
class ResolvedConfig:
    source: str
    path: Optional[str]
    found: bool
    config: Dict[str, Any]
    checked_paths: List[ConfigProbe]
    load_error: Optional[str] = None


def xdg_config_home() -> str:
    return os.path.expanduser(os.getenv("XDG_CONFIG_HOME") or "~/.config")


def canonical_config_path() -> str:
    return os.path.join(xdg_config_home(), "confluence-curation", "config.json")


def resolve_storage_target(explicit_path: Optional[str] = None) -> str:
    if explicit_path:
        return os.path.expanduser(explicit_path)
    return canonical_config_path()


def probe_config(path: str, source: str) -> ConfigProbe:
    expanded = os.path.expanduser(path)
    if not os.path.exists(expanded):
        return ConfigProbe(
            source=source,
            path=expanded,
            exists=False,
            valid=False,
            config={},
        )
    try:
        with open(expanded, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        return ConfigProbe(
            source=source,
            path=expanded,
            exists=True,
            valid=False,
            config={},
            load_error=str(exc),
        )
    if not isinstance(data, dict):
        return ConfigProbe(
            source=source,
            path=expanded,
            exists=True,
            valid=False,
            config={},
            load_error="설정 파일 최상위 값은 JSON object 여야 합니다.",
        )
    return ConfigProbe(
        source=source,
        path=expanded,
        exists=True,
        valid=True,
        config=data,
    )


def resolve_saved_config(explicit_path: Optional[str] = None, explicit_source: str = "env_path") -> ResolvedConfig:
    checked_paths: List[ConfigProbe] = []
    if explicit_path:
        candidates = [(explicit_source, resolve_storage_target(explicit_path))]
    else:
        candidates = [
            ("xdg", canonical_config_path()),
            ("legacy", LEGACY_CONFIG_PATH),
        ]

    for source, path in candidates:
        probe = probe_config(path, source)
        checked_paths.append(probe)
        if not probe.exists:
            continue
        return ResolvedConfig(
            source=probe.source,
            path=probe.path,
            found=bool(probe.valid and probe.config),
            config=probe.config if probe.valid else {},
            checked_paths=checked_paths,
            load_error=probe.load_error,
        )

    return ResolvedConfig(
        source="none",
        path=None,
        found=False,
        config={},
        checked_paths=checked_paths,
    )


def config_str(config: Dict[str, Any], key: str, env_key: Optional[str] = None) -> Optional[str]:
    if env_key:
        env_val = os.getenv(env_key)
        if env_val:
            return env_val
    return config.get(key)


def detect_deployment_type(base_url: str, requested: str) -> str:
    if requested != "auto":
        return requested
    parsed = parse.urlparse(base_url)
    host = (parsed.netloc or "").lower()
    if "atlassian.net" in host:
        return "cloud"
    return "server"


def auth_mode_candidates(config: Dict[str, Any], deployment_type: str) -> List[str]:
    candidates: List[str] = []
    email = str(config.get("email") or "")
    username = str(config.get("username") or "")
    api_token = str(config.get("api_token") or "")
    password = str(config.get("password") or "")

    def add(name: str) -> None:
        if name not in candidates:
            candidates.append(name)

    if deployment_type == "cloud":
        if email and api_token:
            add("basic_api_token")
        return candidates

    token_user = username or email
    if api_token and token_user:
        add("basic_api_token")
    if api_token:
        add("bearer_token")
    if username and password:
        add("basic_password")
    return candidates


def missing_required_fields(config: Dict[str, Any], deployment_type: str) -> List[str]:
    missing: List[str] = []
    base_url = str(config.get("base_url") or "")
    email = str(config.get("email") or "")
    username = str(config.get("username") or "")
    api_token = str(config.get("api_token") or "")
    password = str(config.get("password") or "")

    if not base_url:
        missing.append("base_url")

    if deployment_type == "cloud":
        if not email:
            missing.append("email")
        if not api_token:
            missing.append("api_token")
        return missing

    if api_token:
        return missing
    if password and not username:
        missing.append("username")
        return missing
    if username and not password:
        missing.append("password_or_api_token")
        return missing
    if not username and not password:
        missing.append("api_token_or_username_password")
    return missing
