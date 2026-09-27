"""Mandatory verifier calibration controls from the pilot contract."""

from __future__ import annotations

from typing import Any, Dict

from .assertions import evaluate_assertions
from .contract import PilotContract
from .engine import validate_evidence


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
    """Run CAL-POSITIVE, CAL-NEGATIVE, and CAL-STALE without mutating AE."""
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
        "passed": all(item["passed"] for item in controls.values()),
        "controls": controls,
    }
