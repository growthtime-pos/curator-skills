#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from typing import Any, Dict, Optional

from confluence_config import (
    auth_mode_candidates,
    canonical_config_path,
    detect_deployment_type,
    missing_required_fields,
    probe_config,
    resolve_saved_config,
    resolve_storage_target,
)

KNOWN_KEYS = {
    "base_url",
    "deployment_type",
    "email",
    "username",
    "api_token",
    "password",
    "insecure",
    "cache_dir",
    "cache_ttl_hours",
    "rate_limit_rps",
}


def load_config(path: str) -> Dict[str, Any]:
    probe = probe_config(path, "target")
    if not probe.exists:
        return {}
    if not probe.valid:
        raise ValueError(probe.load_error or f"설정 파일을 읽을 수 없습니다: {path}")
    return probe.config


def save_config(path: str, config: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(config, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass


def mask_secret(value: Optional[str]) -> str:
    if not value:
        return "(미설정)"
    if len(value) <= 6:
        return "***"
    return value[:3] + "***" + value[-3:]


def mask_email(value: Optional[str]) -> str:
    if not value:
        return "(미설정)"
    if "@" not in value:
        return mask_secret(value)
    local, domain = value.split("@", 1)
    if len(local) <= 2:
        local_masked = "*" * len(local)
    else:
        local_masked = local[:2] + "***"
    return f"{local_masked}@{domain}"


def masked_fields(config: Dict[str, Any]) -> Dict[str, str]:
    return {
        "email": mask_email(config.get("email")),
        "username": mask_secret(config.get("username")),
        "api_token": mask_secret(config.get("api_token")),
        "password": mask_secret(config.get("password")),
    }


def resolved_deployment(config: Dict[str, Any]) -> Optional[str]:
    deployment_hint = config.get("deployment_type") or "auto"
    base_url = config.get("base_url")
    if base_url:
        return detect_deployment_type(base_url, deployment_hint)
    if deployment_hint == "auto":
        return None
    return deployment_hint


def cmd_show(args: argparse.Namespace) -> int:
    probe = probe_config(args.config, "target")
    if not probe.exists:
        print("설정 파일이 없습니다:", args.config, file=sys.stderr)
        return 1
    if not probe.valid:
        print(f"설정 파일을 읽지 못했습니다: {args.config}", file=sys.stderr)
        print(probe.load_error or "알 수 없는 JSON 오류", file=sys.stderr)
        return 1
    config = probe.config
    if not config:
        print("설정 파일은 있지만 저장된 값이 없습니다:", args.config, file=sys.stderr)
        return 1
    print(f"설정 파일: {args.config}")
    print()
    for key in sorted(config):
        value = config[key]
        if key in ("api_token", "password"):
            print(f"  {key}: {mask_secret(value)}")
        else:
            print(f"  {key}: {value}")
    return 0


def cmd_set(args: argparse.Namespace) -> int:
    try:
        config = load_config(args.config)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    updated = False
    for pair in args.values:
        if "=" not in pair:
            print(f"잘못된 형식입니다 (key=value 필요): {pair}", file=sys.stderr)
            return 1
        key, value = pair.split("=", 1)
        if key not in KNOWN_KEYS:
            print(f"알 수 없는 설정 키입니다: {key}", file=sys.stderr)
            print(f"사용 가능한 키: {', '.join(sorted(KNOWN_KEYS))}", file=sys.stderr)
            return 1
        if key == "insecure":
            config[key] = value.lower() in ("true", "1", "yes")
        elif key in ("cache_ttl_hours",):
            config[key] = int(value)
        elif key in ("rate_limit_rps",):
            config[key] = float(value)
        else:
            config[key] = value
        updated = True
    if updated:
        save_config(args.config, config)
        print(f"설정이 저장되었습니다: {args.config}")
    return 0


def cmd_delete(args: argparse.Namespace) -> int:
    try:
        config = load_config(args.config)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    removed = False
    for key in args.keys:
        if key in config:
            del config[key]
            removed = True
            print(f"  삭제됨: {key}")
        else:
            print(f"  없는 키: {key}")
    if removed:
        save_config(args.config, config)
    return 0


def cmd_clear(args: argparse.Namespace) -> int:
    if os.path.exists(args.config):
        os.remove(args.config)
        print(f"설정 파일이 삭제되었습니다: {args.config}")
    else:
        print("삭제할 설정 파일이 없습니다.", file=sys.stderr)
    return 0


def cmd_path(args: argparse.Namespace) -> int:
    print(args.config)
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    resolved = args._resolved_config
    config = resolved.config
    deployment = resolved_deployment(config)
    deployment_for_checks = deployment or str(config.get("deployment_type") or "auto")
    status = {
        "config_found": resolved.found,
        "config_path": resolved.path,
        "config_source": resolved.source,
        "config_load_error": resolved.load_error,
        "checked_paths": [
            {
                "source": item.source,
                "path": item.path,
                "exists": item.exists,
                "valid": item.valid,
                "load_error": item.load_error,
            }
            for item in resolved.checked_paths
        ],
        "base_url": config.get("base_url"),
        "base_url_present": bool(config.get("base_url")),
        "deployment_type": config.get("deployment_type"),
        "resolved_deployment_type": deployment,
        "auth_mode_candidates": auth_mode_candidates(config, deployment_for_checks),
        "missing_required_fields": missing_required_fields(config, deployment_for_checks),
        "masked_fields": masked_fields(config),
    }
    if args.json:
        print(json.dumps(status, ensure_ascii=False, indent=2))
        return 0

    print(f"config_found: {status['config_found']}")
    print(f"config_source: {status['config_source']}")
    print(f"config_path: {status['config_path'] or '(없음)'}")
    if status["config_load_error"]:
        print(f"config_load_error: {status['config_load_error']}")
    print(f"base_url_present: {status['base_url_present']}")
    print(f"resolved_deployment_type: {status['resolved_deployment_type'] or '(미결정)'}")
    print(f"auth_mode_candidates: {', '.join(status['auth_mode_candidates']) or '(없음)'}")
    print(
        "missing_required_fields:",
        ", ".join(status["missing_required_fields"]) or "(없음)",
    )
    return 0


def parse_args() -> argparse.Namespace:
    env_config_path = os.getenv("CONFLUENCE_CONFIG_PATH")
    parser = argparse.ArgumentParser(
        description="Confluence 연결 정보를 로컬에 저장하고 관리합니다.",
    )
    parser.add_argument(
        "--config",
        help=(
            "설정 파일 경로. 지정하지 않으면 "
            f"{canonical_config_path()} 에 저장하고, status/fetch 는 legacy fallback 도 확인합니다."
        ),
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("show", help="현재 설정 조회")
    sub.add_parser("path", help="설정 파일 경로 출력")
    status_parser = sub.add_parser("status", help="fetch 가 사용할 활성 설정 상태 조회")
    status_parser.add_argument("--json", action="store_true", help="JSON 으로 상태 출력")

    set_parser = sub.add_parser("set", help="설정 값 저장 (key=value ...)")
    set_parser.add_argument("values", nargs="+", help="key=value 쌍")

    delete_parser = sub.add_parser("delete", help="특정 설정 키 삭제")
    delete_parser.add_argument("keys", nargs="+", help="삭제할 키")

    sub.add_parser("clear", help="설정 파일 전체 삭제")

    args = parser.parse_args()
    cli_config_path = args.config
    explicit_path = cli_config_path or env_config_path
    args._config_override = explicit_path
    args.config = resolve_storage_target(explicit_path)
    resolved_source = "cli_path" if cli_config_path else "env_path"
    args._resolved_config = resolve_saved_config(
        explicit_path=args._config_override,
        explicit_source=resolved_source,
    )
    return args


def main() -> int:
    args = parse_args()
    if not args.command:
        print("사용법: configure_confluence.py {show|set|delete|clear|path|status}", file=sys.stderr)
        print()
        print("예시:")
        print("  python configure_confluence.py set base_url=https://wiki.example.com username=user1 password=pass123 insecure=true")
        print("  python configure_confluence.py status --json")
        print("  python configure_confluence.py show")
        print("  python configure_confluence.py delete password")
        print("  python configure_confluence.py clear")
        return 1
    dispatch = {
        "show": cmd_show,
        "set": cmd_set,
        "delete": cmd_delete,
        "clear": cmd_clear,
        "path": cmd_path,
        "status": cmd_status,
    }
    return dispatch[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
