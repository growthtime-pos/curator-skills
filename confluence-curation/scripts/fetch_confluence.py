#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from html import unescape
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib import error, parse, request


MAX_RPS = 1.0
VERSION_LIMIT = 5
TRANSIENT_STATUSES = {429, 500, 502, 503, 504}


def iso_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch Confluence pages and profile hints.")
    parser.add_argument("--base-url", default=os.getenv("CONFLUENCE_BASE_URL"))
    parser.add_argument(
        "--deployment-type",
        default=os.getenv("CONFLUENCE_DEPLOYMENT_TYPE", "auto"),
        choices=["auto", "cloud", "server", "datacenter"],
    )
    parser.add_argument("--email", default=os.getenv("CONFLUENCE_EMAIL"))
    parser.add_argument("--username", default=os.getenv("CONFLUENCE_USERNAME"))
    parser.add_argument("--api-token", default=os.getenv("CONFLUENCE_API_TOKEN"))
    parser.add_argument("--password", default=os.getenv("CONFLUENCE_PASSWORD"))
    parser.add_argument("--space-key")
    parser.add_argument("--root-page-id")
    parser.add_argument("--label")
    parser.add_argument("--days", type=int)
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--include-body", action="store_true")
    parser.add_argument(
        "--rate-limit-rps",
        type=float,
        default=float(os.getenv("CONFLUENCE_RATE_LIMIT_RPS", "1.0")),
    )
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    if not args.base_url:
        parser.error("--base-url or CONFLUENCE_BASE_URL is required")
    if not args.space_key and not args.root_page_id:
        parser.error("--space-key or --root-page-id is required")
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


def detect_deployment_type(base_url: str, requested: str) -> str:
    if requested != "auto":
        return requested
    parsed = parse.urlparse(base_url)
    host = (parsed.netloc or "").lower()
    if "atlassian.net" in host:
        return "cloud"
    return "server"


class ConfluenceClient:
    def __init__(self, base_url: str, auth: AuthConfig, limiter: RateLimiter, warnings: List[str]):
        self.base_url = base_url.rstrip("/")
        self.auth = auth
        self.limiter = limiter
        self.warnings = warnings
        self.request_count = 0

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
                with request.urlopen(req, timeout=30) as resp:
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
    client = ConfluenceClient(args.base_url, auth, limiter, warnings)
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
            client = ConfluenceClient(args.base_url, fallback, limiter, warnings)
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


def strip_html(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    text = re.sub(r"<[^>]+>", " ", value)
    text = unescape(re.sub(r"\s+", " ", text)).strip()
    return text[:500] if text else None


def title_key(title: str) -> str:
    return re.sub(r"[^a-z0-9가-힣]+", "", title.lower())


def similarity(a: str, b: str) -> float:
    from difflib import SequenceMatcher

    return SequenceMatcher(None, title_key(a), title_key(b)).ratio()


def fetch_page_batch(client: ConfluenceClient, args: argparse.Namespace) -> List[Dict[str, Any]]:
    pages: List[Dict[str, Any]] = []
    start = 0
    limit = min(args.limit, 100)
    expand_fields = ["version", "history", "ancestors", "metadata.labels"]
    if args.include_body:
        expand_fields.append("body.storage")
    if args.root_page_id:
        path = f"/rest/api/content/{args.root_page_id}/descendant/page"
        base_params = {"limit": limit, "start": start, "expand": ",".join(expand_fields)}
    else:
        path = "/rest/api/content"
        base_params = {
            "spaceKey": args.space_key,
            "type": "page",
            "limit": limit,
            "start": start,
            "expand": ",".join(expand_fields),
        }

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


def page_matches_filters(page: Dict[str, Any], days: Optional[int], label: Optional[str]) -> bool:
    if days:
        updated = parse_datetime(page.get("version", {}).get("when"))
        if updated and updated < datetime.now(timezone.utc) - timedelta(days=days):
            return False
    if label:
        labels = ((page.get("metadata", {}) or {}).get("labels", {}) or {}).get("results", [])
        names = {item.get("name") for item in labels}
        return label in names
    return True


def normalize_pages(
    raw_pages: Iterable[Dict[str, Any]],
    client: ConfluenceClient,
    args: argparse.Namespace,
    warnings: List[str],
) -> Tuple[List[Dict[str, Any]], List[str]]:
    pages: List[Dict[str, Any]] = []
    contributor_ids: List[str] = []
    for page in raw_pages:
        if not page_matches_filters(page, args.days, args.label):
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
    auth = maybe_retry_with_password(args, deployment_type, limiter, warnings)
    client = ConfluenceClient(args.base_url, auth, limiter, warnings)

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
            "rate_limit_rps": args.rate_limit_rps,
            "scope": {
                "space_key": args.space_key,
                "root_page_id": args.root_page_id,
                "days": args.days,
                "limit": args.limit,
            },
            "include_body": args.include_body,
        },
        "pages": pages,
        "people": people,
        "relationships": relationships,
        "warnings": warnings,
    }

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
