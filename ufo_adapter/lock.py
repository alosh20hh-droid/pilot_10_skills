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

    required = {
        "repository",
        "commit",
        "required_mode",
        "forbidden_modes",
        "plan_schema",
        "audited_sources",
        "required_files",
        "execution_overlay",
    }
    missing = sorted(required - set(value))
    if missing:
        raise UFOLockError(
            "UFO upstream lock missing fields: " + ", ".join(missing)
        )
    if value.get("repository") != "microsoft/UFO":
        raise UFOLockError("UFO upstream repository must be microsoft/UFO")
    commit = value.get("commit")
    if not isinstance(commit, str) or len(commit) != 40:
        raise UFOLockError("UFO upstream commit must be a full 40-character SHA")
    if value.get("required_mode") != "follower":
        raise UFOLockError("UFO upstream lock must require follower mode")
    plan_schema = value.get("plan_schema")
    if not isinstance(plan_schema, dict):
        raise UFOLockError("UFO plan_schema must be an object")
    if plan_schema.get("required_fields") != ["task", "steps", "object"]:
        raise UFOLockError("unexpected UFO follower plan field contract")
    if plan_schema.get("object") != "AfterFX.exe":
        raise UFOLockError("UFO baseline plan object must be AfterFX.exe")
    required_files = value.get("required_files")
    if not isinstance(required_files, dict) or not required_files:
        raise UFOLockError("UFO required_files must be a non-empty object")
    for path, blob_sha in required_files.items():
        if not isinstance(path, str) or not path:
            raise UFOLockError("invalid UFO required file path")
        if not isinstance(blob_sha, str) or len(blob_sha) != 40:
            raise UFOLockError(f"invalid UFO blob SHA for {path}")
    if set(value.get("audited_sources") or []) != set(required_files):
        raise UFOLockError(
            "audited_sources must exactly match required_files"
        )

    overlay = value.get("execution_overlay")
    if not isinstance(overlay, dict):
        raise UFOLockError("execution_overlay must be an object")
    if overlay.get("environment") != "pilot":
        raise UFOLockError("UFO execution overlay environment must be pilot")
    if overlay.get("file") != "config/ufo/system_pilot.yaml":
        raise UFOLockError("unexpected UFO execution overlay path")
    required_settings = overlay.get("required_settings")
    if not isinstance(required_settings, dict):
        raise UFOLockError("execution_overlay.required_settings must be an object")
    expected_overlay_settings = {
        "CONTROL_BACKEND": ["uia"],
        "USE_APIS": False,
        "USE_MCP": False,
        "MCP_FALLBACK_TO_UI": False,
        "EVA_SESSION": False,
        "EVA_ROUND": False,
        "TASK_STATUS": False,
        "SAVE_EXPERIENCE": "always_not",
        "ASK_QUESTION": False,
        "USE_CUSTOMIZATION": False,
        "ENABLED_THIRD_PARTY_AGENTS": [],
        "INPUT_TEXT_API": "type_keys",
        "CLICK_API": "click_input",
    }
    for key, expected in expected_overlay_settings.items():
        if required_settings.get(key) != expected:
            raise UFOLockError(
                f"UFO execution overlay setting {key} must be {expected!r}"
            )
    if overlay.get("dynamic_round_budget_rule") != "MAX_ROUND = measured_step_count + 2":
        raise UFOLockError("unexpected UFO follower round-budget rule")
    minimum_step_budget = overlay.get("minimum_step_budget")
    if not isinstance(minimum_step_budget, int) or minimum_step_budget < 1:
        raise UFOLockError("execution_overlay.minimum_step_budget must be positive")

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

    required_files = dict(lock.get("required_files") or {})
    missing_files = [path for path in required_files if not (repo / path).is_file()]
    blob_mismatches = []
    for path, expected_blob in required_files.items():
        if path in missing_files:
            continue
        try:
            actual_blob = _run_git(repo, "rev-parse", f"HEAD:{path}")
        except UFOLockError:
            blob_mismatches.append({
                "path": path,
                "expected": expected_blob,
                "actual": None,
            })
            continue
        if actual_blob != expected_blob:
            blob_mismatches.append({
                "path": path,
                "expected": expected_blob,
                "actual": actual_blob,
            })

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
        "blob_mismatches": blob_mismatches,
        "valid": (
            commit_matches
            and status == ""
            and not missing_files
            and not blob_mismatches
        ),
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
    if result.get("blob_mismatches"):
        details = ", ".join(
            item["path"] for item in result["blob_mismatches"]
        )
        raise UFOLockError(
            "UFO audited file blobs do not match the pinned upstream: " + details
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
