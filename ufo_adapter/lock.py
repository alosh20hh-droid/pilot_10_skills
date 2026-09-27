"""Validate a local UFO checkout against the audited upstream lock."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional


class UFOLockError(RuntimeError):
    pass


def load_upstream_lock(path: str | Path | None = None) -> Dict[str, Any]:
    lock_path = Path(path or (Path(__file__).resolve().parent / "upstream_lock.json"))
    try:
        value = json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise UFOLockError(f"unable to load UFO upstream lock: {exc}") from exc
    if not isinstance(value, dict):
        raise UFOLockError("UFO upstream lock must be an object")
    return value


def _run_git(repo: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), *args],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise UFOLockError(f"unable to inspect UFO checkout with git: {exc}") from exc
    return result.stdout.strip()


def inspect_checkout(
    checkout: str | Path,
    *,
    lock: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    lock = lock or load_upstream_lock()
    repo = Path(checkout).expanduser().resolve()
    if not repo.is_dir():
        raise UFOLockError(f"UFO checkout directory not found: {repo}")

    head = _run_git(repo, "rev-parse", "HEAD")
    status = _run_git(repo, "status", "--porcelain")
    origin = ""
    try:
        origin = _run_git(repo, "remote", "get-url", "origin")
    except UFOLockError:
        origin = ""

    required_files = list(lock.get("audited_sources") or [])
    missing_files = [path for path in required_files if not (repo / path).is_file()]

    expected_commit = lock.get("commit")
    commit_matches = isinstance(expected_commit, str) and head == expected_commit

    return {
        "checkout": str(repo),
        "head": head,
        "expected_commit": expected_commit,
        "commit_matches": commit_matches,
        "clean_worktree": status == "",
        "worktree_changes": status.splitlines() if status else [],
        "origin": origin,
        "missing_audited_files": missing_files,
        "valid": commit_matches and status == "" and not missing_files,
    }


def require_locked_checkout(
    checkout: str | Path,
    *,
    lock: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    result = inspect_checkout(checkout, lock=lock)

    if result["missing_audited_files"]:
        raise UFOLockError(
            "UFO checkout is missing audited files: "
            + ", ".join(result["missing_audited_files"])
        )
    if not result["commit_matches"]:
        raise UFOLockError(
            f"UFO checkout HEAD {result['head']} does not match locked commit "
            f"{result['expected_commit']}"
        )
    if not result["clean_worktree"]:
        raise UFOLockError(
            "UFO checkout has uncommitted changes; measured execution requires a clean checkout"
        )

    return result
