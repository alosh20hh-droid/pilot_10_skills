"""Verifier calibration controls.

Two levels exist:
- software self-calibration: deterministic CI check with synthetic state;
- pilot calibration: consumes fresh AE Reader evidence from a canonical fixture.

Only the pilot calibration satisfies the pre-pilot gate in pilot_10_skills.yaml.
"""

from __future__ import annotations

import copy
from typing import Any, Dict, Optional

from .assertions import evaluate_assertions
from .contract import PilotContract
from .engine import compare_fixture_state, validate_evidence


def _canonical_state() -> Dict[str, Any]:
    return {
        "project": {"composition_count": 1},
        "active_comp": {
            "name": "PILOT_COMP",
            "width": 1920,
            "height": 1080,
            "duration_seconds": 5.0,
            "frame_rate": 30.0,
            "current_time_seconds": 0.0,
            "current_time_frame": 0,
        },
        "layers": [],
    }


def _fresh_evidence(contract: PilotContract, *, captured_at: float = 20.0) -> Dict[str, Any]:
    return {
        "status": "OK",
        "request_id": "cal-request",
        "run_id": "cal-run",
        "captured_at": captured_at,
        "reader_version": contract.expected_reader_version(),
        "schema_version": contract.expected_reader_schema_version(),
        "capabilities": {
            "reader_version": contract.expected_reader_version(),
            "schema_version": contract.expected_reader_schema_version(),
            "supported_capabilities": list(
                contract.ae_reader_contract.get("known_capability_ids") or []
            ),
        },
        "state": _canonical_state(),
        "errors": [],
    }


def run_calibration(contract: PilotContract) -> Dict[str, Any]:
    """Software self-calibration for CI. This is not the live pilot gate."""
    canonical = _canonical_state()

    positive = evaluate_assertions(
        canonical,
        [{"path": "project.composition_count", "op": "eq", "value": 1}],
        comparison_policy=contract.comparison_policy,
    )
    positive_status = "PASS" if positive.passed and not positive.contract_error else "INCONCLUSIVE"

    negative = evaluate_assertions(
        canonical,
        [{"path": "project.composition_count", "op": "eq", "value": 999}],
        comparison_policy=contract.comparison_policy,
    )
    negative_status = (
        "VERIFICATION_FAILED"
        if not negative.passed and not negative.contract_error
        else "INCONCLUSIVE"
    )

    stale_evidence = _fresh_evidence(contract, captured_at=10.0)
    stale = validate_evidence(
        stale_evidence,
        expected_run_id="cal-run",
        expected_request_id="cal-request",
        expected_reader_version=contract.expected_reader_version(),
        expected_schema_version=contract.expected_reader_schema_version(),
        min_captured_at=15.0,
    )
    stale_status = "INCONCLUSIVE" if not stale.valid and stale.error_code == "STALE_EVIDENCE" else "PASS"

    controls = {
        "CAL-POSITIVE": {
            "expected": "PASS",
            "actual": positive_status,
            "passed": positive_status == "PASS",
        },
        "CAL-NEGATIVE": {
            "expected": "VERIFICATION_FAILED",
            "actual": negative_status,
            "passed": negative_status == "VERIFICATION_FAILED",
        },
        "CAL-STALE": {
            "expected": "INCONCLUSIVE",
            "actual": stale_status,
            "passed": stale_status == "INCONCLUSIVE",
        },
    }

    return {
        "mode": "SOFTWARE_SELF_CALIBRATION",
        "satisfies_pilot_gate": False,
        "passed": all(item["passed"] for item in controls.values()),
        "controls": controls,
    }


def run_pilot_calibration(
    contract: PilotContract,
    *,
    evidence: Dict[str, Any],
    fixture_id: str,
    expected_run_id: str,
    expected_request_id: str,
    min_captured_at: float,
) -> Dict[str, Any]:
    """Run the three required controls against fresh canonical-fixture evidence."""
    if fixture_id not in contract.fixtures:
        return {
            "mode": "PILOT_EVIDENCE_CALIBRATION",
            "satisfies_pilot_gate": False,
            "passed": False,
            "error": f"unknown fixture: {fixture_id}",
            "controls": {},
        }

    fresh = validate_evidence(
        evidence,
        expected_run_id=expected_run_id,
        expected_request_id=expected_request_id,
        expected_reader_version=contract.expected_reader_version(),
        expected_schema_version=contract.expected_reader_schema_version(),
        min_captured_at=min_captured_at,
    )

    fixture = contract.fixtures[fixture_id]
    fixture_state = fixture.get("required_state")
    if fresh.valid and isinstance(fixture_state, dict):
        mismatches = compare_fixture_state(
            fixture_state,
            fresh.state,
            comparison_policy=contract.comparison_policy,
        )
    else:
        mismatches = [{"reason": fresh.reason or "invalid fixture state"}]

    positive_status = "PASS" if fresh.valid and not mismatches else "INCONCLUSIVE"

    # Negative control changes only an expectation. AE state is never mutated.
    actual_count = None
    if fresh.valid:
        actual_count = ((fresh.state or {}).get("project") or {}).get("composition_count")
    if isinstance(actual_count, int) and not isinstance(actual_count, bool):
        wrong_count = actual_count + 1
        negative = evaluate_assertions(
            fresh.state or {},
            [{"path": "project.composition_count", "op": "eq", "value": wrong_count}],
            comparison_policy=contract.comparison_policy,
        )
        negative_status = (
            "VERIFICATION_FAILED"
            if not negative.passed and not negative.contract_error
            else "INCONCLUSIVE"
        )
    else:
        wrong_count = None
        negative_status = "INCONCLUSIVE"

    # Stale control replays the exact response but asks the verifier to bind it
    # to a deliberately different request identity. No AE mutation occurs.
    replay = copy.deepcopy(evidence)
    stale = validate_evidence(
        replay,
        expected_run_id=expected_run_id,
        expected_request_id=expected_request_id + "-deliberately-wrong",
        expected_reader_version=contract.expected_reader_version(),
        expected_schema_version=contract.expected_reader_schema_version(),
        min_captured_at=min_captured_at,
    )
    stale_status = (
        "INCONCLUSIVE"
        if not stale.valid and stale.error_code == "STALE_EVIDENCE"
        else "PASS"
    )

    controls = {
        "CAL-POSITIVE": {
            "expected": "PASS",
            "actual": positive_status,
            "passed": positive_status == "PASS",
            "fixture_id": fixture_id,
            "fixture_mismatches": mismatches,
        },
        "CAL-NEGATIVE": {
            "expected": "VERIFICATION_FAILED",
            "actual": negative_status,
            "passed": negative_status == "VERIFICATION_FAILED",
            "injected_expected_composition_count": wrong_count,
        },
        "CAL-STALE": {
            "expected": "INCONCLUSIVE",
            "actual": stale_status,
            "passed": stale_status == "INCONCLUSIVE",
            "mechanism": "request_id mismatch replay",
        },
    }

    passed = all(item["passed"] for item in controls.values())
    return {
        "mode": "PILOT_EVIDENCE_CALIBRATION",
        "satisfies_pilot_gate": passed,
        "passed": passed,
        "fixture_id": fixture_id,
        "run_id": expected_run_id,
        "request_id": expected_request_id,
        "controls": controls,
    }
