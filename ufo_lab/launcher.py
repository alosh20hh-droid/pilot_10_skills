"""Launch an existing UFO checkout in isolated Follower Mode for one pilot skill."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from verifier.contract import PilotContract

from .installation import UFOInstallation, UFOInspection, UFOReferenceLock
from .plan import CompiledUFOPlan, compile_skill_plan, write_compiled_plan
from .workspace import UFOWorkspaceManager


class UFOExecutionError(RuntimeError):
    pass


def _run_key(run_id: str) -> str:
    return hashlib.sha256(run_id.encode("utf-8")).hexdigest()


def _safe_task_name(skill_id: str, run_id: str) -> str:
    digest = _run_key(run_id)[:12]
    base = re.sub(r"[^A-Za-z0-9._-]+", "-", skill_id).strip("-") or "skill"
    return f"ae-pilot-{base}-{digest}"


@dataclass(frozen=True)
class UFOExecutionRecord:
    skill_id: str
    fixture_id: str
    run_id: str
    task_name: str
    ufo_root: str
    ufo_git_head: str
    ufo_git_remote: Optional[str]
    exact_reference_commit: bool
    plan_sha256: str
    started_at: float
    finished_at: float
    duration_seconds: float
    process_returncode: Optional[int]
    process_exit_zero: bool
    timed_out: bool
    stdout_path: str
    stderr_path: str
    plan_path: str
    plan_manifest_path: str
    ufo_logs_path: Optional[str]
    execution_mode: str = "follower"
    success_oracle: str = "external_deterministic_verifier"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            "fixture_id": self.fixture_id,
            "run_id": self.run_id,
            "task_name": self.task_name,
            "ufo_root": self.ufo_root,
            "ufo_git_head": self.ufo_git_head,
            "ufo_git_remote": self.ufo_git_remote,
            "exact_reference_commit": self.exact_reference_commit,
            "plan_sha256": self.plan_sha256,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_seconds": self.duration_seconds,
            "process_returncode": self.process_returncode,
            "process_exit_zero": self.process_exit_zero,
            "timed_out": self.timed_out,
            "stdout_path": self.stdout_path,
            "stderr_path": self.stderr_path,
            "plan_path": self.plan_path,
            "plan_manifest_path": self.plan_manifest_path,
            "ufo_logs_path": self.ufo_logs_path,
            "execution_mode": self.execution_mode,
            "success_oracle": self.success_oracle,
            "ufo_finish_is_not_success": True,
        }


class UFOFollowerExecutor:
    def __init__(
        self,
        contract: PilotContract,
        lock: UFOReferenceLock,
        installation: UFOInstallation,
        *,
        artifact_root: Optional[str | Path] = None,
        python_executable: Optional[str] = None,
    ) -> None:
        self.contract = contract
        self.lock = lock
        self.installation = installation
        root = Path(__file__).resolve().parents[1]
        self.artifact_root = Path(
            artifact_root or (root / "ufo_lab" / "executions")
        )
        self.python_executable = python_executable or sys.executable
        self.workspace_manager = UFOWorkspaceManager(installation)

    def _prepare_artifact_directory(self, run_id: str) -> Path:
        if not isinstance(run_id, str) or not run_id:
            raise UFOExecutionError("run_id must be a non-empty string")
        directory = self.artifact_root / _run_key(run_id)
        if directory.exists():
            raise UFOExecutionError(
                "UFO execution artifact directory already exists; run_id reuse is forbidden"
            )
        directory.mkdir(parents=True, exist_ok=False)
        return directory

    @staticmethod
    def _terminate_process_tree(process: subprocess.Popen[str]) -> None:
        if process.poll() is not None:
            return
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                text=True,
                check=False,
            )
        else:
            try:
                process.terminate()
                process.wait(timeout=5)
            except Exception:
                try:
                    process.kill()
                except Exception:
                    pass

    def execute(
        self,
        *,
        skill_id: str,
        run_id: str,
        timeout: float = 900.0,
        allow_compatible_fork: bool = False,
        object_name: str = "Adobe After Effects",
    ) -> UFOExecutionRecord:
        if timeout <= 0:
            raise UFOExecutionError("timeout must be positive")

        compiled = compile_skill_plan(
            self.contract,
            skill_id,
            object_name=object_name,
        )
        inspection = self.installation.require_launchable(
            allow_compatible_fork=allow_compatible_fork,
            require_clean_tree=True,
        )

        artifacts = self._prepare_artifact_directory(run_id)
        plan_path = artifacts / f"{skill_id}.plan.json"
        manifest_path = artifacts / f"{skill_id}.plan.manifest.json"
        write_compiled_plan(
            compiled,
            plan_path,
            manifest_path=manifest_path,
        )

        workspace = self.workspace_manager.create(
            plan_step_count=len(compiled.steps),
            allow_compatible_fork=allow_compatible_fork,
        )

        task_name = _safe_task_name(skill_id, run_id)
        stdout_path = artifacts / "ufo.stdout.log"
        stderr_path = artifacts / "ufo.stderr.log"
        ufo_logs_destination = artifacts / "ufo_logs"
        started_at = time.time()
        timed_out = False
        returncode: Optional[int] = None

        env = os.environ.copy()
        env["UFO_ENV"] = "pilot"
        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"

        command = [
            self.python_executable,
            "-m",
            "ufo",
            "--task",
            task_name,
            "--mode",
            "follower",
            "--plan",
            str(plan_path.resolve()),
            "--log-level",
            "INFO",
        ]

        process: Optional[subprocess.Popen[str]] = None
        try:
            with stdout_path.open("w", encoding="utf-8") as stdout_file, stderr_path.open(
                "w", encoding="utf-8"
            ) as stderr_file:
                try:
                    process = subprocess.Popen(
                        command,
                        cwd=str(workspace.worktree_root),
                        env=env,
                        stdout=stdout_file,
                        stderr=stderr_file,
                        text=True,
                    )
                except (OSError, ValueError) as exc:
                    raise UFOExecutionError(f"unable to start UFO: {exc}") from exc

                try:
                    returncode = process.wait(timeout=float(timeout))
                except subprocess.TimeoutExpired:
                    timed_out = True
                    self._terminate_process_tree(process)
                    try:
                        returncode = process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        returncode = None

            source_logs = workspace.worktree_root / "logs" / task_name
            if source_logs.is_dir():
                shutil.copytree(source_logs, ufo_logs_destination)

            finished_at = time.time()
            record = UFOExecutionRecord(
                skill_id=skill_id,
                fixture_id=compiled.fixture_id,
                run_id=run_id,
                task_name=task_name,
                ufo_root=str(self.installation.root),
                ufo_git_head=inspection.git_head or "",
                ufo_git_remote=inspection.git_remote,
                exact_reference_commit=inspection.exact_reference_commit,
                plan_sha256=compiled.plan_sha256,
                started_at=started_at,
                finished_at=finished_at,
                duration_seconds=max(0.0, finished_at - started_at),
                process_returncode=returncode,
                process_exit_zero=(returncode == 0 and not timed_out),
                timed_out=timed_out,
                stdout_path=str(stdout_path.resolve()),
                stderr_path=str(stderr_path.resolve()),
                plan_path=str(plan_path.resolve()),
                plan_manifest_path=str(manifest_path.resolve()),
                ufo_logs_path=(
                    str(ufo_logs_destination.resolve())
                    if ufo_logs_destination.is_dir()
                    else None
                ),
            )
            (artifacts / "execution.json").write_text(
                json.dumps(record.to_dict(), ensure_ascii=False, indent=2, sort_keys=True)
                + "\n",
                encoding="utf-8",
            )
            return record
        finally:
            if process is not None and process.poll() is None:
                self._terminate_process_tree(process)
            self.workspace_manager.remove(workspace.worktree_root)
