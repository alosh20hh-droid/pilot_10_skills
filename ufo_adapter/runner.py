"""Measured UFO Follower Mode launcher for the AE pilot.

This launcher never prepares fixtures and never judges success. It invokes only
an exact, locked Microsoft UFO checkout in Follower Mode. The source checkout is
never modified: measured execution happens from a detached Git worktree with a
pilot-only configuration overlay.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

from .lock import load_upstream_lock, require_locked_checkout
from .plan import UFOPlan
from .workspace import UFOWorkspaceError, UFOWorkspaceManager


class UFOExecutionError(RuntimeError):
    pass


@dataclass(frozen=True)
class UFOExecutionResult:
    run_id: str
    skill_id: str
    fixture_id: str
    fixture_path: str
    fixture_sha256: str
    plan_sha256: str
    command: Sequence[str]
    task_name: str
    started_at: float
    finished_at: float
    exit_code: int
    timed_out: bool
    stdout_path: str
    stderr_path: str
    ufo_logs_path: Optional[str]
    ufo_checkout: str
    ufo_commit: str
    isolated_worktree: bool
    overlay_max_round: int
    overlay_max_step: int

    @property
    def process_exit_ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "skill_id": self.skill_id,
            "fixture_id": self.fixture_id,
            "fixture_path": self.fixture_path,
            "fixture_sha256": self.fixture_sha256,
            "plan_sha256": self.plan_sha256,
            "command": list(self.command),
            "task_name": self.task_name,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_seconds": max(0.0, self.finished_at - self.started_at),
            "exit_code": self.exit_code,
            "timed_out": self.timed_out,
            "process_exit_ok": self.process_exit_ok,
            "stdout_path": self.stdout_path,
            "stderr_path": self.stderr_path,
            "ufo_logs_path": self.ufo_logs_path,
            "ufo_checkout": self.ufo_checkout,
            "ufo_commit": self.ufo_commit,
            "isolated_worktree": self.isolated_worktree,
            "overlay_max_round": self.overlay_max_round,
            "overlay_max_step": self.overlay_max_step,
            "execution_mode": "follower",
            "success_oracle": "external_deterministic_verifier",
            "ufo_finish_is_not_success": True,
        }


def _validate_run_id(value: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) > 128
        or not re.fullmatch(
            r"[A-Za-z0-9](?:[A-Za-z0-9._-]{0,126}[A-Za-z0-9])?",
            value,
        )
    ):
        raise UFOExecutionError(
            "run_id must be 1-128 characters, start/end with a letter or number, "
            "and contain only letters, numbers, dot, underscore, or hyphen"
        )
    return value


def _safe_name(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _safe_task_name(skill_id: str, run_id: str) -> str:
    skill = re.sub(r"[^A-Za-z0-9._-]+", "-", skill_id).strip("-") or "skill"
    return f"ae-pilot-{skill}-{_safe_name(run_id)[:12]}"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class UFOMeasuredRunner:
    def __init__(
        self,
        ufo_checkout: str | Path,
        *,
        python_executable: Optional[str] = None,
        output_root: Optional[str | Path] = None,
        run_registry_root: Optional[str | Path] = None,
        worktree_root: Optional[str | Path] = None,
        lock_path: Optional[str | Path] = None,
    ) -> None:
        self.ufo_checkout = Path(ufo_checkout).expanduser().resolve()
        self.python_executable = python_executable or os.environ.get(
            "UFO_PYTHON",
            "python",
        )
        self.output_root = Path(
            output_root
            or (Path(__file__).resolve().parents[1] / "ufo_adapter" / "runs")
        )
        self.run_registry_root = Path(
            run_registry_root
            or (Path(__file__).resolve().parents[1] / "ufo_adapter" / "run_registry")
        )
        self.lock = load_upstream_lock(lock_path)
        self.workspace_manager = UFOWorkspaceManager(
            self.ufo_checkout,
            base_dir=worktree_root,
        )

    def validate_environment(self) -> Dict[str, Any]:
        if platform.system() != "Windows":
            raise UFOExecutionError("Microsoft UFO AE measured execution requires Windows")

        checkout = require_locked_checkout(
            self.ufo_checkout,
            lock=self.lock,
        )

        executable = self.ufo_checkout / "ufo" / "__main__.py"
        if not executable.is_file():
            raise UFOExecutionError(
                f"locked checkout is missing ufo/__main__.py: {executable}"
            )

        return checkout

    def build_command(self, task_name: str, plan_path: Path) -> list[str]:
        if self.lock.get("required_mode") != "follower":
            raise UFOExecutionError("upstream lock does not authorize follower mode")

        return [
            self.python_executable,
            "-m",
            "ufo",
            "--task",
            task_name,
            "--mode",
            "follower",
            "--plan",
            str(plan_path),
            "--log-level",
            "INFO",
        ]

    def _bind_fixture(
        self,
        *,
        run_id: str,
        plan: UFOPlan,
        fixture_path: str | Path,
        fixture_sha256: str,
    ) -> tuple[UFOPlan, Path]:
        run_id = _validate_run_id(run_id)
        path = Path(fixture_path).expanduser().resolve()
        if not path.is_file():
            raise UFOExecutionError(f"disposable fixture file not found: {path}")
        if path.suffix.lower() != ".aep":
            raise UFOExecutionError("measured UFO execution requires a .aep fixture")
        if path.name != f"{plan.fixture_id}.aep":
            raise UFOExecutionError(
                "fixture filename does not match the skill's declared fixture_id"
            )
        expected_run_key = _safe_name(run_id)
        if path.parent.name != expected_run_key:
            raise UFOExecutionError(
                "fixture must come from the run-specific disposable fixture workspace"
            )
        if not isinstance(fixture_sha256, str) or not re.fullmatch(
            r"[0-9a-fA-F]{64}",
            fixture_sha256,
        ):
            raise UFOExecutionError(
                "fixture_sha256 must be a 64-character SHA-256 hex string"
            )
        actual_hash = _sha256_file(path)
        if actual_hash.lower() != fixture_sha256.lower():
            raise UFOExecutionError(
                "disposable fixture hash does not match the certified run-copy hash"
            )
        # The fixture must already be open before the measured UFO run. Keep the
        # Follower object bound to AfterFX.exe so opening the fixture itself is
        # not accidentally counted as a measured UFO action.
        return plan, path

    def prepare_run(
        self,
        *,
        run_id: str,
        plan: UFOPlan,
        fixture_path: str | Path,
        fixture_sha256: str,
    ) -> Dict[str, Any]:
        run_id = _validate_run_id(run_id)
        execution_plan, bound_fixture_path = self._bind_fixture(
            run_id=run_id,
            plan=plan,
            fixture_path=fixture_path,
            fixture_sha256=fixture_sha256,
        )

        run_key = _safe_name(run_id)
        run_dir = self.output_root / run_key
        registry_path = self.run_registry_root / f"{run_key}.json"
        if run_dir.exists() or registry_path.exists():
            raise UFOExecutionError(
                "UFO run_id was already used; measured run identity reuse is forbidden"
            )

        self.output_root.mkdir(parents=True, exist_ok=True)
        self.run_registry_root.mkdir(parents=True, exist_ok=True)
        try:
            handle = os.open(
                registry_path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            )
            with os.fdopen(handle, "w", encoding="utf-8") as registry_file:
                json.dump(
                    {
                        "run_id": run_id,
                        "run_key": run_key,
                        "skill_id": plan.skill_id,
                        "fixture_id": plan.fixture_id,
                        "reserved_at": time.time(),
                    },
                    registry_file,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
        except FileExistsError as exc:
            raise UFOExecutionError(
                "UFO run_id was already used; measured run identity reuse is forbidden"
            ) from exc

        try:
            run_dir.mkdir(parents=True, exist_ok=False)
            plan_path = run_dir / "plan.json"
            metadata_path = run_dir / "metadata.json"

            plan_path.write_bytes(execution_plan.serialized_bytes())
            plan_hash = hashlib.sha256(plan_path.read_bytes()).hexdigest()
            if plan_hash != execution_plan.sha256():
                raise UFOExecutionError("serialized UFO plan hash mismatch")

            metadata = {
                "run_id": run_id,
                "run_key": run_key,
                "skill_id": plan.skill_id,
                "fixture_id": plan.fixture_id,
                "fixture_path": str(bound_fixture_path),
                "fixture_sha256": fixture_sha256.lower(),
                "source_plan_sha256": plan.sha256(),
                "plan_sha256": plan_hash,
                "ufo_required_commit": self.lock.get("commit"),
                "ufo_mode": "follower",
                "success_oracle": "external_deterministic_verifier",
                "ufo_finish_is_not_success": True,
                "prepared_at": time.time(),
            }
            metadata_path.write_text(
                json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True),
                encoding="utf-8",
            )

            return {
                "run_key": run_key,
                "run_dir": run_dir,
                "plan_path": plan_path,
                "metadata_path": metadata_path,
                "plan_sha256": plan_hash,
                "fixture_path": bound_fixture_path,
            }
        except Exception:
            shutil.rmtree(run_dir, ignore_errors=True)
            try:
                registry_path.unlink()
            except FileNotFoundError:
                pass
            raise

    def preview_command(
        self,
        *,
        run_id: str,
        plan: UFOPlan,
        fixture_path: str | Path,
        fixture_sha256: str,
    ) -> Dict[str, Any]:
        run_id = _validate_run_id(run_id)
        execution_plan, bound_fixture_path = self._bind_fixture(
            run_id=run_id,
            plan=plan,
            fixture_path=fixture_path,
            fixture_sha256=fixture_sha256,
        )
        run_key = _safe_name(run_id)
        plan_path = self.output_root / run_key / "plan.json"
        task_name = _safe_task_name(plan.skill_id, run_id)
        command = self.build_command(
            task_name=task_name,
            plan_path=plan_path,
        )
        overlay = self.workspace_manager.build_overlay(len(plan.to_dict()["steps"]))
        return {
            "run_id": run_id,
            "run_key": run_key,
            "task_name": task_name,
            "plan_path": str(plan_path),
            "source_plan_sha256": plan.sha256(),
            "plan_sha256": execution_plan.sha256(),
            "fixture_path": str(bound_fixture_path),
            "fixture_sha256": fixture_sha256.lower(),
            "command": command,
            "execution_overlay": overlay,
            "note": "Preview only; the source UFO checkout will not be modified.",
        }

    @staticmethod
    def _terminate_process_tree(process: subprocess.Popen) -> None:
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
        run_id: str,
        plan: UFOPlan,
        fixture_path: str | Path,
        fixture_sha256: str,
        arm_measured_execution: bool = False,
        timeout: Optional[float] = None,
    ) -> UFOExecutionResult:
        if not arm_measured_execution:
            raise UFOExecutionError(
                "measured UFO execution refused: arm_measured_execution must be true"
            )
        if timeout is not None and timeout <= 0:
            raise UFOExecutionError("timeout must be positive")

        checkout = self.validate_environment()
        prepared = self.prepare_run(
            run_id=run_id,
            plan=plan,
            fixture_path=fixture_path,
            fixture_sha256=fixture_sha256,
        )

        run_dir: Path = prepared["run_dir"]
        stdout_path = run_dir / "stdout.log"
        stderr_path = run_dir / "stderr.log"
        result_path = run_dir / "execution_result.json"
        ufo_logs_path = run_dir / "ufo_logs"

        task_name = _safe_task_name(plan.skill_id, run_id)
        command = self.build_command(
            task_name=task_name,
            plan_path=prepared["plan_path"],
        )

        try:
            workspace = self.workspace_manager.create(
                commit=str(checkout["head"]),
                measured_step_count=len(plan.to_dict()["steps"]),
            )
        except UFOWorkspaceError as exc:
            raise UFOExecutionError(
                f"unable to create isolated UFO execution worktree: {exc}"
            ) from exc

        env = os.environ.copy()
        env["UFO_ENV"] = "test"
        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"

        started_at = time.time()
        process: Optional[subprocess.Popen] = None
        exit_code = -1
        timed_out = False

        try:
            with stdout_path.open("w", encoding="utf-8") as stdout_file, stderr_path.open(
                "w", encoding="utf-8"
            ) as stderr_file:
                try:
                    process = subprocess.Popen(
                        command,
                        cwd=workspace.worktree_root,
                        env=env,
                        stdout=stdout_file,
                        stderr=stderr_file,
                        text=True,
                    )
                except OSError as exc:
                    raise UFOExecutionError(f"unable to launch UFO: {exc}") from exc

                try:
                    exit_code = int(process.wait(timeout=timeout))
                except subprocess.TimeoutExpired:
                    timed_out = True
                    self._terminate_process_tree(process)
                    try:
                        exit_code = int(process.wait(timeout=10))
                    except subprocess.TimeoutExpired:
                        exit_code = -1

            source_logs = Path(workspace.worktree_root) / "logs" / task_name
            if source_logs.is_dir():
                shutil.copytree(source_logs, ufo_logs_path)

            finished_at = time.time()
            result = UFOExecutionResult(
                run_id=run_id,
                skill_id=plan.skill_id,
                fixture_id=plan.fixture_id,
                fixture_path=str(prepared["fixture_path"]),
                fixture_sha256=fixture_sha256.lower(),
                plan_sha256=prepared["plan_sha256"],
                command=command,
                task_name=task_name,
                started_at=started_at,
                finished_at=finished_at,
                exit_code=exit_code,
                timed_out=timed_out,
                stdout_path=str(stdout_path.resolve()),
                stderr_path=str(stderr_path.resolve()),
                ufo_logs_path=(
                    str(ufo_logs_path.resolve())
                    if ufo_logs_path.is_dir()
                    else None
                ),
                ufo_checkout=str(self.ufo_checkout),
                ufo_commit=str(checkout["head"]),
                isolated_worktree=True,
                overlay_max_round=workspace.max_round,
                overlay_max_step=workspace.max_step,
            )

            result_path.write_text(
                json.dumps(result.to_dict(), ensure_ascii=False, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            return result
        finally:
            if process is not None and process.poll() is None:
                self._terminate_process_tree(process)
            self.workspace_manager.remove(workspace.worktree_root)
