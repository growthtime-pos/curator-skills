"""curator-skills auto self-update check.

Compares the local repo's latest reachable v* tag with origin's latest v* tag
and fast-forward pulls ``main`` when safe. Throttled to once per hour.
Always exits 0 so it never blocks the rest of the skill.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

THROTTLE_SECONDS = 3600
FETCH_TIMEOUT = 5
PULL_TIMEOUT = 10
TAG_PREFIX = "v"


def find_repo_root() -> Optional[Path]:
    here = Path(os.path.realpath(__file__)).parent
    rc, out, _ = run_git(here, ["rev-parse", "--show-toplevel"], timeout=FETCH_TIMEOUT)
    if rc != 0 or not out:
        return None
    return Path(out)


def run_git(
    cwd: Path,
    args: List[str],
    timeout: int = FETCH_TIMEOUT,
    extra_env: Optional[Dict[str, str]] = None,
) -> Tuple[int, str, str]:
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    if extra_env:
        env.update(extra_env)
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"
    except FileNotFoundError:
        return 127, "", "git not found"


def parse_version(tag: str) -> Optional[Tuple[int, ...]]:
    nums = re.findall(r"\d+", tag)
    if not nums:
        return None
    return tuple(int(n) for n in nums)


def emit(quiet: bool, message: str) -> None:
    if quiet:
        return
    print(f"[skill-update-check] {message}", file=sys.stderr, flush=True)


def touch(path: Path) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch(exist_ok=True)
        os.utime(path, None)
    except OSError:
        pass


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check origin for a newer release tag and ff-only pull main if safe.",
    )
    parser.add_argument("--force", action="store_true", help="ignore the 1-hour throttle")
    parser.add_argument("--quiet", action="store_true", help="suppress stderr messages")
    args: argparse.Namespace = parser.parse_args(argv)

    root = find_repo_root()
    if root is None:
        emit(args.quiet, "not a git repo, skipped")
        return 0

    ts_file = root / "tmp" / ".skill-update-check.ts"

    if not args.force and ts_file.exists():
        age = time.time() - ts_file.stat().st_mtime
        if age < THROTTLE_SECONDS:
            return 0

    touch(ts_file)

    rc, _, _ = run_git(root, ["fetch", "--tags", "--quiet", "origin"], timeout=FETCH_TIMEOUT)
    if rc != 0:
        emit(args.quiet, "offline or fetch failed, skipped")
        return 0

    rc, local_tag, _ = run_git(root, ["describe", "--tags", "--abbrev=0"])
    if rc != 0 or not local_tag:
        return 0

    rc, remote_tag, _ = run_git(
        root,
        [
            "-c",
            "versionsort.suffix=-",
            "for-each-ref",
            "--sort=-v:refname",
            "--count=1",
            "--format=%(refname:short)",
            f"refs/tags/{TAG_PREFIX}*",
        ],
    )
    if rc != 0 or not remote_tag:
        return 0

    if local_tag == remote_tag:
        return 0

    local_v = parse_version(local_tag)
    remote_v = parse_version(remote_tag)
    if local_v is None or remote_v is None:
        return 0
    if remote_v <= local_v:
        return 0

    rc, dirty, _ = run_git(root, ["status", "--porcelain", "--untracked-files=no"])
    if rc == 0 and dirty:
        emit(
            args.quiet,
            f"new release {remote_tag} available, but uncommitted changes — skipping auto-update",
        )
        return 0

    rc, branch, _ = run_git(root, ["symbolic-ref", "--short", "-q", "HEAD"])
    if rc != 0 or branch != "main":
        location = branch if branch else "detached HEAD"
        emit(
            args.quiet,
            f"new release {remote_tag} available, you're on {location} — not auto-updating",
        )
        return 0

    rc, _, _ = run_git(
        root,
        ["pull", "--ff-only", "--quiet", "origin", "main"],
        timeout=PULL_TIMEOUT,
    )
    if rc != 0:
        emit(
            args.quiet,
            f"new release {remote_tag} available, but ff-only pull failed — manual update required",
        )
        return 0

    _, new_local, _ = run_git(root, ["describe", "--tags", "--abbrev=0"])
    new_local = new_local or remote_tag
    emit(args.quiet, f"updated {local_tag} → {new_local}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
