"""Measured UFO Follower Mode launcher for the AE pilot.

This launcher never prepares fixtures and never judges success. It only invokes
a locked Microsoft UFO checkout with a generated Follower Mode plan.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

from .lock import UFOLockError, load_upstream_lock, require_locked_checkout
from .plan import UFOPlan


class UFOExecutionError(RuntimeError):
    pass


@dataclass(frozen=True)
class UFOExecutionResult:
    run_id: str
    skill_id: str
    plan_sha256: str
    command: Sequence[str]
    started_at: float
    finished_at: float
    exit_code: int
    stdout_path: str
    stderr_path: str
    ufo_checkout: str
    ufo_commit: str

    @property
    def process_exit_ok(self) -> bool:
        return self.exit_code == 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "skill_id": self.skill_id,
            "plan_sha256": self.plan_sha256,
            "command": list(self.command),
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "exit_code": self.exit_code,
            "process_exit_ok": self.process_exit_ok,
            "stdout_path": self.stdout_path,
            "stderr_path": self.stderr_path,
            "ufo_checkout": self.ufo_checkout,
            "ufo_commit": self.ufo_commit,
        }


def _validate_run_id(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9._-]+", value):
        raise UFOExecutionError(
            "run_id must contain only letters, numbers, dot, underscore, or hyphen"
        )
    return value


def _safe_name(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


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
        self.lock = load_upstream_lock(lock_path)

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
        plan: UFOPlan,
        fixture_path: str | Path,
        fixture_sha256: str,
    ) -> tuple[UFOPlan, Path]:
        path = Path(fixture_path).expanduser().resolve()
        if not path.is_file():
            raise UFOExecutionError(f"disposable fixture file not found: {path}")
        if path.suffix.lower() != ".aep":
            raise UFOExecutionError("measured UFO execution requires a .aep fixture")
        if path.name != f"{plan.fixture_id}.aep":
            raise UFOExecutionError(
                "fixture filename does not match the skill's declared fixture_id"
            )
        if not isinstance(fixture_sha256, str) or not re.fullmatch(
            r"[0-9a-fA-F]{64}",
            fixture_sha256,
        ):
            raise UFOExecutionError("fixture_sha256 must be a 64-character SHA-256 hex string")
        actual_hash = _sha256_file(path)
        if actual_hash.lower() != fixture_sha256.lower():
            raise UFOExecutionError(
                "disposable fixture hash does not match the certified run-copy hash"
            )
        # The fixture must already be open before the measured UFO run.
        # Keep the Follower plan object bound to AfterFX.exe so opening the
        # fixture itself is not accidentally counted as a measured UFO action.
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
            plan=plan,
            fixture_path=fixture_path,
            fixture_sha256=fixture_sha256,
        )

        run_key = _safe_name(run_id)
        run_dir = self.output_root / run_key
        if run_dir.exists():
            raise UFOExecutionError("UFO run directory already exists; run_id reuse is forbidden")

        run_dir.mkdir(parents=True, exist_ok=False)
        plan_path = run_dir / "plan.json"
        metadata_path = run_dir / "metadata.json"

        plan_path.write_bytes(execution_plan.serialized_bytes())

        plan_hash = hashlib.sha256(plan_path.read_bytes()).hexdigest()
        if plan_hash != execution_plan.sha256():
            raise UFOExecutionError("serialized UFO plan hash mismatch")
        metadata = {
            "run_id": run_id,
            "skill_id": plan.skill_id,
            "fixture_id": plan.fixture_id,
            "fixture_path": str(bound_fixture_path),
            "fixture_sha256": fixture_sha256.lower(),
            "source_plan_sha256": plan.sha256(),
            "plan_sha256": plan_hash,
            "ufo_required_commit": self.lock.get("commit"),
            "ufo_mode": "follower",
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
        }

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
            plan=plan,
            fixture_path=fixture_path,
            fixture_sha256=fixture_sha256,
        )
        run_key = _safe_name(run_id)
        plan_path = self.output_root / run_key / "plan.json"
        command = self.build_command(
            task_name=f"pilot/{plan.skill_id}/{run_id}",
            plan_path=plan_path,
        )
        return {
            "run_id": run_id,
            "run_key": run_key,
            "plan_path": str(plan_path),
            "source_plan_sha256": plan.sha256(),
            "plan_sha256": execution_plan.sha256(),
            "fixture_path": str(bound_fixture_path),
            "fixture_sha256": fixture_sha256.lower(),
            "command": command,
        }

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

        command = self.build_command(
            task_name=f"pilot/{plan.skill_id}/{run_id}",
            plan_path=prepared["plan_path"],
        )
        started_at = time.time()

        try:
            with stdout_path.open("w", encoding="utf-8") as stdout_file, stderr_path.open(
                "w", encoding="utf-8"
            ) as stderr_file:
                process = subprocess.run(
                    command,
                    cwd=str(self.ufo_checkout),
                    stdout=stdout_file,
                    stderr=stderr_file,
                    text=True,
                    timeout=timeout,
                    check=False,
                )
            exit_code = int(process.returncode)
        except subprocess.TimeoutExpired as exc:
            finished_at = time.time()
            payload = {
                "run_id": run_id,
                "skill_id": plan.skill_id,
                "status": "TIMEOUT",
                "started_at": started_at,
                "finished_at": finished_at,
                "timeout": timeout,
                "plan_sha256": prepared["plan_sha256"],
                "command": command,
            }
            result_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            raise UFOExecutionError(f"UFO measured execution timed out: {exc}") from exc
        except OSError as exc:
            raise UFOExecutionError(f"unable to launch UFO: {exc}") from exc

        finished_at = time.time()
        result = UFOExecutionResult(
            run_id=run_id,
            skill_id=plan.skill_id,
            plan_sha256=prepared["plan_sha256"],
            command=command,
            started_at=started_at,
            finished_at=finished_at,
            exit_code=exit_code,
            stdout_path=str(stdout_path.resolve()),
            stderr_path=str(stderr_path.resolve()),
            ufo_checkout=str(self.ufo_checkout),
            ufo_commit=str(checkout["head"]),
        )

        result_path.write_text(
            json.dumps(result.to_dict(), ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return result
