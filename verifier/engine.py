"""Fail-closed verification engine for the AE 10-skill pilot."""

from __future__ import annotations

import copy
import math
import ntpath
from numbers import Real
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .assertions import evaluate_assertions
from .contract import PilotContract
from .model import (
    EvidenceValidation,
    PreflightDecision,
    RunDecision,
    SkillDecision,
)


def _same_windows_path(left: str, right: str) -> bool:
    return ntpath.normcase(ntpath.normpath(left)) == ntpath.normcase(
        ntpath.normpath(right)
    )


def _is_number(value: Any) -> bool:
    return (
        isinstance(value, Real)
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _normalize_locale(value: Any) -> Optional[str]:
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip().replace("_", "-").lower()


def _parse_major_version(value: Any) -> Optional[int]:
    if not isinstance(value, str) or not value.strip():
        return None
    prefix = value.strip().split(".", 1)[0]
    return int(prefix) if prefix.isdigit() else None


def _application_build_identity(application: Dict[str, Any]) -> Optional[str]:
    version = application.get("version")
    build_name = application.get("build_name")
    build_number = application.get("build_number")
    if not isinstance(version, str) or not version.strip():
        return None
    if not isinstance(build_name, str) or not build_name.strip():
        return None
    if not _is_number(build_number):
        return None
    number = int(build_number) if float(build_number).is_integer() else float(build_number)
    return f"{version.strip()}|{build_name.strip()}|{number}"


def _fixture_tolerance(path: str, policy: Dict[str, Any]) -> float:
    lowered = path.lower()
    if any(token in lowered for token in ("x_percent", "y_percent", "opacity_percent")):
        return float(policy.get("percent_absolute_tolerance", 0.001))
    if any(token in lowered for token in (".width", ".height", ".position.")):
        return float(policy.get("pixel_absolute_tolerance", 0.01))
    if any(token in lowered for token in ("duration_seconds", "in_seconds", "out_seconds", "start_seconds", "current_time_seconds")):
        return float(policy.get("duration_seconds_absolute_tolerance", 0.001))
    if "frame_rate" in lowered:
        return float(policy.get("frame_rate_absolute_tolerance", 0.001))
    return float(policy.get("default_numeric_absolute_tolerance", 0.001))


def compare_fixture_state(
    expected: Any,
    actual: Any,
    *,
    comparison_policy: Optional[Dict[str, Any]] = None,
    path: str = "$",
) -> List[Dict[str, Any]]:
    """Return deterministic mismatch records for a canonical fixture partial-state."""
    policy = comparison_policy or {}
    mismatches: List[Dict[str, Any]] = []

    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return [{
                "path": path,
                "expected": expected,
                "actual": actual,
                "reason": "expected object",
            }]
        for key, expected_value in expected.items():
            child_path = f"{path}.{key}"
            if key not in actual:
                mismatches.append({
                    "path": child_path,
                    "expected": expected_value,
                    "actual": None,
                    "reason": "missing field",
                })
                continue
            mismatches.extend(
                compare_fixture_state(
                    expected_value,
                    actual[key],
                    comparison_policy=policy,
                    path=child_path,
                )
            )
        return mismatches

    if isinstance(expected, list):
        if not isinstance(actual, list):
            return [{
                "path": path,
                "expected": expected,
                "actual": actual,
                "reason": "expected list",
            }]
        if len(expected) != len(actual):
            mismatches.append({
                "path": path,
                "expected": f"list length {len(expected)}",
                "actual": f"list length {len(actual)}",
                "reason": "list length mismatch",
            })
            return mismatches
        for index, expected_value in enumerate(expected):
            mismatches.extend(
                compare_fixture_state(
                    expected_value,
                    actual[index],
                    comparison_policy=policy,
                    path=f"{path}[{index}]",
                )
            )
        return mismatches

    if expected is None:
        if actual is not None:
            mismatches.append({
                "path": path,
                "expected": None,
                "actual": actual,
                "reason": "expected null",
            })
        return mismatches

    if isinstance(expected, bool) or isinstance(actual, bool):
        if not (
            isinstance(expected, bool)
            and isinstance(actual, bool)
            and expected is actual
        ):
            mismatches.append({
                "path": path,
                "expected": expected,
                "actual": actual,
                "reason": "strict boolean/type mismatch",
            })
        return mismatches

    if _is_number(expected) and _is_number(actual):
        tolerance = _fixture_tolerance(path, policy)
        if abs(float(actual) - float(expected)) > tolerance:
            mismatches.append({
                "path": path,
                "expected": expected,
                "actual": actual,
                "reason": f"numeric mismatch tolerance={tolerance}",
            })
        return mismatches

    if actual != expected:
        mismatches.append({
            "path": path,
            "expected": expected,
            "actual": actual,
            "reason": "exact mismatch",
        })
    return mismatches


def _fixture_state_capabilities(required_state: Dict[str, Any]) -> set[str]:
    """Infer Reader capabilities needed to prove a canonical fixture state."""
    capabilities: set[str] = set()

    project = required_state.get("project")
    if isinstance(project, dict):
        if "composition_count" in project:
            capabilities.add("project.composition_count")
        if "file_path" in project:
            capabilities.add("project.file_identity")

    if "active_comp" in required_state:
        capabilities.add("composition.identity")
        active_comp = required_state.get("active_comp")
        if isinstance(active_comp, dict):
            if "width" in active_comp or "height" in active_comp:
                capabilities.add("composition.dimensions")
            if "duration_seconds" in active_comp:
                capabilities.add("composition.duration")
            if "frame_rate" in active_comp:
                capabilities.add("composition.frame_rate")
            if (
                "current_time_seconds" in active_comp
                or "current_time_frame" in active_comp
            ):
                capabilities.add("composition.current_time")

    if "layers" in required_state:
        capabilities.add("layer.list")
        layers = required_state.get("layers")
        if isinstance(layers, list):
            for layer in layers:
                if not isinstance(layer, dict):
                    continue
                if "name" in layer:
                    capabilities.add("layer.identity")
                if "type" in layer:
                    capabilities.add("layer.type")
                if "source_text" in layer:
                    capabilities.add("layer.source_text")
                if "index" in layer:
                    capabilities.add("layer.index")
                if any(
                    key in layer
                    for key in ("in_seconds", "out_seconds", "start_seconds")
                ):
                    capabilities.add("layer.timing")

                transform = layer.get("transform")
                if isinstance(transform, dict):
                    if "position" in transform:
                        capabilities.add("layer.transform.position")
                    if "scale" in transform:
                        capabilities.add("layer.transform.scale")
                    if "opacity_percent" in transform:
                        capabilities.add("layer.transform.opacity")

                properties = layer.get("properties")
                if isinstance(properties, dict):
                    opacity = properties.get("opacity")
                    if isinstance(opacity, dict):
                        if "keyframe_count" in opacity:
                            capabilities.add("property.keyframes.count")
                        if "keyframes" in opacity:
                            capabilities.add("property.keyframes.time")
                            capabilities.add("property.keyframes.value")

                if "effects" in layer:
                    capabilities.add("effect.list")
                    effects = layer.get("effects")
                    if isinstance(effects, list) and effects:
                        capabilities.add("effect.identity.stable_id")
                        capabilities.add("effect.property.identity")
                        capabilities.add("effect.property.value")

    return capabilities


def validate_evidence(
    evidence: Any,
    *,
    expected_run_id: str,
    expected_request_id: Optional[str],
    expected_reader_version: Optional[str],
    expected_schema_version: Optional[int],
    min_captured_at: Optional[float] = None,
) -> EvidenceValidation:
    if not isinstance(evidence, dict):
        return EvidenceValidation(False, "MALFORMED_EVIDENCE", "reader evidence must be an object")

    required = (
        "status",
        "request_id",
        "run_id",
        "captured_at",
        "reader_version",
        "schema_version",
        "capabilities",
        "application",
        "state",
        "errors",
    )
    missing = [key for key in required if key not in evidence]
    if missing:
        return EvidenceValidation(
            False,
            "MALFORMED_EVIDENCE",
            "reader evidence missing fields",
            details={"missing": missing},
        )

    if evidence.get("run_id") != expected_run_id:
        return EvidenceValidation(
            False,
            "STALE_EVIDENCE",
            "reader run_id does not match active run",
            details={"expected": expected_run_id, "actual": evidence.get("run_id")},
        )

    request_id = evidence.get("request_id")
    if not isinstance(request_id, str) or not request_id:
        return EvidenceValidation(False, "MALFORMED_EVIDENCE", "reader request_id is missing or invalid")
    if expected_request_id is not None and request_id != expected_request_id:
        return EvidenceValidation(
            False,
            "STALE_EVIDENCE",
            "reader request_id does not match expected request",
            details={"expected": expected_request_id, "actual": request_id},
        )

    captured_at = evidence.get("captured_at")
    if not _is_number(captured_at):
        return EvidenceValidation(False, "MALFORMED_EVIDENCE", "reader captured_at is missing or invalid")
    if min_captured_at is not None and not _is_number(min_captured_at):
        return EvidenceValidation(
            False,
            "MALFORMED_EVIDENCE",
            "freshness boundary is missing or invalid",
        )
    if min_captured_at is not None and float(captured_at) <= float(min_captured_at):
        return EvidenceValidation(
            False,
            "STALE_EVIDENCE",
            "reader evidence is not newer than the required boundary",
            details={"captured_at": captured_at, "required_newer_than": min_captured_at},
        )

    if expected_reader_version is not None and evidence.get("reader_version") != expected_reader_version:
        return EvidenceValidation(
            False,
            "READER_VERSION_MISMATCH",
            "unexpected AE Reader version",
            details={
                "expected": expected_reader_version,
                "actual": evidence.get("reader_version"),
            },
        )

    if expected_schema_version is not None and evidence.get("schema_version") != expected_schema_version:
        return EvidenceValidation(
            False,
            "READER_SCHEMA_MISMATCH",
            "unexpected AE Reader schema version",
            details={
                "expected": expected_schema_version,
                "actual": evidence.get("schema_version"),
            },
        )

    errors = evidence.get("errors")
    if not isinstance(errors, list):
        return EvidenceValidation(False, "MALFORMED_EVIDENCE", "reader errors must be a list")
    if not all(isinstance(item, str) for item in errors):
        return EvidenceValidation(
            False,
            "MALFORMED_EVIDENCE",
            "reader errors must contain strings only",
        )

    capabilities = evidence.get("capabilities")
    if not isinstance(capabilities, dict):
        return EvidenceValidation(False, "MALFORMED_EVIDENCE", "capability manifest is missing")
    supported = capabilities.get("supported_capabilities")
    if not isinstance(supported, list) or not all(isinstance(item, str) for item in supported):
        return EvidenceValidation(False, "MALFORMED_EVIDENCE", "invalid supported_capabilities")
    if len(set(supported)) != len(supported):
        return EvidenceValidation(False, "MALFORMED_EVIDENCE", "duplicate supported_capabilities")

    if expected_reader_version is not None and capabilities.get("reader_version") != expected_reader_version:
        return EvidenceValidation(False, "READER_VERSION_MISMATCH", "capability manifest reader version mismatch")
    if expected_schema_version is not None and capabilities.get("schema_version") != expected_schema_version:
        return EvidenceValidation(False, "READER_SCHEMA_MISMATCH", "capability manifest schema mismatch")

    status = evidence.get("status")
    if not isinstance(status, str):
        return EvidenceValidation(False, "MALFORMED_EVIDENCE", "reader status must be a string")
    if status != "OK":
        return EvidenceValidation(
            False,
            "READER_NOT_OK",
            f"AE Reader returned {status}",
            details={"errors": list(evidence.get("errors") or [])},
        )
    if errors:
        return EvidenceValidation(
            False,
            "CONTRADICTORY_EVIDENCE",
            "AE Reader returned OK together with non-empty errors",
            details={"errors": list(errors)},
        )

    application = evidence.get("application")
    if not isinstance(application, dict):
        return EvidenceValidation(
            False,
            "MALFORMED_EVIDENCE",
            "reader application metadata must be an object",
        )
    if application.get("name") != "After Effects":
        return EvidenceValidation(
            False,
            "MALFORMED_EVIDENCE",
            "reader application name is invalid",
        )
    if _application_build_identity(application) is None:
        return EvidenceValidation(
            False,
            "MALFORMED_EVIDENCE",
            "reader application build metadata is incomplete",
        )
    if _normalize_locale(application.get("language")) is None:
        return EvidenceValidation(
            False,
            "MALFORMED_EVIDENCE",
            "reader application language is missing",
        )

    state = evidence.get("state")
    if not isinstance(state, dict):
        return EvidenceValidation(False, "MALFORMED_EVIDENCE", "reader state must be an object")

    return EvidenceValidation(
        True,
        state=state,
        details={
            "request_id": request_id,
            "captured_at": float(captured_at),
            "supported_capabilities": list(supported),
            "application": dict(application),
            "application_build_identity": _application_build_identity(application),
        },
    )


def check_environment(
    actual: Dict[str, Any],
    contract: Dict[str, Any],
    *,
    expected_ae_build: Optional[Any] = None,
) -> Tuple[bool, Optional[str], Optional[str], Dict[str, Any]]:
    if not isinstance(actual, dict):
        return False, "ENVIRONMENT_MISSING", "environment evidence is missing", {}

    details: Dict[str, Any] = {}

    if actual.get("after_effects_process_running") is not True:
        return False, "AE_PROCESS_NOT_RUNNING", "After Effects process is not running", details

    modal_state = actual.get("unknown_modal_dialog")
    if modal_state is not False:
        return False, (
            "UNKNOWN_MODAL_DIALOG" if modal_state is True else "ENVIRONMENT_MISSING"
        ), (
            "unknown modal dialog is open"
            if modal_state is True
            else "unknown_modal_dialog evidence must explicitly be false"
        ), details

    expected_os = contract.get("operating_system")
    actual_os = actual.get("operating_system")
    if expected_os and actual_os != expected_os:
        return False, "ENVIRONMENT_MISMATCH", f"operating system must be {expected_os}", {
            "expected": expected_os,
            "actual": actual_os,
        }

    display_contract = contract.get("display") or {}
    expected_resolution = display_contract.get("required_resolution")
    if expected_resolution is not None and actual.get("display_resolution") != expected_resolution:
        return False, "ENVIRONMENT_MISMATCH", "display resolution mismatch", {
            "expected": expected_resolution,
            "actual": actual.get("display_resolution"),
        }

    expected_scaling = display_contract.get("required_scaling_percent")
    if expected_scaling is not None and actual.get("display_scaling_percent") != expected_scaling:
        return False, "ENVIRONMENT_MISMATCH", "display scaling mismatch", {
            "expected": expected_scaling,
            "actual": actual.get("display_scaling_percent"),
        }

    ae_contract = contract.get("after_effects") or {}
    expected_major = ae_contract.get("required_major_version")
    if expected_major is not None and actual.get("ae_major_version") != expected_major:
        return False, "ENVIRONMENT_MISMATCH", "After Effects major version mismatch", {
            "expected": expected_major,
            "actual": actual.get("ae_major_version"),
        }

    expected_language = ae_contract.get("required_language")
    if expected_language is not None and actual.get("ae_language") != expected_language:
        return False, "ENVIRONMENT_MISMATCH", "After Effects language mismatch", {
            "expected": expected_language,
            "actual": actual.get("ae_language"),
        }

    expected_workspace = ae_contract.get("required_workspace_id")
    if expected_workspace is not None and actual.get("workspace_id") != expected_workspace:
        return False, "ENVIRONMENT_MISMATCH", "After Effects workspace mismatch", {
            "expected": expected_workspace,
            "actual": actual.get("workspace_id"),
        }

    fixture_path = actual.get("fixture_path")
    if not isinstance(fixture_path, str) or not fixture_path.strip():
        return False, "FIXTURE_IDENTITY_REQUIRED", "expected fixture_path is missing", details
    details["expected_fixture_path"] = fixture_path

    observed_build = actual.get("ae_build")
    details["observed_ae_build"] = observed_build
    exact_build_policy = ae_contract.get("exact_build_policy")
    if exact_build_policy == "record_and_pin_for_pilot_batch":
        if expected_ae_build is None:
            return False, "AE_BUILD_PIN_REQUIRED", (
                "the pilot requires an exact After Effects build pinned for the batch"
            ), {
                "actual": observed_build,
            }
        if observed_build != expected_ae_build:
            return False, "ENVIRONMENT_MISMATCH", "After Effects build differs from pinned pilot build", {
                "expected": expected_ae_build,
                "actual": observed_build,
            }
    elif expected_ae_build is not None and observed_build != expected_ae_build:
        return False, "ENVIRONMENT_MISMATCH", "After Effects build differs from pinned pilot build", {
            "expected": expected_ae_build,
            "actual": observed_build,
        }

    return True, None, None, details


def _runtime_calibration_check(
    skill: Dict[str, Any],
    runtime: Dict[str, Any],
) -> Tuple[bool, Optional[str], Dict[str, Any]]:
    calibration = skill.get("runtime_calibration")
    if not isinstance(calibration, dict):
        return True, None, {}

    missing = []
    invalid = []
    resolved: Dict[str, Any] = {}
    for key, contract_value in calibration.items():
        if key == "rule":
            continue
        if key in runtime and runtime[key] not in (None, ""):
            resolved[key] = runtime[key]
        elif contract_value not in (None, ""):
            resolved[key] = contract_value
        else:
            missing.append(key)
            continue

        if key.endswith("_id") and (
            not isinstance(resolved[key], str) or not resolved[key].strip()
        ):
            invalid.append(key)

    if missing:
        return False, "runtime calibration missing: " + ", ".join(sorted(missing)), {
            "missing_runtime_calibration": sorted(missing)
        }
    if invalid:
        return False, "runtime calibration invalid: " + ", ".join(sorted(invalid)), {
            "invalid_runtime_calibration": sorted(invalid)
        }
    return True, None, resolved


class DeterministicVerifier:
    def __init__(self, contract: PilotContract):
        self.contract = contract

    def verify_preflight(
        self,
        *,
        skill_id: str,
        evidence: Dict[str, Any],
        expected_run_id: str,
        expected_request_id: Optional[str],
        run_started_at: float,
        environment: Dict[str, Any],
        runtime: Optional[Dict[str, Any]] = None,
        expected_ae_build: Optional[Any] = None,
    ) -> PreflightDecision:
        runtime = dict(runtime or {})
        skill = self.contract.skill(skill_id)

        if not isinstance(expected_run_id, str) or not expected_run_id:
            return PreflightDecision(
                False,
                "BLOCKED",
                "RUN_ID_REQUIRED",
                "a non-empty run_id is required before execution",
            )
        if not isinstance(expected_request_id, str) or not expected_request_id:
            return PreflightDecision(
                False,
                "BLOCKED",
                "REQUEST_ID_REQUIRED",
                "a non-empty pre-state request_id is required before execution",
            )
        if not _is_number(run_started_at):
            return PreflightDecision(
                False,
                "BLOCKED",
                "RUN_START_TIMESTAMP_REQUIRED",
                "a numeric run start timestamp is required before execution",
            )

        environment_ok, env_code, env_reason, env_details = check_environment(
            environment,
            self.contract.environment_contract,
            expected_ae_build=expected_ae_build,
        )
        if not environment_ok:
            return PreflightDecision(
                False,
                "BLOCKED",
                env_code,
                env_reason,
                details=env_details,
            )

        evidence_check = validate_evidence(
            evidence,
            expected_run_id=expected_run_id,
            expected_request_id=expected_request_id,
            expected_reader_version=self.contract.expected_reader_version(),
            expected_schema_version=self.contract.expected_reader_schema_version(),
            min_captured_at=run_started_at,
        )
        if not evidence_check.valid:
            return PreflightDecision(
                False,
                "BLOCKED",
                evidence_check.error_code,
                evidence_check.reason,
                details=evidence_check.details,
            )

        supported = set(evidence_check.details.get("supported_capabilities") or [])
        fixture = self.contract.fixture_for_skill(skill_id)
        required_state = fixture.get("required_state")
        if not isinstance(required_state, dict):
            return PreflightDecision(
                False,
                "BLOCKED",
                "FIXTURE_SPEC_INVALID",
                "fixture required_state is missing or invalid",
            )

        system_required = {
            "project.file_identity",
            "application.version",
            "application.language",
        }
        fixture_required = _fixture_state_capabilities(required_state)
        required = (
            set(self.contract.required_capabilities(skill_id))
            | fixture_required
            | system_required
        )
        missing = sorted(required - supported)
        if missing:
            return PreflightDecision(
                False,
                "BLOCKED",
                "READER_CAPABILITY_MISSING",
                "required AE Reader capabilities are absent",
                details={"missing_capabilities": missing},
            )

        application = evidence_check.details.get("application") or {}
        reader_major = _parse_major_version(application.get("version"))
        reader_language = _normalize_locale(application.get("language"))
        reader_build_identity = evidence_check.details.get("application_build_identity")
        expected_language = self.contract.environment_contract.get("after_effects", {}).get(
            "required_language"
        )

        if reader_major != environment.get("ae_major_version"):
            return PreflightDecision(
                False,
                "BLOCKED",
                "READER_ENVIRONMENT_MISMATCH",
                "AE Reader application version does not match preflight environment evidence",
                details={
                    "reader_major_version": reader_major,
                    "environment_major_version": environment.get("ae_major_version"),
                },
            )
        if reader_language != _normalize_locale(environment.get("ae_language")):
            return PreflightDecision(
                False,
                "BLOCKED",
                "READER_ENVIRONMENT_MISMATCH",
                "AE Reader language does not match preflight environment evidence",
                details={
                    "reader_language": application.get("language"),
                    "environment_language": environment.get("ae_language"),
                },
            )
        if reader_language != _normalize_locale(expected_language):
            return PreflightDecision(
                False,
                "BLOCKED",
                "READER_ENVIRONMENT_MISMATCH",
                "AE Reader language does not match the locked pilot language",
                details={
                    "reader_language": application.get("language"),
                    "required_language": expected_language,
                },
            )
        if reader_build_identity != environment.get("ae_build"):
            return PreflightDecision(
                False,
                "BLOCKED",
                "READER_ENVIRONMENT_MISMATCH",
                "AE Reader build identity does not match preflight environment evidence",
                details={
                    "reader_build": reader_build_identity,
                    "environment_build": environment.get("ae_build"),
                },
            )

        project_state = (evidence_check.state or {}).get("project")
        observed_fixture_path = (
            project_state.get("file_path")
            if isinstance(project_state, dict)
            else None
        )
        expected_fixture_path = environment.get("fixture_path")
        if (
            not isinstance(observed_fixture_path, str)
            or not observed_fixture_path
            or not isinstance(expected_fixture_path, str)
            or not _same_windows_path(observed_fixture_path, expected_fixture_path)
        ):
            return PreflightDecision(
                False,
                "BLOCKED",
                "FIXTURE_IDENTITY_MISMATCH",
                "AE Reader project file does not match the expected disposable fixture copy",
                details={
                    "expected_fixture_path": expected_fixture_path,
                    "observed_fixture_path": observed_fixture_path,
                },
            )

        calibration_ok, calibration_reason, resolved_calibration = _runtime_calibration_check(
            skill,
            runtime,
        )
        if not calibration_ok:
            return PreflightDecision(
                False,
                "BLOCKED",
                "RUNTIME_CALIBRATION_MISSING",
                calibration_reason,
                details=resolved_calibration,
            )
        runtime.update(resolved_calibration)

        fixture_mismatches = compare_fixture_state(
            required_state,
            evidence_check.state,
            comparison_policy=self.contract.comparison_policy,
        )
        if fixture_mismatches:
            return PreflightDecision(
                False,
                "BLOCKED",
                "FIXTURE_STATE_MISMATCH",
                "loaded fixture does not match its canonical required state",
                details={
                    "fixture_id": fixture.get("id"),
                    "mismatches": fixture_mismatches,
                },
            )

        assertion_results = evaluate_assertions(
            evidence_check.state,
            self.contract.pre_assertions(skill_id),
            runtime=runtime,
            comparison_policy=self.contract.comparison_policy,
        )
        if assertion_results.contract_error:
            return PreflightDecision(
                False,
                "BLOCKED",
                "ASSERTION_CONTRACT_ERROR",
                "precondition assertion contract is invalid",
                assertion_results=assertion_results,
            )
        if not assertion_results.passed:
            return PreflightDecision(
                False,
                "BLOCKED",
                "PRECONDITION_FAILED",
                "one or more precondition assertions failed",
                assertion_results=assertion_results,
            )

        return PreflightDecision(
            True,
            None,
            None,
            None,
            assertion_results=assertion_results,
            details={
                "skill_id": skill_id,
                "run_id": expected_run_id,
                "pre_request_id": expected_request_id,
                "run_started_at": float(run_started_at),
                "pre_captured_at": float(evidence_check.details["captured_at"]),
                "fixture_id": fixture.get("id"),
                "runtime": runtime,
                "reader_build_identity": reader_build_identity,
                "reader_language": reader_language,
                **env_details,
            },
        )

    def verify_post(
        self,
        *,
        skill_id: str,
        preflight: PreflightDecision,
        execution_completed: bool,
        evidence: Optional[Dict[str, Any]],
        expected_run_id: str,
        expected_request_id: Optional[str],
        last_action_at: float,
        runtime: Optional[Dict[str, Any]] = None,
        blocked_reason: Optional[str] = None,
        ui_change_evidence: Optional[Dict[str, Any]] = None,
    ) -> RunDecision:
        if not isinstance(execution_completed, bool):
            return RunDecision(
                "INCONCLUSIVE",
                "EXECUTION_FLAG_INVALID",
                "execution_completed must be an explicit boolean",
            )

        supplied_runtime = dict(runtime or {})
        pinned_runtime = dict(preflight.details.get("runtime") or {})

        if not preflight.can_execute:
            return RunDecision(
                "BLOCKED",
                preflight.reason_code or "PREFLIGHT_BLOCKED",
                preflight.reason or "preflight blocked execution",
                assertion_results=preflight.assertion_results,
                details=preflight.details,
            )

        pinned_skill_id = preflight.details.get("skill_id")
        if pinned_skill_id != skill_id:
            return RunDecision(
                "INCONCLUSIVE",
                "PREFLIGHT_SKILL_MISMATCH",
                "post verification skill_id does not match the preflight skill",
                details={"preflight_skill_id": pinned_skill_id, "post_skill_id": skill_id},
            )

        pinned_run_id = preflight.details.get("run_id")
        if pinned_run_id != expected_run_id:
            return RunDecision(
                "INCONCLUSIVE",
                "PREFLIGHT_RUN_MISMATCH",
                "post verification run_id does not match the preflight run",
                details={"preflight_run_id": pinned_run_id, "post_run_id": expected_run_id},
            )

        runtime_conflicts = {
            key: {"preflight": pinned_runtime[key], "post": value}
            for key, value in supplied_runtime.items()
            if key in pinned_runtime and pinned_runtime[key] != value
        }
        if runtime_conflicts:
            return RunDecision(
                "INCONCLUSIVE",
                "RUNTIME_CALIBRATION_CHANGED",
                "runtime calibration changed after preflight",
                details={"conflicts": runtime_conflicts},
            )
        runtime = pinned_runtime

        if blocked_reason:
            return RunDecision(
                "BLOCKED",
                "RUNTIME_BLOCKED",
                blocked_reason,
            )

        if isinstance(ui_change_evidence, dict) and not execution_completed:
            route_changed = ui_change_evidence.get("route_changed") is True
            capability_exists = ui_change_evidence.get("capability_still_exists") is True
            independent_evidence = ui_change_evidence.get("evidence")
            evidence_present = (
                isinstance(independent_evidence, (str, list, dict))
                and bool(independent_evidence)
            )
            if route_changed and capability_exists and evidence_present:
                return RunDecision(
                    "UI_CHANGED",
                    "EVIDENCE_BACKED_UI_CHANGE",
                    "stored UI route changed while independent evidence supports the capability",
                    details=dict(ui_change_evidence),
                )

        if not execution_completed:
            return RunDecision(
                "EXECUTION_FAILED",
                "EXECUTION_DID_NOT_COMPLETE",
                "measured UI interaction sequence did not complete",
            )

        if not isinstance(expected_request_id, str) or not expected_request_id:
            return RunDecision(
                "INCONCLUSIVE",
                "REQUEST_ID_REQUIRED",
                "a non-empty post-state request_id is required for verification",
            )
        pre_request_id = preflight.details.get("pre_request_id")
        if expected_request_id == pre_request_id:
            return RunDecision(
                "INCONCLUSIVE",
                "POST_REQUEST_ID_REUSED",
                "post-state must use a new AE Reader request_id distinct from preflight",
                details={
                    "pre_request_id": pre_request_id,
                    "post_request_id": expected_request_id,
                },
            )
        if not _is_number(last_action_at):
            return RunDecision(
                "INCONCLUSIVE",
                "LAST_ACTION_TIMESTAMP_REQUIRED",
                "a numeric last-action timestamp is required for freshness verification",
            )

        pre_captured_at = preflight.details.get("pre_captured_at")
        run_started_at = preflight.details.get("run_started_at")
        if (
            not _is_number(pre_captured_at)
            or not _is_number(run_started_at)
            or float(last_action_at) <= float(pre_captured_at)
            or float(last_action_at) <= float(run_started_at)
        ):
            return RunDecision(
                "INCONCLUSIVE",
                "ACTION_TIMESTAMP_ORDER_INVALID",
                "last measured action must be newer than both run start and pre-state capture",
                details={
                    "run_started_at": run_started_at,
                    "pre_captured_at": pre_captured_at,
                    "last_action_at": last_action_at,
                },
            )

        if evidence is None:
            return RunDecision(
                "INCONCLUSIVE",
                "MISSING_POST_EVIDENCE",
                "post-execution AE Reader evidence is missing",
            )

        evidence_check = validate_evidence(
            evidence,
            expected_run_id=expected_run_id,
            expected_request_id=expected_request_id,
            expected_reader_version=self.contract.expected_reader_version(),
            expected_schema_version=self.contract.expected_reader_schema_version(),
            min_captured_at=last_action_at,
        )
        if not evidence_check.valid:
            return RunDecision(
                "INCONCLUSIVE",
                evidence_check.error_code or "INVALID_POST_EVIDENCE",
                evidence_check.reason or "post-execution evidence is invalid",
                details=evidence_check.details,
            )

        post_supported = set(
            evidence_check.details.get("supported_capabilities") or []
        )
        post_required = set(self.contract.required_capabilities(skill_id)) | {
            "project.file_identity",
            "application.version",
            "application.language",
        }
        missing_post_capabilities = sorted(post_required - post_supported)
        if missing_post_capabilities:
            return RunDecision(
                "INCONCLUSIVE",
                "READER_CAPABILITY_MISSING",
                "post-state AE Reader evidence lacks required capabilities",
                details={"missing_capabilities": missing_post_capabilities},
            )

        post_application = evidence_check.details.get("application") or {}
        post_build_identity = evidence_check.details.get("application_build_identity")
        post_language = _normalize_locale(post_application.get("language"))
        if post_build_identity != preflight.details.get("reader_build_identity"):
            return RunDecision(
                "INCONCLUSIVE",
                "POST_APPLICATION_BUILD_MISMATCH",
                "After Effects build changed between preflight and post-state evidence",
                details={
                    "preflight_build": preflight.details.get("reader_build_identity"),
                    "post_build": post_build_identity,
                },
            )
        if post_language != preflight.details.get("reader_language"):
            return RunDecision(
                "INCONCLUSIVE",
                "POST_APPLICATION_LANGUAGE_MISMATCH",
                "After Effects language changed between preflight and post-state evidence",
                details={
                    "preflight_language": preflight.details.get("reader_language"),
                    "post_language": post_application.get("language"),
                },
            )

        expected_fixture_path = preflight.details.get("expected_fixture_path")
        if not isinstance(expected_fixture_path, str) or not expected_fixture_path:
            return RunDecision(
                "INCONCLUSIVE",
                "FIXTURE_IDENTITY_REQUIRED",
                "preflight did not preserve the expected disposable fixture path",
            )

        post_project_state = (evidence_check.state or {}).get("project")
        post_fixture_path = (
            post_project_state.get("file_path")
            if isinstance(post_project_state, dict)
            else None
        )
        if (
            not isinstance(post_fixture_path, str)
            or not post_fixture_path
            or not _same_windows_path(post_fixture_path, expected_fixture_path)
        ):
            return RunDecision(
                "INCONCLUSIVE",
                "POST_FIXTURE_IDENTITY_MISMATCH",
                "post-state belongs to a different or unidentified project file",
                details={
                    "expected_fixture_path": expected_fixture_path,
                    "observed_fixture_path": post_fixture_path,
                },
            )

        assertion_results = evaluate_assertions(
            evidence_check.state,
            self.contract.post_assertions(skill_id),
            runtime=runtime,
            comparison_policy=self.contract.comparison_policy,
        )
        if assertion_results.contract_error:
            return RunDecision(
                "INCONCLUSIVE",
                "ASSERTION_CONTRACT_ERROR",
                "postcondition assertion contract is invalid",
                assertion_results=assertion_results,
            )

        if not assertion_results.passed:
            return RunDecision(
                "VERIFICATION_FAILED",
                "POSTCONDITION_FAILED",
                "fresh AE Reader state disproves one or more required postconditions",
                assertion_results=assertion_results,
            )

        return RunDecision(
            "PASS",
            "ALL_POSTCONDITIONS_PASS",
            "fresh AE Reader evidence satisfies every required postcondition",
            assertion_results=assertion_results,
        )

    def aggregate_skill(self, run_statuses: Iterable[str]) -> SkillDecision:
        statuses = list(run_statuses)
        verified_count = sum(1 for status in statuses if status == "PASS")

        if len(statuses) != self.contract.required_repetitions:
            return SkillDecision(
                "NEEDS_REVIEW",
                statuses,
                verified_count,
                (
                    f"expected {self.contract.required_repetitions} independent runs, "
                    f"received {len(statuses)}"
                ),
            )

        if all(status == "PASS" for status in statuses):
            return SkillDecision(
                "VERIFIED",
                statuses,
                verified_count,
                None,
            )

        review_statuses = {"UI_CHANGED", "BLOCKED", "INCONCLUSIVE"}
        if any(status in review_statuses for status in statuses):
            return SkillDecision(
                "NEEDS_REVIEW",
                statuses,
                verified_count,
                "one or more runs require review because evidence or environment is unresolved",
            )

        failure_statuses = {"EXECUTION_FAILED", "VERIFICATION_FAILED"}
        if any(status in failure_statuses for status in statuses):
            return SkillDecision(
                "NOT_VERIFIED",
                statuses,
                verified_count,
                "one or more completed runs failed execution or deterministic verification",
            )

        return SkillDecision(
            "NEEDS_REVIEW",
            statuses,
            verified_count,
            "run outcomes do not satisfy a defined aggregate rule",
        )
