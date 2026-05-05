#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import ssl
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from html import unescape
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib import error, parse, request

from confluence_config import config_str, detect_deployment_type, resolve_saved_config
from data_store import default_data_dir, persist_feature_state, read_json_if_exists, write_json


MAX_RPS = 1.0
VERSION_LIMIT = 5
TRANSIENT_STATUSES = {429, 500, 502, 503, 504}


def iso_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def parse_query_terms(query: Optional[str]) -> List[str]:
    if not query:
        return []
    return [term.strip().lower() for term in re.split(r"\s*\|\s*|,", query) if term.strip()]


def escape_cql_term(term: str) -> str:
    return term.replace("\\", "\\\\").replace('"', '\\"')


def build_cql_query(query: str) -> str:
    terms = parse_query_terms(query)
    if not terms:
        escaped = escape_cql_term(query.strip())
        return f'text ~ "{escaped}" or title ~ "{escaped}"'
    clauses: List[str] = []
    for term in terms:
        escaped = escape_cql_term(term)
        clauses.append(f'text ~ "{escaped}"')
        clauses.append(f'title ~ "{escaped}"')
    return " or ".join(clauses)


def parse_args() -> argparse.Namespace:
    config_override = os.getenv("CONFLUENCE_CONFIG_PATH")
    resolved_config = resolve_saved_config(
        explicit_path=config_override,
        explicit_source="env_path",
    )
    config = resolved_config.config

    parser = argparse.ArgumentParser(description="Fetch Confluence pages and profile hints.")
    parser.add_argument("--base-url", default=config_str(config, "base_url", "CONFLUENCE_BASE_URL"))
    parser.add_argument(
        "--deployment-type",
        default=os.getenv("CONFLUENCE_DEPLOYMENT_TYPE") or config.get("deployment_type", "auto"),
        choices=["auto", "cloud", "server", "datacenter"],
    )
    parser.add_argument("--email", default=config_str(config, "email", "CONFLUENCE_EMAIL"))
    parser.add_argument("--username", default=config_str(config, "username", "CONFLUENCE_USERNAME"))
    parser.add_argument("--api-token", default=config_str(config, "api_token", "CONFLUENCE_API_TOKEN"))
    parser.add_argument("--password", default=config_str(config, "password", "CONFLUENCE_PASSWORD"))
    parser.add_argument("--space-key")
    parser.add_argument("--root-page-id")
    parser.add_argument("--all-spaces", action="store_true", help="Search across all accessible spaces.")
    parser.add_argument("--query", help="Keyword query to filter relevant pages by title or body excerpt.")
    parser.add_argument("--label")
    parser.add_argument("--days", type=int)
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--include-body", action="store_true")
    insecure_default = config.get("insecure", False)
    parser.add_argument(
        "--insecure",
        action="store_true",
        default=insecure_default,
        help="Disable SSL certificate verification for testing.",
    )
    parser.add_argument(
        "--cache-dir",
        default=os.getenv("CONFLUENCE_CACHE_DIR") or config.get("cache_dir", os.path.expanduser("~/.confluence-curation-cache")),
        help="Directory used to persist fetched results for reuse.",
    )
    parser.add_argument(
        "--data-dir",
        default=os.getenv("CONFLUENCE_DATA_DIR") or default_data_dir(),
        help="Directory used to persist reusable page snapshots and pipeline artifacts.",
    )
    parser.add_argument(
        "--cache-ttl-hours",
        type=int,
        default=int(os.getenv("CONFLUENCE_CACHE_TTL_HOURS") or config.get("cache_ttl_hours", 24)),
        help="Reuse cache younger than this many hours unless --refresh-cache is used.",
    )
    parser.add_argument("--refresh-cache", action="store_true", help="Ignore existing cache and fetch fresh data.")
    parser.add_argument("--cache-only", action="store_true", help="Use cached data only and fail if cache is missing.")
    parser.add_argument(
        "--rate-limit-rps",
        type=float,
        default=float(os.getenv("CONFLUENCE_RATE_LIMIT_RPS") or config.get("rate_limit_rps", 1.0)),
    )
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    args._config_path = resolved_config.path
    args._config_source = resolved_config.source
    args._config_used = resolved_config.found
    args._config_load_error = resolved_config.load_error

    if not args.base_url:
        config_hint = args._config_path or "canonical/legacy 설정 파일 없음"
        if args._config_load_error:
            parser.error(
                "--base-url or CONFLUENCE_BASE_URL is required. "
                f"설정 파일을 읽지 못했습니다 ({config_hint}): {args._config_load_error}"
            )
        parser.error(
            "--base-url or CONFLUENCE_BASE_URL is required "
            f"(또는 configure_confluence.py 로 설정, 확인한 설정 소스={args._config_source}, 경로={config_hint})"
        )
    if not args.space_key and not args.root_page_id and not args.all_spaces:
        parser.error("--space-key, --root-page-id, or --all-spaces is required")
    if args.rate_limit_rps <= 0 or args.rate_limit_rps > MAX_RPS:
        parser.error("--rate-limit-rps must be > 0 and <= 1.0")
    return args


