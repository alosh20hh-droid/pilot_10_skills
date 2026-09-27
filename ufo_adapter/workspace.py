"""Isolated measured-execution worktree for the pinned Microsoft UFO checkout."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import yaml


class UFOWorkspaceError(RuntimeError):
    pass


@dataclass(frozen=True)
class UFOWorkspace:
    source_checkout: str
    worktree_root: str
    commit: str
    overlay_path: str
    mcp_policy_path: str
    max_round: int
    max_step: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_checkout": self.source_checkout,
            "worktree_root": self.worktree_root,
            "commit": self.commit,
            "overlay_path": self.overlay_path,
            "mcp_policy_path": self.mcp_policy_path,
            "ufo_env": "test",
            "max_round": self.max_round,
            "max_step": self.max_step,
        }


class UFOWorkspaceManager:
    """
    Execute UFO from a detached Git worktree so the user's existing checkout is
    never modified by the pilot-only configuration overlay.
    """

    def __init__(
        self,
        source_checkout: str | Path,
        *,
        base_dir: Optional[str | Path] = None,
    ) -> None:
        self.source_checkout = Path(source_checkout).expanduser().resolve()
        self.base_dir = Path(
            base_dir or (Path(tempfile.gettempdir()) / "ae_pilot_ufo_worktrees")
        )

    @staticmethod
    def build_overlay(measured_step_count: int) -> Dict[str, Any]:
        if (
            not isinstance(measured_step_count, int)
            or isinstance(measured_step_count, bool)
            or measured_step_count < 1
        ):
            raise UFOWorkspaceError("measured_step_count must be a positive integer")

        # Pinned upstream FollowerSession spends round 0 selecting the app and
        # then one round per plan step. Upstream system.yaml defaults MAX_ROUND
        # to 1, which would stop before the measured steps. Give the follower
        # enough deterministic room for app selection + every declared step.
        max_round = measured_step_count + 2
        max_step = max(50, measured_step_count * 12)

        return {
            "CONTROL_BACKEND": ["uia"],
            "MAX_ROUND": max_round,
            "MAX_STEP": max_step,
            "SAFE_GUARD": True,
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
            "SAVE_UI_TREE": True,
            "SAVE_FULL_SCREEN": False,
            "LOG_TO_MARKDOWN": True,
            "MAXIMIZE_WINDOW": False,
            "INPUT_TEXT_API": "type_keys",
            "CLICK_API": "click_input",
        }


    @staticmethod
    def build_ui_only_mcp_policy() -> Dict[str, Any]:
        """
        UFO's local UI tools are transported through its MCP plumbing. The
        measured lab must therefore keep only UI collection/execution servers
        while removing command-line, COM, hardware, Bash, and other action
        namespaces from the temporary worktree configuration.
        """
        return {
            "HostAgent": {
                "default": {
                    "data_collection": [
                        {
                            "namespace": "UICollector",
                            "type": "local",
                            "start_args": [],
                            "reset": False,
                        }
                    ],
                    "action": [
                        {
                            "namespace": "HostUIExecutor",
                            "type": "local",
                            "start_args": [],
                            "reset": False,
                        }
                    ],
                }
            },
            "AppAgent": {
                "default": {
                    "data_collection": [
                        {
                            "namespace": "UICollector",
                            "type": "local",
                            "start_args": [],
                            "reset": False,
                        }
                    ],
                    "action": [
                        {
                            "namespace": "AppUIExecutor",
                            "type": "local",
                            "start_args": [],
                            "reset": False,
                        }
                    ],
                }
            },
        }

    def _git(self, *args: str, timeout: float = 60.0) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                ["git", "-C", str(self.source_checkout), *args],
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise UFOWorkspaceError(f"git worktree command failed: {exc}") from exc

    def create(
        self,
        *,
        commit: str,
        measured_step_count: int,
    ) -> UFOWorkspace:
        if not isinstance(commit, str) or len(commit) != 40:
            raise UFOWorkspaceError("a full pinned UFO commit SHA is required")

        overlay = self.build_overlay(measured_step_count)
        mcp_policy = self.build_ui_only_mcp_policy()

        self.base_dir.mkdir(parents=True, exist_ok=True)
        target = Path(tempfile.mkdtemp(prefix="run-", dir=self.base_dir))
        # git worktree add requires a non-existing target.
        shutil.rmtree(target)

        result = self._git(
            "worktree",
            "add",
            "--detach",
            str(target),
            commit,
        )
        if result.returncode != 0:
            raise UFOWorkspaceError(
                "unable to create isolated UFO worktree: "
                + (result.stderr.strip() or result.stdout.strip())
            )

        try:
            config_dir = target / "config" / "ufo"
            if not config_dir.is_dir():
                raise UFOWorkspaceError(
                    "isolated UFO worktree is missing config/ufo"
                )
            overlay_path = config_dir / "system_test.yaml"
            if overlay_path.exists():
                raise UFOWorkspaceError(
                    "pinned UFO revision unexpectedly already contains system_test.yaml"
                )
            overlay_path.write_text(
                yaml.safe_dump(
                    overlay,
                    sort_keys=True,
                    allow_unicode=True,
                ),
                encoding="utf-8",
            )

            mcp_policy_path = config_dir / "mcp.yaml"
            if not mcp_policy_path.is_file():
                raise UFOWorkspaceError(
                    "pinned UFO revision is missing config/ufo/mcp.yaml"
                )
            mcp_policy_path.write_text(
                yaml.safe_dump(
                    mcp_policy,
                    sort_keys=True,
                    allow_unicode=True,
                ),
                encoding="utf-8",
            )

            return UFOWorkspace(
                source_checkout=str(self.source_checkout),
                worktree_root=str(target.resolve()),
                commit=commit,
                overlay_path=str(overlay_path.resolve()),
                mcp_policy_path=str(mcp_policy_path.resolve()),
                max_round=int(overlay["MAX_ROUND"]),
                max_step=int(overlay["MAX_STEP"]),
            )
        except Exception:
            self.remove(target)
            raise

    def remove(self, worktree_root: str | Path) -> None:
        target = Path(worktree_root)
        if not target.exists():
            self._git("worktree", "prune")
            return

        result = self._git("worktree", "remove", "--force", str(target))
        if result.returncode != 0:
            shutil.rmtree(target, ignore_errors=True)
        self._git("worktree", "prune")
