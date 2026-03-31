#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from typing import Any, Dict, Optional

DEFAULT_CONFIG_PATH = os.path.expanduser("~/.confluence-curation.json")

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
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


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


def cmd_show(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    if not config:
        print("설정 파일이 없습니다:", args.config, file=sys.stderr)
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
    config = load_config(args.config)
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
    config = load_config(args.config)
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Confluence 연결 정보를 로컬에 저장하고 관리합니다.",
    )
    parser.add_argument(
        "--config",
        default=os.getenv("CONFLUENCE_CONFIG_PATH", DEFAULT_CONFIG_PATH),
        help=f"설정 파일 경로 (기본: {DEFAULT_CONFIG_PATH})",
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("show", help="현재 설정 조회")
    sub.add_parser("path", help="설정 파일 경로 출력")

    set_parser = sub.add_parser("set", help="설정 값 저장 (key=value ...)")
    set_parser.add_argument("values", nargs="+", help="key=value 쌍")

    delete_parser = sub.add_parser("delete", help="특정 설정 키 삭제")
    delete_parser.add_argument("keys", nargs="+", help="삭제할 키")

    sub.add_parser("clear", help="설정 파일 전체 삭제")

    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.command:
        print("사용법: configure_confluence.py {show|set|delete|clear|path}", file=sys.stderr)
        print()
        print("예시:")
        print("  python configure_confluence.py set base_url=https://wiki.example.com username=user1 password=pass123 insecure=true")
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
    }
    return dispatch[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