class FetchError(RuntimeError):
    pass


class RateLimiter:
    def __init__(self, rps: float) -> None:
        self.min_interval = 1.0 / rps
        self._last_time = 0.0

    def wait(self) -> None:
        now = time.monotonic()
        delay = self.min_interval - (now - self._last_time)
        if delay > 0:
            time.sleep(delay)
        self._last_time = time.monotonic()


@dataclass
class AuthConfig:
    deployment_type: str
    headers: Dict[str, str]
    auth_used: str


def _basic_auth_header(username: str, secret: str) -> str:
    token = base64.b64encode(f"{username}:{secret}".encode("utf-8")).decode("ascii")
    return f"Basic {token}"


class ConfluenceClient:
    def __init__(
        self,
        base_url: str,
        auth: AuthConfig,
        limiter: RateLimiter,
        warnings: List[str],
        insecure: bool = False,
    ):
        self.base_url = base_url.rstrip("/")
        self.auth = auth
        self.limiter = limiter
        self.warnings = warnings
        self.request_count = 0
        self.ssl_context = None
        if insecure:
            self.ssl_context = ssl._create_unverified_context()

    def build_url(self, path: str, params: Optional[Dict[str, Any]] = None) -> str:
        url = f"{self.base_url}{path}"
        if params:
            pairs = [(k, v) for k, v in params.items() if v is not None]
            url = f"{url}?{parse.urlencode(pairs, doseq=True)}"
        return url

    def get_json(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        last_error: Optional[Exception] = None
        for attempt in range(4):
            self.limiter.wait()
            self.request_count += 1
            req = request.Request(
                self.build_url(path, params),
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    **self.auth.headers,
                },
            )
            try:
                with request.urlopen(req, timeout=30, context=self.ssl_context) as resp:
                    charset = resp.headers.get_content_charset() or "utf-8"
                    return json.loads(resp.read().decode(charset))
            except error.HTTPError as exc:
                if exc.code in TRANSIENT_STATUSES and attempt < 3:
                    time.sleep((attempt + 1) * 2)
                    last_error = exc
                    continue
                body = exc.read().decode("utf-8", errors="replace")
                raise FetchError(f"HTTP {exc.code} for {path}: {body[:400]}") from exc
            except error.URLError as exc:
                if attempt < 3:
                    time.sleep((attempt + 1) * 2)
                    last_error = exc
                    continue
                raise FetchError(f"Network error for {path}: {exc}") from exc
        raise FetchError(f"Request failed for {path}: {last_error}")


