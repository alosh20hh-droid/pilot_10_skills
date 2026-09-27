"""Locate and validate an existing Microsoft UFO checkout for the AE pilot lab."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional


class UFOInstallationError(RuntimeError):
    pass


@dataclass(frozen=True)
class UFOReferenceLock:
    schema_version: int
    upstream_repository: str
    upstream_repository_full_name: str
    reference_commit: str
    platform: str
    execution_mode: str
    required_entrypoint: str
    required_control_backend: List[str]
    reference_files: List[str]
    verified_reference_capabilities: List[str]
    lab_policy: Dict[str, Any]

    @classmethod
    def load(cls, path: str | Path) -> "UFOReferenceLock":
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeError) as exc:
            raise UFOInstallationError(f"unable to load UFO lock file: {exc}") from exc
        if not isinstance(raw, dict):
            raise UFOInstallationError("UFO lock root must be an object")
        required = [
            "schema_version",
            "upstream_repository",
            "upstream_repository_full_name",
            "reference_commit",
            "platform",
            "execution_mode",
            "required_entrypoint",
            "required_control_backend",
            "reference_files",
            "verified_reference_capabilities",
            "lab_policy",
        ]
        missing = [key for key in required if key not in raw]
        if missing:
            raise UFOInstallationError("UFO lock missing: " + ", ".join(missing))
        return cls(
            schema_version=int(raw["schema_version"]),
            upstream_repository=str(raw["upstream_repository"]),
            upstream_repository_full_name=str(raw["upstream_repository_full_name"]),
            reference_commit=str(raw["reference_commit"]),
            platform=str(raw["platform"]),
            execution_mode=str(raw["execution_mode"]),
            required_entrypoint=str(raw["required_entrypoint"]),
            required_control_backend=list(raw["required_control_backend"]),
            reference_files=list(raw["reference_files"]),
            verified_reference_capabilities=list(raw["verified_reference_capabilities"]),
            lab_policy=dict(raw["lab_policy"]),
        )


@dataclass(frozen=True)
class UFOInspection:
    root: str
    git_head: Optional[str]
    git_remote: Optional[str]
    git_dirty: Optional[bool]
    exact_reference_commit: bool
    structurally_compatible: bool
    missing_files: List[str]
    missing_signatures: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "root": self.root,
            "git_head": self.git_head,
            "git_remote": self.git_remote,
            "git_dirty": self.git_dirty,
            "exact_reference_commit": self.exact_reference_commit,
            "structurally_compatible": self.structurally_compatible,
            "missing_files": list(self.missing_files),
            "missing_signatures": list(self.missing_signatures),
        }


class UFOInstallation:
    REQUIRED_SIGNATURES = {
        "ufo/ufo.py": [
            '"--mode"',
            '"follower"',
            '"--plan"',
        ],
        "ufo/module/sessions/plan_reader.py": [
            "class PlanReader",
            "def next_step",
            'self.plan.get("steps", [])',
        ],
        "ufo/module/sessions/session.py": [
            "class FollowerSession",
            "self.plan_reader = PlanReader(plan_file)",
            'self.context.set(ContextNames.MODE, "follower")',
        ],
        "ufo/module/session_pool.py": [
            'elif mode == "follower"',
            "FollowerSession(",
        ],
        "ufo/automator/ui_control/controller.py": [
            "def click_input",
            "def click_on_coordinates",
            "def drag_on_coordinates",
            "def keyboard_input",
            "def key_press",
            "def scroll",
            "def mouse_move",
            "def type",
        ],
        "config/config_loader.py": [
            'os.getenv("UFO_ENV", "production")',
            'f"{yaml_file.stem}_{env}.yaml"',
        ],
    }

    def __init__(
        self,
        root: str | Path,
        lock: UFOReferenceLock,
    ) -> None:
        self.root = Path(root).expanduser().resolve()
        self.lock = lock

    @classmethod
    def discover(
        cls,
        lock: UFOReferenceLock,
        explicit_root: Optional[str | Path] = None,
    ) -> "UFOInstallation":
        candidates: List[Path] = []

        if explicit_root:
            candidates.append(Path(explicit_root).expanduser())

        env_root = os.environ.get("UFO_ROOT")
        if env_root:
            candidates.append(Path(env_root).expanduser())

        home = Path.home()
        candidates.extend(
            [
                home / "UFO",
                home / "Desktop" / "UFO",
                home / "Documents" / "UFO",
            ]
        )

        seen = set()
        for candidate in candidates:
            resolved = candidate.resolve()
            if str(resolved).lower() in seen:
                continue
            seen.add(str(resolved).lower())
            if (resolved / "ufo" / "__main__.py").is_file():
                return cls(resolved, lock)

        raise UFOInstallationError(
            "existing UFO checkout was not found; pass --ufo-root or set UFO_ROOT"
        )

    def _git(self, *args: str) -> Optional[str]:
        try:
            completed = subprocess.run(
                ["git", "-C", str(self.root), *args],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if completed.returncode != 0:
            return None
        return completed.stdout.strip()

    def inspect(self) -> UFOInspection:
        missing_files = [
            relative
            for relative in self.lock.reference_files
            if not (self.root / relative).is_file()
        ]

        missing_signatures: List[str] = []
        for relative, signatures in self.REQUIRED_SIGNATURES.items():
            path = self.root / relative
            if not path.is_file():
                continue
            try:
                source = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                missing_signatures.append(f"{relative}: unreadable")
                continue
            for signature in signatures:
                if signature not in source:
                    missing_signatures.append(f"{relative}: {signature}")

        git_head = self._git("rev-parse", "HEAD")
        git_remote = self._git("remote", "get-url", "origin")
        dirty_output = self._git("status", "--porcelain")
        git_dirty = None if dirty_output is None else bool(dirty_output)

        structurally_compatible = not missing_files and not missing_signatures
        exact_reference = git_head == self.lock.reference_commit

        return UFOInspection(
            root=str(self.root),
            git_head=git_head,
            git_remote=git_remote,
            git_dirty=git_dirty,
            exact_reference_commit=exact_reference,
            structurally_compatible=structurally_compatible,
            missing_files=missing_files,
            missing_signatures=missing_signatures,
        )

    def require_launchable(
        self,
        *,
        allow_compatible_fork: bool = False,
        require_clean_tree: bool = True,
    ) -> UFOInspection:
        inspection = self.inspect()
        if not inspection.structurally_compatible:
            raise UFOInstallationError(
                "UFO checkout is not structurally compatible: "
                + "; ".join(inspection.missing_files + inspection.missing_signatures)
            )
        if require_clean_tree and inspection.git_dirty is not False:
            raise UFOInstallationError(
                "UFO checkout must be a clean git worktree before measured execution"
            )
        if not inspection.exact_reference_commit and not allow_compatible_fork:
            raise UFOInstallationError(
                "UFO HEAD does not match the pinned reference commit; "
                "use an exact checkout or explicitly allow a compatible fork and record its HEAD"
            )
        if inspection.git_head is None:
            raise UFOInstallationError(
                "UFO checkout must be a git repository so execution provenance can be recorded"
            )
        return inspection
