"""Isolated local-file After Effects reader; it never mutates an AE project."""

from __future__ import annotations

import json
import hashlib
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from .schema import AEReadRequest, AEStateSnapshot, invalid_state


class AfterEffectsReadOnlyObserver:
    """Request a read-only JSX snapshot through a private temporary directory."""

    def __init__(self, afterfx_path: Optional[str] = None, ipc_dir: Optional[str] = None, script_path: Optional[str] = None):
        self.afterfx_path = afterfx_path
        self.ipc_dir = Path(ipc_dir or (Path(tempfile.gettempdir()) / "ufo_ae_reader"))
        self.script_path = Path(script_path or (Path(__file__).resolve().parent / "scripts" / "read_state.jsx"))
        self._registry_lock = threading.Lock()
        self._request_registry = {}

    def _session_key(self, session_id: str) -> str:
        """Return an opaque, path-safe key without exposing session_id."""
        return hashlib.sha256(str(session_id).encode("utf-8")).hexdigest()

    @staticmethod
    def _validate_request_id(request_id: str) -> str:
        value = str(request_id)
        if not re.fullmatch(r"[A-Za-z0-9._-]+", value):
            raise ValueError("request_id is not a safe path component")
        return value

    def _request_directory(self, request: AEReadRequest) -> Path:
        """Return the request-specific directory without creating it."""
        request_id = self._validate_request_id(request.request_id)
        return self.ipc_dir / self._session_key(request.session_id) / request_id

    def _register_request(self, request: AEReadRequest, directory: Path) -> None:
        request_id = self._validate_request_id(request.request_id)
        with self._registry_lock:
            if request_id in self._request_registry:
                raise RuntimeError(f"request_id already exists: {request_id}")
            self._request_registry[request_id] = {
                "status": "ACTIVE",
                "directory": directory,
                "session_key": self._session_key(request.session_id),
                "request_id": request_id,
            }

    def _set_request_status(self, request_id: str, status: str) -> None:
        with self._registry_lock:
            record = self._request_registry.get(request_id)
            if record is not None:
                record["status"] = status

    def _prepare_request_directory(self, request: AEReadRequest) -> Path:
        if not self.script_path.is_file():
            raise FileNotFoundError(f"{self.script_path} was not found")

        session_directory = self.ipc_dir / self._session_key(request.session_id)
        request_directory = session_directory / self._validate_request_id(request.request_id)
        session_directory.mkdir(parents=True, exist_ok=True)
        request_directory.mkdir(exist_ok=False)
        try:
            self._register_request(request, request_directory)
            shutil.copyfile(self.script_path, request_directory / "read_state.jsx")
            temporary = request_directory / "request.tmp"
            temporary.write_text(
                json.dumps(request.to_dict(), ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8",
            )
            os.replace(temporary, request_directory / "request.json")
            return request_directory
        except Exception:
            self._safe_cleanup(request_directory)
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
        candidates = sorted(root.glob("Adobe After Effects */Support Files/AfterFX.exe"), key=lambda p: str(p).lower())
        return candidates[-1] if candidates else None

    def _write_request(self, request: AEReadRequest) -> Path:
        """Create and populate one isolated request directory."""
        return self._prepare_request_directory(request)

    @staticmethod
    def _invalid(request: AEReadRequest, status: str, error: str) -> AEStateSnapshot:
        return invalid_state(request, status, error)

    def _read_response(self, request: AEReadRequest, request_directory: Optional[Path] = None) -> AEStateSnapshot:
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
        if response.session_id != request.session_id or response.lesson_id != request.lesson_id or response.step_id != request.step_id:
            return self._invalid(request, "STALE_RESPONSE", "request identity mismatch")
        if response.captured_at is None or response.captured_at < request.requested_at:
            return self._invalid(request, "STALE_RESPONSE", "response predates request")
        if response.status != "OK":
            return response
        return response

    def read_state(self, session_id: str, lesson_id: str, step_id: str, timeout: float = 10.0, poll_interval: float = 0.05) -> AEStateSnapshot:
        request = AEReadRequest(str(uuid.uuid4()), str(session_id), str(lesson_id), str(step_id), time.time())
        request_directory = None
        try:
            request_directory = self._write_request(request)
            executable = self._locate_afterfx()
            if executable is None:
                self._set_request_status(request.request_id, "INVALID")
                return self._invalid(request, "AE_NOT_AVAILABLE", "AfterFX.exe was not found")
            script = request_directory / "read_state.jsx"
            try:
                subprocess.Popen([str(executable), "-r", str(script)], close_fds=True)
            except (OSError, ValueError) as exc:
                self._set_request_status(request.request_id, "INVALID")
                return self._invalid(request, "AE_NOT_AVAILABLE", f"AfterFX launch failed: {exc}")
            deadline = time.monotonic() + max(0.0, float(timeout))
            response_path = request_directory / "response.json"
            while time.monotonic() <= deadline:
                if response_path.is_file():
                    result = self._read_response(request, request_directory)
                    self._set_request_status(request.request_id, "COMPLETE" if result.status == "OK" else "INVALID")
                    return result
                time.sleep(max(0.01, poll_interval))
            self._set_request_status(request.request_id, "TIMEOUT")
            return self._invalid(request, "TIMEOUT", "matching response did not arrive before timeout")
        finally:
            if request_directory is not None:
                self._safe_cleanup(request_directory)

    def _safe_cleanup(self, request_directory: Path) -> None:
        """Delete only a registered request directory owned by this reader."""
        directory = Path(request_directory)
        with self._registry_lock:
            record = next(
                (item for item in self._request_registry.values() if item["directory"] == directory),
                None,
            )
            if record is None:
                return
            root = self.ipc_dir.resolve()
            resolved = directory.resolve()
            expected = root / record["session_key"] / record["request_id"]
            if resolved != expected.resolve():
                return
            try:
                shutil.rmtree(resolved)
            finally:
                record["status"] = record.get("status", "INVALID")


__all__ = ["AfterEffectsReadOnlyObserver"]