def choose_auth(args: argparse.Namespace, deployment_type: str) -> AuthConfig:
    if deployment_type == "cloud":
        if not args.email or not args.api_token:
            raise FetchError("Cloud는 비밀번호 fallback 불가: --email 과 --api-token 이 필요합니다.")
        return AuthConfig(
            deployment_type=deployment_type,
            headers={"Authorization": _basic_auth_header(args.email, args.api_token)},
            auth_used="basic_api_token",
        )

    token_user = args.username or args.email
    if args.api_token:
        if token_user:
            return AuthConfig(
                deployment_type=deployment_type,
                headers={"Authorization": _basic_auth_header(token_user, args.api_token)},
                auth_used="basic_api_token",
            )
        return AuthConfig(
            deployment_type=deployment_type,
            headers={"Authorization": f"Bearer {args.api_token}"},
            auth_used="bearer_token",
        )

    if args.username and args.password:
        return AuthConfig(
            deployment_type=deployment_type,
            headers={"Authorization": _basic_auth_header(args.username, args.password)},
            auth_used="basic_password",
        )

    raise FetchError("Server/Data Center 인증 정보가 부족합니다. 토큰 또는 username/password가 필요합니다.")


def maybe_retry_with_password(
    args: argparse.Namespace,
    deployment_type: str,
    limiter: RateLimiter,
    warnings: List[str],
) -> AuthConfig:
    auth = choose_auth(args, deployment_type)
    client = ConfluenceClient(args.base_url, auth, limiter, warnings, insecure=args.insecure)
    try:
        client.get_json("/rest/api/space", {"limit": 1})
        return auth
    except FetchError:
        if deployment_type == "cloud" or auth.auth_used == "basic_password":
            raise
        if args.username and args.password:
            fallback = AuthConfig(
                deployment_type=deployment_type,
                headers={"Authorization": _basic_auth_header(args.username, args.password)},
                auth_used="basic_password",
            )
            client = ConfluenceClient(args.base_url, fallback, limiter, warnings, insecure=args.insecure)
            client.get_json("/rest/api/space", {"limit": 1})
            warnings.append("토큰 인증이 실패해 username/password fallback 으로 수집했습니다.")
            return fallback
        raise


def parse_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    fixed = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(fixed)
    except ValueError:
        return None


