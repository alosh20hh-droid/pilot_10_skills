"""Windows fixture builder orchestration.

This module is intentionally separate from measured skill execution. It drives
After Effects only to create disposable canonical test fixtures before a pilot
run exists.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from verifier.contract import PilotContract

from .spec import FixtureBuildPlan, compile_fixture_plan


class FixtureBuildError(RuntimeError):
    pass


class FixtureBuilder:
    def __init__(
        self,
        contract: PilotContract,
        *,
        afterfx_path: Optional[str] = None,
        work_dir: Optional[str] = None,
        script_path: Optional[str] = None,
        json2_path: Optional[str] = None,
    ) -> None:
        root = Path(__file__).resolve().parents[1]
        self.contract = contract
        self.afterfx_path = afterfx_path
        self.work_dir = Path(
            work_dir or (Path(tempfile.gettempdir()) / "ae_fixture_builder")
        )
        self.script_path = Path(
            script_path or (root / "fixtures" / "scripts" / "build_fixture.jsx")
        )
        self.json2_path = Path(
            json2_path or (root / "ae_reader" / "scripts" / "json2.jsx")
        )

    def _locate_afterfx(self) -> Optional[Path]:
        if self.afterfx_path:
            path = Path(self.afterfx_path).expanduser()
            return path if path.is_file() else None

        for key in ("UFO_AFTERFX_PATH", "AFTERFX_PATH"):
            configured = os.environ.get(key)
            if configured:
                path = Path(configured).expanduser()
                if path.is_file():
                    return path

        root = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Adobe"
        candidates = sorted(
            root.glob("Adobe After Effects */Support Files/AfterFX.exe"),
            key=lambda path: str(path).lower(),
        )
        return candidates[-1] if candidates else None

    def _prepare_request(self, plan: FixtureBuildPlan, output_path: Path) -> Path:
        if not self.script_path.is_file():
            raise FixtureBuildError(f"fixture builder script missing: {self.script_path}")
        if not self.json2_path.is_file():
            raise FixtureBuildError(f"json2 runtime missing: {self.json2_path}")

        request_dir = self.work_dir / str(uuid.uuid4())
        request_dir.mkdir(parents=True, exist_ok=False)

        shutil.copyfile(self.script_path, request_dir / "build_fixture.jsx")
        shutil.copyfile(self.json2_path, request_dir / "json2.jsx")

        request = plan.to_request(str(output_path.resolve()))
        temporary = request_dir / "request.tmp"
        temporary.write_text(
            json.dumps(request, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        os.replace(temporary, request_dir / "request.json")
        return request_dir

    def build(
        self,
        fixture_id: str,
        output_path: str | Path,
        *,
        timeout: float = 30.0,
        poll_interval: float = 0.1,
        acknowledge_disposable_project: bool = False,
    ) -> Dict[str, Any]:
        if not acknowledge_disposable_project:
            raise FixtureBuildError(
                "fixture build refused: acknowledge_disposable_project must be true "
                "because the fixture builder closes the current AE project without saving"
            )

        output = Path(output_path).expanduser()
        output.parent.mkdir(parents=True, exist_ok=True)
        if output.exists():
            raise FixtureBuildError(f"fixture output already exists: {output}")

        executable = self._locate_afterfx()
        if executable is None:
            raise FixtureBuildError("AfterFX.exe was not found")

        plan = compile_fixture_plan(self.contract, fixture_id)
        request_dir = self._prepare_request(plan, output)
        result_path = request_dir / "build_result.json"
        started_at = time.time()

        try:
            try:
                subprocess.Popen(
                    [
                        str(executable),
                        "-r",
                        str(request_dir / "build_fixture.jsx"),
                    ],
                    close_fds=True,
                )
            except (OSError, ValueError) as exc:
                raise FixtureBuildError(f"After Effects launch failed: {exc}") from exc

            deadline = time.monotonic() + max(0.0, float(timeout))
            while time.monotonic() <= deadline:
                if result_path.is_file():
                    try:
                        result = json.loads(result_path.read_text(encoding="utf-8"))
                    except (OSError, ValueError, UnicodeError) as exc:
                        raise FixtureBuildError(
                            f"invalid fixture build result: {exc}"
                        ) from exc

                    if not isinstance(result, dict):
                        raise FixtureBuildError("fixture build result must be an object")
                    if result.get("fixture_id") != fixture_id:
                        raise FixtureBuildError("fixture build returned wrong fixture_id")
                    if result.get("status") != "SAVED":
                        raise FixtureBuildError(
                            f"fixture build failed: {result.get('error') or result.get('status')}"
                        )
                    if not output.is_file():
                        raise FixtureBuildError(
                            "After Effects reported SAVED but the .aep file is missing"
                        )

                    result = dict(result)
                    result["started_at"] = started_at
                    result["finished_at"] = time.time()
                    result["output_path"] = str(output.resolve())
                    return result

                time.sleep(max(0.02, float(poll_interval)))

            raise FixtureBuildError(
                f"fixture build timed out after {timeout:.1f}s: {fixture_id}"
            )
        finally:
            shutil.rmtree(request_dir, ignore_errors=True)
