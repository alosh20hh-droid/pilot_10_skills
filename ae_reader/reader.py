"""Windows read-only After Effects observer with isolated, fail-closed IPC."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Iterable, Optional

from .schema import (
    AECapabilityManifest,
    AEReadRequest,
    AEStateSnapshot,
    READER_VERSION,
    SCHEMA_VERSION,
    invalid_state,
)


class AfterEffectsReadOnlyObserver:
    """Request a read-only JSX snapshot through a request-isolated directory."""

    def __init__(
        self,
        afterfx_path: Optional[str] = None,
        ipc_dir: Optional[str] = None,
        script_path: Optional[str] = None,
        json2_path: Optional[str] = None,
        capabilities_path: Optional[str] = None,
        retain_failed_requests: bool = False,
    ):
        root = Path(__file__).resolve().parent
        self.afterfx_path = afterfx_path
        self.ipc_dir = Path(ipc_dir or (Path(tempfile.gettempdir()) / "ufo_ae_reader_v2"))
        self.script_path = Path(script_path or (root / "scripts" / "read_state.jsx"))
        self.json2_path = Path(json2_path or (root / "scripts" / "json2.jsx"))
        self.capabilities_path = Path(capabilities_path or (root / "capabilities.json"))
        self.retain_failed_requests = bool(retain_failed_requests)
        self._registry_lock = threading.Lock()
        self._request_registry = {}
        self._manifest = self._load_manifest()

    @property
    def capability_manifest(self) -> AECapabilityManifest:
        return self._manifest

    def missing_capabilities(self, required: Iterable[str]) -> list[str]:
        return self._manifest.missing(required)

    def _load_manifest(self) -> AECapabilityManifest:
        try:
            data = json.loads(self.capabilities_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeError) as exc:
            raise RuntimeError(f"Unable to load AE Reader capability manifest: {exc}") from exc
        manifest = AECapabilityManifest.from_dict(data)
        if manifest.reader_version != READER_VERSION or manifest.schema_version != SCHEMA_VERSION:
            raise RuntimeError("AE Reader capability manifest version does not match Python schema")
        return manifest

    @staticmethod
    def _opaque_key(value: str) -> str:
        return hashlib.sha256(str(value).encode("utf-8")).hexdigest()

    @staticmethod
    def _validate_request_id(request_id: str) -> str:
        value = str(request_id)
        if not re.fullmatch(r"[A-Za-z0-9._-]+", value):
            raise ValueError("request_id is not a safe path component")
        return value

    def _request_directory(self, request: AEReadRequest) -> Path:
        request_id = self._validate_request_id(request.request_id)
        return self.ipc_dir / self._opaque_key(request.run_id) / request_id

    def _register_request(self, request: AEReadRequest, directory: Path) -> None:
        request_id = self._validate_request_id(request.request_id)
        with self._registry_lock:
            if request_id in self._request_registry:
                raise RuntimeError(f"request_id already exists: {request_id}")
            self._request_registry[request_id] = {
                "status": "ACTIVE",
                "directory": directory,
                "run_key": self._opaque_key(request.run_id),
                "request_id": request_id,
            }

    def _set_request_status(self, request_id: str, status: str) -> None:
        with self._registry_lock:
            record = self._request_registry.get(request_id)
            if record is not None:
                record["status"] = status

    def _prepare_request_directory(self, request: AEReadRequest) -> Path:
        required_files = (self.script_path, self.json2_path, self.capabilities_path)
        missing = [str(path) for path in required_files if not path.is_file()]
        if missing:
            raise FileNotFoundError("AE Reader runtime file(s) missing: " + ", ".join(missing))

        request_directory = self._request_directory(request)
        request_directory.parent.mkdir(parents=True, exist_ok=True)
        request_directory.mkdir(exist_ok=False)

        try:
            self._register_request(request, request_directory)
            shutil.copyfile(self.script_path, request_directory / "read_state.jsx")
            shutil.copyfile(self.json2_path, request_directory / "json2.jsx")
            shutil.copyfile(self.capabilities_path, request_directory / "capabilities.json")

            temporary = request_directory / "request.tmp"
            temporary.write_text(
                json.dumps(request.to_dict(), ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8",
            )
            os.replace(temporary, request_directory / "request.json")
            return request_directory
        except Exception:
            self._safe_cleanup(request_directory, force=True)
            raise

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

    def _invalid(self, request: AEReadRequest, status: str, error: str) -> AEStateSnapshot:
        return invalid_state(request, status, error, self._manifest)

    def _read_response(
        self,
        request: AEReadRequest,
        request_directory: Optional[Path] = None,
    ) -> AEStateSnapshot:
        expected_directory = self._request_directory(request)
        path = Path(request_directory) if request_directory is not None else expected_directory

        if path.resolve() != expected_directory.resolve():
            return self._invalid(request, "STALE_RESPONSE", "request directory mismatch")

        response_path = path / "response.json"
        try:
            data = json.loads(response_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return self._invalid(request, "TIMEOUT", "After Effects did not return response.json")
        except (OSError, ValueError, UnicodeError) as exc:
            return self._invalid(request, "INVALID_RESPONSE", f"invalid response JSON: {exc}")

        try:
            response = AEStateSnapshot.from_dict(data)
        except ValueError as exc:
            return self._invalid(request, "INVALID_RESPONSE", str(exc))

        if response.request_id != request.request_id:
            return self._invalid(request, "STALE_RESPONSE", "request_id mismatch")
        if response.run_id != request.run_id:
            return self._invalid(request, "STALE_RESPONSE", "run_id mismatch")
        if response.session_id != request.session_id:
            return self._invalid(request, "STALE_RESPONSE", "session_id mismatch")
        if response.lesson_id != request.lesson_id:
            return self._invalid(request, "STALE_RESPONSE", "lesson_id mismatch")
        if response.step_id != request.step_id:
            return self._invalid(request, "STALE_RESPONSE", "step_id mismatch")
        if response.captured_at is None or response.captured_at < request.requested_at:
            return self._invalid(request, "STALE_RESPONSE", "response predates request")
        if response.capabilities.to_dict() != self._manifest.to_dict():
            return self._invalid(request, "INVALID_RESPONSE", "capability manifest mismatch")
        return response

    def read_state(
        self,
        session_id: str = "",
        lesson_id: str = "",
        step_id: str = "",
        timeout: float = 10.0,
        poll_interval: float = 0.05,
        *,
        run_id: Optional[str] = None,
    ) -> AEStateSnapshot:
        """
        Capture one state snapshot.

        The positional session/lesson/step arguments are kept for compatibility
        with the original AE-R1 caller. New pilot code should pass run_id.
        """
        effective_run_id = str(run_id or session_id or ("run-" + str(uuid.uuid4())))
        request = AEReadRequest(
            request_id=str(uuid.uuid4()),
            run_id=effective_run_id,
            requested_at=time.time(),
            session_id=str(session_id) if session_id else None,
            lesson_id=str(lesson_id) if lesson_id else None,
            step_id=str(step_id) if step_id else None,
        )

        request_directory: Optional[Path] = None
        result: Optional[AEStateSnapshot] = None

        try:
            request_directory = self._prepare_request_directory(request)
            executable = self._locate_afterfx()
            if executable is None:
                self._set_request_status(request.request_id, "INVALID")
                result = self._invalid(request, "AE_NOT_AVAILABLE", "AfterFX.exe was not found")
                return result

            script = request_directory / "read_state.jsx"
            try:
                subprocess.Popen(
                    [str(executable), "-r", str(script)],
                    close_fds=True,
                )
            except (OSError, ValueError) as exc:
                self._set_request_status(request.request_id, "INVALID")
                result = self._invalid(request, "AE_NOT_AVAILABLE", f"AfterFX launch failed: {exc}")
                return result

            deadline = time.monotonic() + max(0.0, float(timeout))
            response_path = request_directory / "response.json"

            while time.monotonic() <= deadline:
                if response_path.is_file():
                    result = self._read_response(request, request_directory)
                    self._set_request_status(
                        request.request_id,
                        "COMPLETE" if result.status == "OK" else "INVALID",
                    )
                    return result
                time.sleep(max(0.01, float(poll_interval)))

            self._set_request_status(request.request_id, "TIMEOUT")
            result = self._invalid(
                request,
                "TIMEOUT",
                "matching response did not arrive before timeout",
            )
            return result
        finally:
            if request_directory is not None:
                keep = bool(
                    self.retain_failed_requests
                    and result is not None
                    and result.status != "OK"
                )
                if not keep:
                    self._safe_cleanup(request_directory)

    def read_pilot_state(
        self,
        run_id: str,
        timeout: float = 10.0,
        poll_interval: float = 0.05,
    ) -> dict:
        snapshot = self.read_state(
            timeout=timeout,
            poll_interval=poll_interval,
            run_id=run_id,
        )
        return {
            "status": snapshot.status,
            "request_id": snapshot.request_id,
            "run_id": snapshot.run_id,
            "captured_at": snapshot.captured_at,
            "reader_version": snapshot.reader_version,
            "schema_version": snapshot.schema_version,
            "capabilities": snapshot.capabilities.to_dict(),
            "state": snapshot.to_pilot_state(),
            "errors": list(snapshot.errors),
        }

    def _safe_cleanup(self, request_directory: Path, force: bool = False) -> None:
        """Delete only a request directory registered to this observer."""
        directory = Path(request_directory)
        with self._registry_lock:
            record = next(
                (
                    item
                    for item in self._request_registry.values()
                    if item["directory"] == directory
                ),
                None,
            )

            if record is None:
                if not force:
                    return
                root = self.ipc_dir.resolve()
                resolved = directory.resolve()
                if root not in resolved.parents:
                    return
                shutil.rmtree(resolved, ignore_errors=True)
                return

            root = self.ipc_dir.resolve()
            resolved = directory.resolve()
            expected = root / record["run_key"] / record["request_id"]
            if resolved != expected.resolve():
                return

            try:
                shutil.rmtree(resolved)
            finally:
                record["status"] = "CLEANED"


__all__ = ["AfterEffectsReadOnlyObserver"]
