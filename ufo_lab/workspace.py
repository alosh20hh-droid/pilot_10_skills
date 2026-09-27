"""Create an isolated UFO execution worktree with a pilot-only configuration overlay."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

from .installation import UFOInstallation, UFOInstallationError, UFOInspection


class UFOWorkspaceError(RuntimeError):
    pass


@dataclass(frozen=True)
class UFOWorkspace:
    source_root: Path
    worktree_root: Path
    git_head: str
    overlay_path: Path
    max_round: int
    max_step: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_root": str(self.source_root),
            "worktree_root": str(self.worktree_root),
            "git_head": self.git_head,
            "overlay_path": str(self.overlay_path),
            "max_round": self.max_round,
            "max_step": self.max_step,
            "ufo_env": "pilot",
        }


class UFOWorkspaceManager:
    def __init__(
        self,
        installation: UFOInstallation,
        *,
        base_dir: Optional[str | Path] = None,
    ) -> None:
        self.installation = installation
        self.base_dir = Path(
            base_dir or (Path(tempfile.gettempdir()) / "ufo_ae_pilot_worktrees")
        )

    @staticmethod
    def pilot_overlay(*, plan_step_count: int) -> Dict[str, Any]:
        if plan_step_count < 1:
            raise UFOWorkspaceError("plan must contain at least one measured UI step")

        # FollowerSession spends its first round selecting the application, then
        # one round per supplied plan step.
        max_round = plan_step_count + 2
        max_step = max(50, plan_step_count * 12)

        return {
            "CONTROL_BACKEND": ["uia"],
            "MAX_ROUND": max_round,
            "MAX_STEP": max_step,
            "SAFE_GUARD": True,
            "USE_MCP": False,
            "MCP_FALLBACK_TO_UI": False,
            "EVA_SESSION": False,
            "EVA_ROUND": False,
            "TASK_STATUS": False,
            "SAVE_EXPERIENCE": "always_not",
            "ASK_QUESTION": False,
            "USE_CUSTOMIZATION": False,
            "ENABLED_THIRD_PARTY_AGENTS": [],
            "SAVE_UI_TREE": True,
            "SAVE_FULL_SCREEN": False,
            "LOG_TO_MARKDOWN": True,
            "MAXIMIZE_WINDOW": False,
            "INPUT_TEXT_API": "type_keys",
            "CLICK_API": "click_input",
        }

    def _run_git(self, *args: str, cwd: Optional[Path] = None) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                ["git", *args],
                cwd=str(cwd or self.installation.root),
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise UFOWorkspaceError(f"git command failed: {exc}") from exc

    def create(
        self,
        *,
        plan_step_count: int,
        allow_compatible_fork: bool = False,
    ) -> UFOWorkspace:
        inspection = self.installation.require_launchable(
            allow_compatible_fork=allow_compatible_fork,
            require_clean_tree=True,
        )
        if not inspection.git_head:
            raise UFOWorkspaceError("UFO git HEAD is unavailable")

        self.base_dir.mkdir(parents=True, exist_ok=True)
        root = Path(tempfile.mkdtemp(prefix="run-", dir=self.base_dir))
        # git worktree requires the target path not to exist.
        shutil.rmtree(root)

        result = self._run_git(
            "worktree",
            "add",
            "--detach",
            str(root),
            inspection.git_head,
        )
        if result.returncode != 0:
            raise UFOWorkspaceError(
                "unable to create isolated UFO worktree: "
                + (result.stderr.strip() or result.stdout.strip())
            )

        try:
            overlay = self.pilot_overlay(plan_step_count=plan_step_count)
            config_dir = root / "config" / "ufo"
            if not config_dir.is_dir():
                raise UFOWorkspaceError(
                    f"isolated UFO worktree is missing config/ufo: {root}"
                )

            overlay_path = config_dir / "system_pilot.yaml"
            if overlay_path.exists():
                raise UFOWorkspaceError(
                    "unexpected system_pilot.yaml already exists in source revision"
                )
            overlay_path.write_text(
                yaml.safe_dump(
                    overlay,
                    sort_keys=True,
                    allow_unicode=True,
                ),
                encoding="utf-8",
            )

            return UFOWorkspace(
                source_root=self.installation.root,
                worktree_root=root,
                git_head=inspection.git_head,
                overlay_path=overlay_path,
                max_round=int(overlay["MAX_ROUND"]),
                max_step=int(overlay["MAX_STEP"]),
            )
        except Exception:
            self.remove(root)
            raise

    def remove(self, worktree_root: str | Path) -> None:
        root = Path(worktree_root)
        if not root.exists():
            return

        result = self._run_git(
            "worktree",
            "remove",
            "--force",
            str(root),
        )
        if result.returncode != 0:
            # Defense in depth: clean the temporary directory even when Git's
            # bookkeeping removal fails. Prune metadata afterwards.
            shutil.rmtree(root, ignore_errors=True)
            self._run_git("worktree", "prune")
        else:
            self._run_git("worktree", "prune")