def build_cache_key(args: argparse.Namespace, deployment_type: str) -> str:
    payload = {
        "base_url": args.base_url.rstrip("/"),
        "deployment_type": deployment_type,
        "space_key": args.space_key,
        "root_page_id": args.root_page_id,
        "all_spaces": args.all_spaces,
        "query": args.query,
        "label": args.label,
        "days": args.days,
        "limit": args.limit,
        "include_body": args.include_body,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


def cache_file_path(cache_dir: str, cache_key: str) -> str:
    return os.path.join(cache_dir, f"{cache_key}.json")


def load_cached_result(path: str, ttl_hours: int) -> Optional[Dict[str, Any]]:
    if not os.path.exists(path):
        return None
    age_seconds = time.time() - os.path.getmtime(path)
    if ttl_hours >= 0 and age_seconds > ttl_hours * 3600:
        return None
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return payload


def save_cached_result(path: str, payload: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def strip_html(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    text = re.sub(r"<[^>]+>", " ", value)
    text = unescape(re.sub(r"\s+", " ", text)).strip()
    return text[:4000] if text else None


def body_hash(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def title_key(title: str) -> str:
    return re.sub(r"[^a-z0-9가-힣]+", "", title.lower())


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, title_key(a), title_key(b)).ratio()


def page_snapshot_dir(data_dir: str, page_id: str) -> str:
    return os.path.join(data_dir, "pages", str(page_id))


def latest_snapshot_path(data_dir: str, page_id: str) -> str:
    return os.path.join(page_snapshot_dir(data_dir, page_id), "latest.json")


def history_snapshot_path(data_dir: str, page_id: str, fetched_at: str, version_number: Optional[int]) -> str:
    stamp = fetched_at.replace(":", "").replace("-", "").replace("+", "_")
    version_label = f"v{version_number}" if version_number is not None else "vunknown"
    return os.path.join(page_snapshot_dir(data_dir, page_id), "history", f"{stamp}_{version_label}.json")


def run_artifact_path(data_dir: str, fetched_at: str) -> str:
    stamp = fetched_at.replace(":", "").replace("-", "").replace("+", "_")
    return os.path.join(data_dir, "runs", f"fetch_{stamp}.json")


def page_change_summary(current: Dict[str, Any], previous: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not previous:
        return {
            "has_reference": False,
            "changed": True,
            "change_type": "new",
            "importance": "high",
            "importance_score": 16,
            "previous_updated_at": None,
            "current_updated_at": current.get("updated_at"),
            "previous_version_number": None,
            "current_version_number": current.get("version_number"),
            "changed_fields": ["new_page"],
            "body_similarity": None,
            "summary_ko": "저장된 기준본이 없어 새 문서로 취급합니다.",
        }

    previous_body = previous.get("body_excerpt") or ""
    current_body = current.get("body_excerpt") or ""
    similarity_score = SequenceMatcher(None, previous_body, current_body).ratio() if previous_body or current_body else 1.0
    changed_fields: List[str] = []

    if previous.get("title") != current.get("title"):
        changed_fields.append("title")
    if previous.get("updated_at") != current.get("updated_at"):
        changed_fields.append("updated_at")
    if previous.get("version_number") != current.get("version_number"):
        changed_fields.append("version_number")
    if previous.get("body_hash") != current.get("body_hash"):
        changed_fields.append("body_excerpt")
    if previous.get("last_updated_by_account_id") != current.get("last_updated_by_account_id"):
        changed_fields.append("last_updated_by_account_id")

    if not changed_fields:
        return {
            "has_reference": True,
            "changed": False,
            "change_type": "unchanged",
            "importance": "background",
            "importance_score": 3,
            "previous_updated_at": previous.get("updated_at"),
            "current_updated_at": current.get("updated_at"),
            "previous_version_number": previous.get("version_number"),
            "current_version_number": current.get("version_number"),
            "changed_fields": [],
            "body_similarity": round(similarity_score, 3),
            "summary_ko": "저장된 기준본 대비 의미 있는 변경이 확인되지 않았습니다.",
        }

    version_gap = (current.get("version_number") or 0) - (previous.get("version_number") or 0)
    major_change = "body_excerpt" in changed_fields and similarity_score < 0.88
    if major_change or version_gap >= 2:
        importance = "high"
        importance_score = 18
    elif "updated_at" in changed_fields or "version_number" in changed_fields:
        importance = "medium"
        importance_score = 11
    else:
        importance = "low"
        importance_score = 6

    changes_ko: List[str] = []
    if "title" in changed_fields:
        changes_ko.append("제목 변경")
    if "updated_at" in changed_fields:
        changes_ko.append("갱신 시각 변경")
    if "version_number" in changed_fields:
        changes_ko.append("버전 증가")
    if "body_excerpt" in changed_fields:
        changes_ko.append("본문 내용 변경")
    if "last_updated_by_account_id" in changed_fields:
        changes_ko.append("최근 수정자 변경")

    return {
        "has_reference": True,
        "changed": True,
        "change_type": "updated",
        "importance": importance,
        "importance_score": importance_score,
        "previous_updated_at": previous.get("updated_at"),
        "current_updated_at": current.get("updated_at"),
        "previous_version_number": previous.get("version_number"),
        "current_version_number": current.get("version_number"),
        "changed_fields": changed_fields,
        "body_similarity": round(similarity_score, 3),
        "summary_ko": "저장된 기준본 대비 " + ", ".join(changes_ko) + " 이 확인되었습니다.",
    }


def persist_data_artifacts(
    data_dir: str,
    result: Dict[str, Any],
) -> Dict[str, Any]:
    fetched_at = ((result.get("meta") or {}).get("fetched_at")) or iso_now()
    pages = result.get("pages", [])
    snapshot_stats = {
        "page_count": len(pages),
        "new_page_count": 0,
        "updated_page_count": 0,
        "unchanged_page_count": 0,
    }

    for page in pages:
        page_id = str(page.get("page_id") or "")
        if not page_id:
            continue
        previous_payload = load_json_if_exists(latest_snapshot_path(data_dir, page_id))
        previous = (previous_payload or {}).get("page")
        page["body_hash"] = body_hash(page.get("body_excerpt"))
        change = page_change_summary(page, previous)
        page["reference_snapshot"] = {
            "data_dir": os.path.abspath(data_dir),
            "latest_snapshot_path": os.path.abspath(latest_snapshot_path(data_dir, page_id)),
            "has_reference": change["has_reference"],
        }
        page["change_summary"] = change

        if change["change_type"] == "new":
            snapshot_stats["new_page_count"] += 1
        elif change["changed"]:
            snapshot_stats["updated_page_count"] += 1
        else:
            snapshot_stats["unchanged_page_count"] += 1

        snapshot_payload = {
            "meta": {
                "saved_at": iso_now(),
                "fetched_at": fetched_at,
                "page_id": page_id,
                "data_dir": os.path.abspath(data_dir),
            },
            "page": page,
        }
        write_json(latest_snapshot_path(data_dir, page_id), snapshot_payload)
        write_json(
            history_snapshot_path(data_dir, page_id, fetched_at, page.get("version_number")),
            snapshot_payload,
        )

    run_payload = dict(result)
    run_path = run_artifact_path(data_dir, fetched_at)
    write_json(run_path, run_payload)
    feature_paths = persist_feature_state(
        data_dir,
        "fetch-confluence",
        {
            "meta": {
                "generated_at": fetched_at,
                "page_count": len(pages),
                "new_page_count": snapshot_stats["new_page_count"],
                "updated_page_count": snapshot_stats["updated_page_count"],
                "unchanged_page_count": snapshot_stats["unchanged_page_count"],
            },
            "scope": ((result.get("meta") or {}).get("scope", {})),
            "cache": ((result.get("meta") or {}).get("cache", {})),
            "data_artifacts": {
                "run_artifact_path": os.path.abspath(run_path),
                **snapshot_stats,
            },
        },
        generated_at=fetched_at,
    )
    result.setdefault("meta", {})
    result["meta"]["data_artifacts"] = {
        "used": True,
        "data_dir": os.path.abspath(data_dir),
        "run_artifact_path": os.path.abspath(run_path),
        "feature_latest_path": feature_paths["latest_path"],
        **snapshot_stats,
    }
    return result


def fetch_page_batch(client: ConfluenceClient, args: argparse.Namespace) -> List[Dict[str, Any]]:
    pages: List[Dict[str, Any]] = []
    start = 0
    limit = min(args.limit, 100)
    expand_fields = ["version", "history", "ancestors", "metadata.labels"]
    if args.include_body:
        expand_fields.append("body.storage")
    if args.query:
        path = "/rest/api/content/search"
        cql_parts = ["type = page"]
        if args.space_key:
            cql_parts.append(f'space = "{args.space_key}"')
        cql_query = build_cql_query(args.query)
        cql_parts.append(f"({cql_query})")
        base_params = {
            "limit": limit,
            "start": start,
            "expand": ",".join(expand_fields),
            "cql": " and ".join(cql_parts),
        }
    elif args.root_page_id:
        path = f"/rest/api/content/{args.root_page_id}/descendant/page"
        base_params = {"limit": limit, "start": start, "expand": ",".join(expand_fields)}
    else:
        path = "/rest/api/content"
        base_params = {
            "type": "page",
            "limit": limit,
            "start": start,
            "expand": ",".join(expand_fields),
        }
        if args.space_key:
            base_params["spaceKey"] = args.space_key

    while len(pages) < args.limit:
        params = dict(base_params)
        params["start"] = start
        payload = client.get_json(path, params)
        batch = payload.get("results", [])
        if not batch:
            break
        pages.extend(batch)
        if len(batch) < limit:
            break
        start += len(batch)
    return pages[: args.limit]


def fetch_versions(client: ConfluenceClient, page_id: str, warnings: List[str]) -> List[Dict[str, Any]]:
    endpoints = [
        f"/rest/experimental/content/{page_id}/version",
        f"/rest/api/content/{page_id}/version",
    ]
    for endpoint in endpoints:
        try:
            payload = client.get_json(endpoint, {"limit": VERSION_LIMIT})
            results = payload.get("results", payload.get("value", payload if isinstance(payload, list) else []))
            if isinstance(results, list):
                events = []
                for item in results[:VERSION_LIMIT]:
                    by = item.get("by", {}) or {}
                    events.append(
                        {
                            "version": item.get("number"),
                            "updated_at": item.get("when"),
                            "account_id": extract_account_id(by),
                            "message": item.get("message", ""),
                        }
                    )
                return events
        except FetchError:
            continue
    warnings.append(f"페이지 {page_id} 의 상세 버전 이력을 가져오지 못해 기본 version 정보만 사용합니다.")
    return []


def extract_account_id(user_obj: Dict[str, Any]) -> Optional[str]:
    return (
        user_obj.get("accountId")
        or user_obj.get("account_id")
        or user_obj.get("username")
        or user_obj.get("userKey")
        or user_obj.get("userkey")
    )


def extract_profile_fields(payload: Dict[str, Any]) -> Dict[str, Optional[str]]:
    profile = payload.get("profile", {}) or {}
    details = payload.get("details", {}) or {}
    personal = payload.get("personalSpace", {}) or {}
    return {
        "job_title_raw": payload.get("jobTitle") or profile.get("position") or details.get("position"),
        "department_raw": payload.get("department") or details.get("department"),
        "organization_raw": payload.get("organization") or details.get("company"),
        "about_raw": payload.get("aboutMe") or profile.get("status") or personal.get("name"),
    }


def infer_org_hint(profile_fields: Dict[str, Optional[str]]) -> Dict[str, Any]:
    title = profile_fields.get("job_title_raw")
    dept = profile_fields.get("department_raw")
    about = profile_fields.get("about_raw") or ""
    combined = " ".join(filter(None, [title, dept, about])).lower()
    evidence: List[str] = []
    role_band = "unknown"
    confidence = "low"

    patterns = [
        ("director", r"\bdirector\b|\bhead\b|\bvp\b"),
        ("lead", r"\blead\b|\bmanager\b|\bowner\b"),
        ("staff", r"\bstaff\b|\bprincipal\b|\bsenior\b"),
        ("individual", r"\bengineer\b|\bdeveloper\b|\banalyst\b|\boperator\b"),
    ]
    for band, pattern in patterns:
        if re.search(pattern, combined):
            role_band = band
            evidence.append(f"matched role pattern: {band}")
            break
    if title:
        confidence = "medium"
        evidence.append("job_title_raw present")
    if dept:
        confidence = "medium" if confidence == "low" else "high"
        evidence.append("department_raw present")
    return {
        "team": dept,
        "title": title,
        "role_band": role_band,
        "confidence": confidence,
        "evidence": evidence,
    }


def fetch_person(client: ConfluenceClient, deployment_type: str, account_id: str, warnings: List[str]) -> Optional[Dict[str, Any]]:
    endpoints: List[Tuple[str, Dict[str, Any]]] = []
    if deployment_type == "cloud":
        endpoints.append(("/rest/api/user", {"accountId": account_id}))
    else:
        endpoints.append(("/rest/api/user", {"username": account_id}))
        endpoints.append(("/rest/api/user", {"key": account_id}))

    for path, params in endpoints:
        try:
            payload = client.get_json(path, params)
            profile_fields = extract_profile_fields(payload)
            return {
                "account_id": account_id,
                "display_name": payload.get("displayName"),
                "public_name": payload.get("publicName") or payload.get("displayName"),
                "email": payload.get("email"),
                "profile": profile_fields,
                "org_hint": infer_org_hint(profile_fields),
            }
        except FetchError:
            continue
    warnings.append(f"사용자 {account_id} 의 프로필을 가져오지 못했습니다.")
    return {
        "account_id": account_id,
        "display_name": account_id,
        "public_name": account_id,
        "email": None,
        "profile": {
            "job_title_raw": None,
            "department_raw": None,
            "organization_raw": None,
            "about_raw": None,
        },
        "org_hint": {
            "team": None,
            "title": None,
            "role_band": "unknown",
            "confidence": "low",
            "evidence": ["profile unavailable"],
        },
    }


def page_matches_filters(page: Dict[str, Any], days: Optional[int], label: Optional[str], query: Optional[str]) -> bool:
    if days:
        updated = parse_datetime(page.get("version", {}).get("when"))
        if updated and updated < datetime.now(timezone.utc) - timedelta(days=days):
            return False
    if label:
        labels = ((page.get("metadata", {}) or {}).get("labels", {}) or {}).get("results", [])
        names = {item.get("name") for item in labels}
        if label not in names:
            return False
    if query:
        haystacks = [
            (page.get("title") or "").lower(),
            strip_html(((((page.get("body") or {}).get("storage") or {}).get("value"))) or "") or "",
        ]
        terms = parse_query_terms(query)
        if terms and not any(term in hay for term in terms for hay in haystacks):
            return False
    return True


def build_retrieval_seed_metadata(args: argparse.Namespace, page: Dict[str, Any]) -> Dict[str, Any]:
    source = "space_seed"
    reasons = ["스페이스 범위 시드"]
    if args.query:
        source = "query_seed"
        reasons = ["키워드 검색 시드"]
    elif args.root_page_id:
        source = "root_descendant_seed"
        reasons = ["루트 페이지 하위 문서 시드"]
    elif args.all_spaces:
        source = "all_spaces_seed"
        reasons = ["전체 스페이스 범위 시드"]

    return {
        "discovery_source": source,
        "discovery_reasons": reasons,
        "retrieval_paths": [
            {
                "kind": source,
                "space_key": (page.get("space") or {}).get("key") or args.space_key,
                "query": args.query,
                "root_page_id": args.root_page_id,
                "label": args.label,
                "all_spaces": bool(args.all_spaces),
                "reasons": reasons,
            }
        ],
        "preferred_space_match": False,
        "preferred_space_boost": 0,
    }


def normalize_pages(
    raw_pages: Iterable[Dict[str, Any]],
    client: ConfluenceClient,
    args: argparse.Namespace,
    warnings: List[str],
) -> Tuple[List[Dict[str, Any]], List[str]]:
    pages: List[Dict[str, Any]] = []
    contributor_ids: List[str] = []
    for page in raw_pages:
        if not page_matches_filters(page, args.days, args.label, args.query):
            continue
        version = page.get("version", {}) or {}
        history = page.get("history", {}) or {}
        created_by = history.get("createdBy", {}) or {}
        last_by = version.get("by", {}) or {}
        page_id = str(page.get("id"))
        version_events = fetch_versions(client, page_id, warnings)
        recent_contributors = list(
            dict.fromkeys(
                filter(
                    None,
                    [extract_account_id(created_by), extract_account_id(last_by)]
                    + [item.get("account_id") for item in version_events],
                )
            )
        )
        contributor_ids.extend(recent_contributors)
        body_value = ((((page.get("body") or {}).get("storage") or {}).get("value"))) if args.include_body else None
        retrieval_meta = build_retrieval_seed_metadata(args, page)
        normalized = {
            "page_id": page_id,
            "title": page.get("title"),
            "url": client.base_url + page.get("_links", {}).get("webui", f"/pages/{page_id}"),
            "space_key": (page.get("space") or {}).get("key") or args.space_key,
            "status": page.get("status", "current"),
            "created_at": history.get("createdDate"),
            "updated_at": version.get("when"),
            "created_by_account_id": extract_account_id(created_by),
            "last_updated_by_account_id": extract_account_id(last_by),
            "version_number": version.get("number"),
            "ancestors": [
                {"page_id": str(item.get("id")), "title": item.get("title")}
                for item in (page.get("ancestors") or [])
            ],
            "labels": [item.get("name") for item in (((page.get("metadata") or {}).get("labels") or {}).get("results") or [])],
            "version_events": version_events,
            "recent_contributors": recent_contributors,
            "body_excerpt": strip_html(body_value),
            **retrieval_meta,
        }
        pages.append(normalized)
    return pages, list(dict.fromkeys(filter(None, contributor_ids)))


def build_relationships(pages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    relationships: List[Dict[str, Any]] = []
    page_ids = {page["page_id"] for page in pages}
    for page in pages:
        for ancestor in page.get("ancestors", []):
            if ancestor["page_id"] in page_ids:
                relationships.append(
                    {
                        "from_page_id": ancestor["page_id"],
                        "to_page_id": page["page_id"],
                        "type": "child",
                        "confidence": "high",
                    }
                )
                relationships.append(
                    {
                        "from_page_id": page["page_id"],
                        "to_page_id": ancestor["page_id"],
                        "type": "ancestor",
                        "confidence": "high",
                    }
                )
    for index, left in enumerate(pages):
        for right in pages[index + 1 :]:
            score = similarity(left["title"], right["title"])
            if score >= 0.82:
                confidence = "high" if score >= 0.9 else "medium"
                relationships.append(
                    {
                        "from_page_id": left["page_id"],
                        "to_page_id": right["page_id"],
                        "type": "related_title",
                        "confidence": confidence,
                    }
                )
                relationships.append(
                    {
                        "from_page_id": right["page_id"],
                        "to_page_id": left["page_id"],
                        "type": "related_title",
                        "confidence": confidence,
                    }
                )
    return relationships


def estimate_runtime_warning(request_count: int, rps: float, warnings: List[str]) -> None:
    seconds = request_count / rps if rps else 0
    if seconds >= 60:
        warnings.append(
            f"rate limit 정책 때문에 예상 수집 시간이 길 수 있습니다. 대략 {request_count}회 호출, 약 {int(seconds)}초 예상입니다."
        )


def main() -> int:
    args = parse_args()
    warnings: List[str] = []
    limiter = RateLimiter(args.rate_limit_rps)
    deployment_type = detect_deployment_type(args.base_url, args.deployment_type)
    cache_key = build_cache_key(args, deployment_type)
    cache_path = cache_file_path(args.cache_dir, cache_key)

    if not args.refresh_cache:
        cached = load_cached_result(cache_path, args.cache_ttl_hours)
        if cached:
            cached.setdefault("meta", {})
            cached["meta"]["config"] = {
                "source": args._config_source,
                "path": args._config_path,
                "found": args._config_used,
            }
            cached["meta"]["cache"] = {
                "used": True,
                "cache_key": cache_key,
                "cache_path": cache_path,
                "cache_ttl_hours": args.cache_ttl_hours,
            }
            cached = persist_data_artifacts(args.data_dir, cached)
            os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
            with open(args.output, "w", encoding="utf-8") as handle:
                json.dump(cached, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            return 0

    if args.cache_only:
        raise FetchError(f"캐시만 사용하도록 요청되었지만 사용 가능한 캐시가 없습니다: {cache_path}")

    auth = maybe_retry_with_password(args, deployment_type, limiter, warnings)
    client = ConfluenceClient(args.base_url, auth, limiter, warnings, insecure=args.insecure)

    raw_pages = fetch_page_batch(client, args)
    pages, contributor_ids = normalize_pages(raw_pages, client, args, warnings)

    people = []
    seen_people = set()
    for account_id in contributor_ids:
        if account_id in seen_people:
            continue
        seen_people.add(account_id)
        people.append(fetch_person(client, deployment_type, account_id, warnings))
    people = [item for item in people if item]

    relationships = build_relationships(pages)
    estimate_runtime_warning(client.request_count, args.rate_limit_rps, warnings)

    result = {
        "meta": {
            "fetched_at": iso_now(),
            "base_url": args.base_url.rstrip("/"),
            "deployment_type": deployment_type,
            "auth_used": auth.auth_used,
            "config": {
                "source": args._config_source,
                "path": args._config_path,
                "found": args._config_used,
            },
            "rate_limit_rps": args.rate_limit_rps,
            "scope": {
                "space_key": args.space_key,
                "root_page_id": args.root_page_id,
                "all_spaces": args.all_spaces,
                "query": args.query,
                "days": args.days,
                "limit": args.limit,
            },
            "include_body": args.include_body,
            "cache": {
                "used": False,
                "cache_key": cache_key,
                "cache_path": cache_path,
                "cache_ttl_hours": args.cache_ttl_hours,
            },
        },
        "pages": pages,
        "people": people,
        "relationships": relationships,
        "warnings": warnings,
    }

    save_cached_result(cache_path, result)
    result = persist_data_artifacts(args.data_dir, result)
    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except FetchError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
