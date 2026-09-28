"""Canonical fixture certification, integrity, and fresh-run copy management."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
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



def _parse_major_version(value: Any) -> Optional[int]:
    if not isinstance(value, str) or not value.strip():
        return None
    match = re.match(r"^\s*(\d+)", value)
    return int(match.group(1)) if match else None


def _normalize_locale(value: Any) -> Optional[str]:
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip().replace("_", "-").lower()


def _application_build_identity(
    version: Any,
    build_name: Any,
    build_number: Any,
) -> Optional[str]:
    if not isinstance(version, str) or not version.strip():
        return None
    if not isinstance(build_name, str) or not build_name.strip():
        return None
    if (
        isinstance(build_number, bool)
        or not isinstance(build_number, (int, float))
        or not math.isfinite(float(build_number))
    ):
        return None
    number = (
        int(build_number)
        if float(build_number).is_integer()
        else float(build_number)
    )
    return f"{version.strip()}|{build_name.strip()}|{number}"


class FixtureRepository:
    def __init__(
        self,
        contract: PilotContract,
        *,
        repo_root: Optional[str | Path] = None,
        canonical_dir: Optional[str | Path] = None,
        certification_dir: Optional[str | Path] = None,
        run_dir: Optional[str | Path] = None,
        run_registry_dir: Optional[str | Path] = None,
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
        self.run_registry_dir = Path(
            run_registry_dir or (root / "fixtures" / "run_registry")
        )

    def ensure_layout(self) -> None:
        self.canonical_dir.mkdir(parents=True, exist_ok=True)
        self.certification_dir.mkdir(parents=True, exist_ok=True)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.run_registry_dir.mkdir(parents=True, exist_ok=True)

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
        expected_canonical_path = self.canonical_path(fixture_id).resolve()
        if fixture_path != expected_canonical_path:
            raise FixtureCertificationError(
                "fixture certification is allowed only for the canonical fixture path"
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

        application = evidence.get("application")
        if not isinstance(application, dict):
            raise FixtureCertificationError(
                "AE Reader certification evidence is missing application metadata"
            )

        ae_contract = self.contract.environment_contract.get("after_effects") or {}
        required_major = ae_contract.get("required_major_version")
        observed_reader_version = application.get("version")
        observed_reader_major = _parse_major_version(observed_reader_version)
        if (
            not isinstance(required_major, int)
            or isinstance(required_major, bool)
            or observed_reader_major != required_major
        ):
            raise FixtureCertificationError(
                "fixture was not read by the required After Effects major version"
            )

        required_language = ae_contract.get("required_language")
        observed_reader_language = application.get("language")
        if (
            not isinstance(required_language, str)
            or _normalize_locale(observed_reader_language)
            != _normalize_locale(required_language)
        ):
            raise FixtureCertificationError(
                "fixture was not read with the required After Effects language"
            )

        if not isinstance(builder_result, dict) or not builder_result:
            raise FixtureCertificationError(
                "canonical fixture certification requires trusted builder metadata"
            )
        if builder_result.get("status") != "SAVED":
            raise FixtureCertificationError(
                "fixture builder did not report SAVED"
            )
        if builder_result.get("fixture_id") != fixture_id:
            raise FixtureCertificationError(
                "fixture builder metadata belongs to a different fixture"
            )
        builder_output = builder_result.get("output_path")
        if (
            not isinstance(builder_output, str)
            or not builder_output
            or not _same_path(builder_output, fixture_path)
        ):
            raise FixtureCertificationError(
                "fixture builder metadata belongs to a different output file"
            )

        builder_version = builder_result.get("ae_version")
        builder_major = _parse_major_version(builder_version)
        if builder_major != required_major:
            raise FixtureCertificationError(
                "fixture was not built by the required After Effects major version"
            )
        if builder_version != observed_reader_version:
            raise FixtureCertificationError(
                "After Effects version changed between fixture build and certification read"
            )

        builder_language = builder_result.get("ae_language")
        if _normalize_locale(builder_language) != _normalize_locale(required_language):
            raise FixtureCertificationError(
                "fixture builder language does not match the required language"
            )
        if _normalize_locale(builder_language) != _normalize_locale(observed_reader_language):
            raise FixtureCertificationError(
                "After Effects language changed between fixture build and certification read"
            )

        reader_build_name = application.get("build_name")
        reader_build_number = application.get("build_number")
        builder_build_name = builder_result.get("ae_build_name")
        builder_build_number = builder_result.get("ae_build_number")

        if not isinstance(reader_build_name, str) or not reader_build_name.strip():
            raise FixtureCertificationError(
                "AE Reader certification evidence is missing build_name"
            )
        if (
            isinstance(reader_build_number, bool)
            or not isinstance(reader_build_number, (int, float))
            or not math.isfinite(float(reader_build_number))
        ):
            raise FixtureCertificationError(
                "AE Reader certification evidence is missing a valid build_number"
            )
        if not isinstance(builder_build_name, str) or not builder_build_name.strip():
            raise FixtureCertificationError(
                "fixture builder metadata is missing ae_build_name"
            )
        if (
            isinstance(builder_build_number, bool)
            or not isinstance(builder_build_number, (int, float))
            or not math.isfinite(float(builder_build_number))
        ):
            raise FixtureCertificationError(
                "fixture builder metadata is missing a valid ae_build_number"
            )
        if builder_build_name != reader_build_name:
            raise FixtureCertificationError(
                "After Effects build name changed between fixture build and certification read"
            )
        if float(builder_build_number) != float(reader_build_number):
            raise FixtureCertificationError(
                "After Effects build number changed between fixture build and certification read"
            )

        saved_at = builder_result.get("saved_at")
        if (
            isinstance(saved_at, bool)
            or not isinstance(saved_at, (int, float))
            or not math.isfinite(float(saved_at))
            or float(saved_at) <= 0
        ):
            raise FixtureCertificationError(
                "fixture builder metadata is missing a valid saved_at timestamp"
            )

        file_hash = sha256_file(fixture_path)
        size = fixture_path.stat().st_size

        canonical_relpath = str(
            fixture_path.relative_to(self.repo_root.resolve())
        )

        ae_build_identity = _application_build_identity(
            observed_reader_version,
            reader_build_name,
            reader_build_number,
        )
        if ae_build_identity is None:
            raise FixtureCertificationError(
                "unable to derive certified After Effects build identity"
            )

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
            "ae_build_identity": ae_build_identity,
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
        if record.get("fixture_id") != fixture_id:
            raise FixtureCertificationError(
                "certification record belongs to a different fixture"
            )
        record_hash = record.get("sha256")
        if (
            not isinstance(record_hash, str)
            or re.fullmatch(r"[0-9a-f]{64}", record_hash) is None
        ):
            raise FixtureCertificationError(
                "certification record contains an invalid SHA-256"
            )
        record_size = record.get("size_bytes")
        if (
            not isinstance(record_size, int)
            or isinstance(record_size, bool)
            or record_size <= 0
        ):
            raise FixtureCertificationError(
                "certification record contains an invalid file size"
            )
        if record.get("reader_version") != self.contract.expected_reader_version():
            raise FixtureCertificationError(
                "certification record Reader version no longer matches the pilot contract"
            )
        if (
            record.get("reader_schema_version")
            != self.contract.expected_reader_schema_version()
        ):
            raise FixtureCertificationError(
                "certification record Reader schema no longer matches the pilot contract"
            )

        application = record.get("application")
        builder_result = record.get("builder_result")
        if not isinstance(application, dict) or not isinstance(builder_result, dict):
            raise FixtureCertificationError(
                "certification record is missing AE application/build metadata"
            )
        recorded_build_identity = _application_build_identity(
            application.get("version"),
            application.get("build_name"),
            application.get("build_number"),
        )
        builder_build_identity = _application_build_identity(
            builder_result.get("ae_version"),
            builder_result.get("ae_build_name"),
            builder_result.get("ae_build_number"),
        )
        if (
            recorded_build_identity is None
            or builder_build_identity is None
            or recorded_build_identity != builder_build_identity
            or record.get("ae_build_identity") != recorded_build_identity
        ):
            raise FixtureCertificationError(
                "certification record AE build identity is inconsistent"
            )

        path = self.canonical_path(fixture_id).resolve()
        if not path.is_file():
            raise FixtureCertificationError(
                f"certified fixture file is missing: {path}"
            )

        record_relpath = record.get("canonical_relpath")
        if not isinstance(record_relpath, str) or not record_relpath:
            raise FixtureCertificationError(
                "certification record is missing canonical_relpath"
            )
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
        registry_path = self.run_registry_dir / f"{run_key}.json"

        if destination_dir.exists() or registry_path.exists():
            raise FixtureCertificationError(
                "run_id was already used; pilot run identity reuse is forbidden"
            )

        self.ensure_layout()
        try:
            handle = os.open(
                registry_path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            )
            with os.fdopen(handle, "w", encoding="utf-8") as registry_file:
                json.dump(
                    {
                        "status": "RESERVED",
                        "run_id": run_id,
                        "run_key": run_key,
                        "fixture_id": fixture_id,
                        "reserved_at": time.time(),
                    },
                    registry_file,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
        except FileExistsError as exc:
            raise FixtureCertificationError(
                "run_id was already used; pilot run identity reuse is forbidden"
            ) from exc

        temporary = destination.with_suffix(".tmp")

        try:
            destination_dir.mkdir(parents=True, exist_ok=False)
            shutil.copy2(source, temporary)
            copied_hash = sha256_file(temporary)
            if copied_hash != record["sha256"]:
                raise FixtureCertificationError(
                    "fresh fixture copy hash differs from certified canonical fixture"
                )
            os.replace(temporary, destination)
        except Exception:
            shutil.rmtree(destination_dir, ignore_errors=True)
            try:
                registry_path.unlink()
            except FileNotFoundError:
                pass
            raise

        copy_hash = sha256_file(destination)
        created_at = time.time()
        ready_record = {
            "status": "READY",
            "run_id": run_id,
            "run_key": run_key,
            "fixture_id": fixture_id,
            "canonical_sha256": record["sha256"],
            "copy_sha256": copy_hash,
            "certified_ae_build_identity": record["ae_build_identity"],
            "copy_path": str(destination.resolve()),
            "created_at": created_at,
            "disposable": True,
        }
        registry_tmp = registry_path.with_suffix(".tmp")
        try:
            registry_tmp.write_text(
                json.dumps(
                    ready_record,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            os.replace(registry_tmp, registry_path)
        except Exception:
            shutil.rmtree(destination_dir, ignore_errors=True)
            try:
                registry_tmp.unlink()
            except FileNotFoundError:
                pass
            try:
                registry_path.unlink()
            except FileNotFoundError:
                pass
            raise

        result = dict(ready_record)
        # Keep the public Step 03 API stable for callers that consume "path".
        result["path"] = result["copy_path"]
        return result

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
