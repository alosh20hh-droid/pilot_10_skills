"""Pinned upstream UFO contract and local integration invariants."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List


class UFOContractError(ValueError):
    pass


@dataclass(frozen=True)
class UFOLock:
    upstream_repository: str
    release_tag: str
    commit_sha: str
    verified_identical_tag_and_commit: bool
    verified_at: str
    required_files: Dict[str, str]
    verified_contract: Dict[str, Any]

    @classmethod
    def load(cls, path: str | Path) -> "UFOLock":
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeError) as exc:
            raise UFOContractError(f"unable to load UFO lock: {exc}") from exc

        if not isinstance(raw, dict):
            raise UFOContractError("UFO lock root must be an object")

        required = (
            "upstream_repository",
            "release_tag",
            "commit_sha",
            "verified_identical_tag_and_commit",
            "verified_at",
            "required_files",
            "verified_contract",
        )
        missing = [key for key in required if key not in raw]
        if missing:
            raise UFOContractError("UFO lock missing fields: " + ", ".join(missing))

        required_files = raw["required_files"]
        verified_contract = raw["verified_contract"]
        if not isinstance(required_files, dict) or not required_files:
            raise UFOContractError("required_files must be a non-empty object")
        if not isinstance(verified_contract, dict):
            raise UFOContractError("verified_contract must be an object")

        lock = cls(
            upstream_repository=str(raw["upstream_repository"]),
            release_tag=str(raw["release_tag"]),
            commit_sha=str(raw["commit_sha"]),
            verified_identical_tag_and_commit=bool(
                raw["verified_identical_tag_and_commit"]
            ),
            verified_at=str(raw["verified_at"]),
            required_files={
                str(key): str(value)
                for key, value in required_files.items()
            },
            verified_contract=verified_contract,
        )
        errors = lock.validate()
        if errors:
            raise UFOContractError("; ".join(errors))
        return lock

    def validate(self) -> List[str]:
        errors: List[str] = []

        if self.upstream_repository != "microsoft/UFO":
            errors.append("upstream repository must be microsoft/UFO")
        if self.release_tag != "v3.0.10":
            errors.append("unexpected pinned UFO release tag")
        if len(self.commit_sha) != 40:
            errors.append("commit_sha must be a full 40-character SHA")
        if not self.verified_identical_tag_and_commit:
            errors.append("release tag and pinned commit must be verified identical")

        required_paths = {
            "ufo/ufo.py",
            "ufo/module/sessions/plan_reader.py",
            "ufo/module/sessions/session.py",
            "ufo/automator/ui_control/controller.py",
            "config/ufo/system.yaml",
            "documents/docs/ufo2/advanced_usage/follower_mode.md",
        }
        missing_paths = sorted(required_paths - set(self.required_files))
        if missing_paths:
            errors.append(
                "UFO lock omits required upstream files: "
                + ", ".join(missing_paths)
            )

        for path, blob_sha in self.required_files.items():
            if len(blob_sha) != 40:
                errors.append(f"invalid blob SHA for {path}")

        contract = self.verified_contract
        if contract.get("cli_mode") != "follower":
            errors.append("UFO integration must use follower mode")
        if contract.get("control_backend_baseline") != ["uia"]:
            errors.append("UFO baseline control backend must be UIA only")

        plan_fields = contract.get("plan_fields")
        if plan_fields != ["task", "steps", "object"]:
            errors.append("UFO follower plan field contract changed")

        capabilities = contract.get("verified_controller_capabilities")
        if not isinstance(capabilities, list) or not capabilities:
            errors.append("verified controller capabilities are missing")

        minimum_capabilities = {
            "click_input",
            "click_on_coordinates",
            "drag_on_coordinates",
            "keyboard_input",
            "keypress",
            "scroll",
            "type",
            "wait",
        }
        if isinstance(capabilities, list):
            missing_caps = sorted(minimum_capabilities - set(capabilities))
            if missing_caps:
                errors.append(
                    "pinned UFO controller lacks required capabilities: "
                    + ", ".join(missing_caps)
                )

        return errors


DEFAULT_LOCK_PATH = Path(__file__).resolve().parent / "UPSTREAM_UFO.lock"


def load_default_lock() -> UFOLock:
    return UFOLock.load(DEFAULT_LOCK_PATH)
