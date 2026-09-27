"""Fail-closed verification engine for the AE 10-skill pilot."""

from __future__ import annotations

import copy
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
    return isinstance(value, Real) and not isinstance(value, bool)


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
    if expected_ae_build is not None and observed_build != expected_ae_build:
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

    if missing:
        return False, "runtime calibration missing: " + ", ".join(sorted(missing)), {
            "missing_runtime_calibration": sorted(missing)
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
        system_required = {"project.file_identity"}
        required = set(self.contract.required_capabilities(skill_id)) | system_required
        missing = sorted(required - supported)
        if missing:
            return PreflightDecision(
                False,
                "BLOCKED",
                "READER_CAPABILITY_MISSING",
                "required AE Reader capabilities are absent",
                details={"missing_capabilities": missing},
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

        fixture = self.contract.fixture_for_skill(skill_id)
        required_state = fixture.get("required_state")
        if not isinstance(required_state, dict):
            return PreflightDecision(
                False,
                "BLOCKED",
                "FIXTURE_SPEC_INVALID",
                "fixture required_state is missing or invalid",
            )

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
                "fixture_id": fixture.get("id"),
                "runtime": runtime,
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
        runtime = dict(runtime or {})
        if preflight.details.get("runtime"):
            runtime = {**preflight.details["runtime"], **runtime}

        if not preflight.can_execute:
            return RunDecision(
                "BLOCKED",
                preflight.reason_code or "PREFLIGHT_BLOCKED",
                preflight.reason or "preflight blocked execution",
                assertion_results=preflight.assertion_results,
                details=preflight.details,
            )

        if blocked_reason:
            return RunDecision(
                "BLOCKED",
                "RUNTIME_BLOCKED",
                blocked_reason,
            )

        if isinstance(ui_change_evidence, dict) and not execution_completed:
            route_changed = ui_change_evidence.get("route_changed") is True
            capability_exists = ui_change_evidence.get("capability_still_exists") is True
            if route_changed and capability_exists:
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
        if not _is_number(last_action_at):
            return RunDecision(
                "INCONCLUSIVE",
                "LAST_ACTION_TIMESTAMP_REQUIRED",
                "a numeric last-action timestamp is required for freshness verification",
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
        if "project.file_identity" not in post_supported:
            return RunDecision(
                "INCONCLUSIVE",
                "READER_CAPABILITY_MISSING",
                "post-state AE Reader evidence lacks project.file_identity",
                details={"missing_capabilities": ["project.file_identity"]},
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
