"""Canonical fixture certification, integrity, and fresh-run copy management."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from pathlib import Path
from typing import Any, Dict, Optional

from verifier.contract import PilotContract
from verifier.engine import compare_fixture_state, validate_evidence


class FixtureCertificationError(RuntimeError):
    pass


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _same_path(left: str | Path, right: str | Path) -> bool:
    a = os.path.normcase(os.path.abspath(str(left)))
    b = os.path.normcase(os.path.abspath(str(right)))
    return a == b


class FixtureRepository:
    def __init__(
        self,
        contract: PilotContract,
        *,
        repo_root: Optional[str | Path] = None,
        canonical_dir: Optional[str | Path] = None,
        certification_dir: Optional[str | Path] = None,
        run_dir: Optional[str | Path] = None,
    ) -> None:
        root = Path(repo_root or Path(__file__).resolve().parents[1])
        self.contract = contract
        self.repo_root = root
        self.contract_path = root / "pilot_10_skills.yaml"
        self.canonical_dir = Path(
            canonical_dir or (root / "fixtures" / "canonical")
        )
        self.certification_dir = Path(
            certification_dir or (root / "fixtures" / "certifications")
        )
        self.run_dir = Path(
            run_dir or (root / "fixtures" / "runs")
        )

    def ensure_layout(self) -> None:
        self.canonical_dir.mkdir(parents=True, exist_ok=True)
        self.certification_dir.mkdir(parents=True, exist_ok=True)
        self.run_dir.mkdir(parents=True, exist_ok=True)

    def canonical_path(self, fixture_id: str) -> Path:
        if fixture_id not in self.contract.fixtures:
            raise FixtureCertificationError(f"unknown fixture id: {fixture_id}")
        return self.canonical_dir / f"{fixture_id}.aep"

    def certification_path(self, fixture_id: str) -> Path:
        if fixture_id not in self.contract.fixtures:
            raise FixtureCertificationError(f"unknown fixture id: {fixture_id}")
        return self.certification_dir / f"{fixture_id}.json"

    def _contract_sha256(self) -> str:
        try:
            data = self.contract_path.read_bytes()
        except OSError as exc:
            raise FixtureCertificationError(
                f"unable to hash pilot contract: {exc}"
            ) from exc
        return sha256_bytes(data)

    def _required_state_sha256(self, fixture_id: str) -> str:
        required_state = self.contract.fixtures[fixture_id].get("required_state")
        encoded = json.dumps(
            required_state,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        return sha256_bytes(encoded)

    def certify(
        self,
        fixture_id: str,
        *,
        aep_path: str | Path,
        evidence: Dict[str, Any],
        expected_run_id: str,
        expected_request_id: str,
        min_captured_at: float,
        builder_result: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        self.ensure_layout()
        if fixture_id not in self.contract.fixtures:
            raise FixtureCertificationError(f"unknown fixture id: {fixture_id}")

        fixture_path = Path(aep_path).resolve()
        if not fixture_path.is_file():
            raise FixtureCertificationError(
                f"fixture file does not exist: {fixture_path}"
            )

        evidence_check = validate_evidence(
            evidence,
            expected_run_id=expected_run_id,
            expected_request_id=expected_request_id,
            expected_reader_version=self.contract.expected_reader_version(),
            expected_schema_version=self.contract.expected_reader_schema_version(),
            min_captured_at=min_captured_at,
        )
        if not evidence_check.valid:
            raise FixtureCertificationError(
                f"AE Reader evidence is not certifiable: "
                f"{evidence_check.error_code}: {evidence_check.reason}"
            )

        supported = set(evidence_check.details.get("supported_capabilities") or [])
        if "project.file_identity" not in supported:
            raise FixtureCertificationError(
                "AE Reader cannot certify fixture identity: project.file_identity capability is missing"
            )

        state = evidence_check.state or {}
        project = state.get("project")
        if not isinstance(project, dict):
            raise FixtureCertificationError(
                "AE Reader state is missing project identity"
            )
        observed_file_path = project.get("file_path")
        if not isinstance(observed_file_path, str) or not observed_file_path:
            raise FixtureCertificationError(
                "AE Reader did not bind evidence to a saved project file"
            )
        if not _same_path(observed_file_path, fixture_path):
            raise FixtureCertificationError(
                "AE Reader evidence belongs to a different project file"
            )

        required_state = self.contract.fixtures[fixture_id].get("required_state")
        if not isinstance(required_state, dict):
            raise FixtureCertificationError(
                f"{fixture_id} required_state is invalid"
            )

        mismatches = compare_fixture_state(
            required_state,
            state,
            comparison_policy=self.contract.comparison_policy,
        )
        if mismatches:
            raise FixtureCertificationError(
                "fixture state does not match canonical specification: "
                + json.dumps(mismatches, ensure_ascii=False)
            )

        file_hash = sha256_file(fixture_path)
        size = fixture_path.stat().st_size
        application = evidence.get("application") or {}
        if not isinstance(application, dict):
            application = {}

        try:
            canonical_relpath = str(fixture_path.relative_to(self.repo_root.resolve()))
        except ValueError:
            canonical_relpath = None

        record = {
            "status": "CERTIFIED",
            "fixture_id": fixture_id,
            "canonical_relpath": canonical_relpath,
            "certified_project_file_path": str(fixture_path),
            "sha256": file_hash,
            "size_bytes": size,
            "contract_sha256": self._contract_sha256(),
            "required_state_sha256": self._required_state_sha256(fixture_id),
            "reader_version": evidence.get("reader_version"),
            "reader_schema_version": evidence.get("schema_version"),
            "reader_request_id": expected_request_id,
            "certification_run_id": expected_run_id,
            "captured_at": evidence.get("captured_at"),
            "certified_at": time.time(),
            "application": application,
            "builder_result": dict(builder_result or {}),
        }

        target = self.certification_path(fixture_id)
        temporary = target.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        os.replace(temporary, target)
        return record

    def load_certification(self, fixture_id: str) -> Dict[str, Any]:
        path = self.certification_path(fixture_id)
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise FixtureCertificationError(
                f"fixture is not certified: {fixture_id}"
            ) from exc
        except (OSError, ValueError, UnicodeError) as exc:
            raise FixtureCertificationError(
                f"invalid fixture certification record: {exc}"
            ) from exc
        if not isinstance(value, dict):
            raise FixtureCertificationError(
                "fixture certification record must be an object"
            )
        return value

    def verify_canonical(self, fixture_id: str) -> Dict[str, Any]:
        record = self.load_certification(fixture_id)
        if record.get("status") != "CERTIFIED":
            raise FixtureCertificationError(
                f"fixture is not certified: {fixture_id}"
            )

        path = self.canonical_path(fixture_id).resolve()
        if not path.is_file():
            raise FixtureCertificationError(
                f"certified fixture file is missing: {path}"
            )

        record_relpath = record.get("canonical_relpath")
        if record_relpath is not None:
            if not isinstance(record_relpath, str):
                raise FixtureCertificationError("invalid canonical_relpath in certification")
            expected_relative = str(path.relative_to(self.repo_root.resolve()))
            if record_relpath != expected_relative:
                raise FixtureCertificationError(
                    "certification relative path does not match canonical fixture path"
                )

        actual_hash = sha256_file(path)
        if actual_hash != record.get("sha256"):
            raise FixtureCertificationError(
                f"canonical fixture hash changed after certification: {fixture_id}"
            )

        if path.stat().st_size != record.get("size_bytes"):
            raise FixtureCertificationError(
                f"canonical fixture size changed after certification: {fixture_id}"
            )

        if record.get("contract_sha256") != self._contract_sha256():
            raise FixtureCertificationError(
                f"pilot contract changed after {fixture_id} was certified"
            )

        if (
            record.get("required_state_sha256")
            != self._required_state_sha256(fixture_id)
        ):
            raise FixtureCertificationError(
                f"fixture specification changed after {fixture_id} was certified"
            )

        return record

    def create_run_copy(
        self,
        fixture_id: str,
        run_id: str,
    ) -> Dict[str, Any]:
        if not isinstance(run_id, str) or not run_id:
            raise FixtureCertificationError("run_id must be a non-empty string")

        record = self.verify_canonical(fixture_id)
        source = self.canonical_path(fixture_id).resolve()

        run_key = hashlib.sha256(run_id.encode("utf-8")).hexdigest()
        destination_dir = self.run_dir / run_key
        destination = destination_dir / f"{fixture_id}.aep"

        if destination_dir.exists():
            raise FixtureCertificationError(
                "run workspace already exists; run_id reuse is forbidden"
            )

        destination_dir.mkdir(parents=True, exist_ok=False)
        temporary = destination.with_suffix(".tmp")

        try:
            shutil.copy2(source, temporary)
            copied_hash = sha256_file(temporary)
            if copied_hash != record["sha256"]:
                raise FixtureCertificationError(
                    "fresh fixture copy hash differs from certified canonical fixture"
                )
            os.replace(temporary, destination)
        except Exception:
            shutil.rmtree(destination_dir, ignore_errors=True)
            raise

        return {
            "fixture_id": fixture_id,
            "run_id": run_id,
            "run_key": run_key,
            "canonical_sha256": record["sha256"],
            "copy_sha256": sha256_file(destination),
            "path": str(destination.resolve()),
            "created_at": time.time(),
            "disposable": True,
        }

    def remove_run_copy(self, run_id: str) -> None:
        if not isinstance(run_id, str) or not run_id:
            raise FixtureCertificationError("run_id must be a non-empty string")
        run_key = hashlib.sha256(run_id.encode("utf-8")).hexdigest()
        target = self.run_dir / run_key
        if target.exists():
            shutil.rmtree(target)

    def status(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        for fixture_id in self.contract.fixtures:
            try:
                record = self.verify_canonical(fixture_id)
            except FixtureCertificationError as exc:
                result[fixture_id] = {
                    "status": "NOT_CERTIFIED",
                    "reason": str(exc),
                }
            else:
                result[fixture_id] = {
                    "status": "CERTIFIED",
                    "sha256": record["sha256"],
                    "size_bytes": record["size_bytes"],
                    "certified_at": record["certified_at"],
                }
        return result
