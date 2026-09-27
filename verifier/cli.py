"""Command-line interface for the deterministic verifier."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict

from .calibration import run_calibration
from .contract import ContractError, PilotContract
from .engine import DeterministicVerifier


DEFAULT_CONTRACT = Path(__file__).resolve().parents[1] / "pilot_10_skills.yaml"


def _load_json(path: str) -> Dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SystemExit(f"unable to load JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise SystemExit(f"JSON root must be an object: {path}")
    return value


def _print(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def _load_contract(path: str) -> PilotContract:
    try:
        return PilotContract.load(path)
    except ContractError as exc:
        raise SystemExit(f"contract validation failed: {exc}") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AE pilot deterministic verifier")
    parser.add_argument(
        "--contract",
        default=str(DEFAULT_CONTRACT),
        help="Path to pilot_10_skills.yaml",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("validate-contract", help="Load and validate the pilot contract")
    sub.add_parser("calibrate", help="Run mandatory positive/negative/stale controls")

    run = sub.add_parser("verify-run", help="Verify one complete measured run from a JSON bundle")
    run.add_argument("--bundle", required=True)

    aggregate = sub.add_parser("aggregate", help="Aggregate independent run statuses")
    aggregate.add_argument("statuses", nargs="+")

    return parser


def _verify_bundle(verifier: DeterministicVerifier, bundle: Dict[str, Any]) -> Dict[str, Any]:
    required = [
        "skill_id",
        "run_id",
        "run_started_at",
        "last_action_at",
        "environment",
        "pre_evidence",
        "execution_completed",
    ]
    missing = [key for key in required if key not in bundle]
    if missing:
        raise SystemExit("verification bundle missing fields: " + ", ".join(missing))

    preflight = verifier.verify_preflight(
        skill_id=str(bundle["skill_id"]),
        evidence=bundle["pre_evidence"],
        expected_run_id=str(bundle["run_id"]),
        expected_request_id=bundle.get("pre_request_id"),
        run_started_at=float(bundle["run_started_at"]),
        environment=bundle["environment"],
        runtime=bundle.get("runtime") or {},
        expected_ae_build=bundle.get("expected_ae_build"),
    )

    decision = verifier.verify_post(
        skill_id=str(bundle["skill_id"]),
        preflight=preflight,
        execution_completed=bool(bundle["execution_completed"]),
        evidence=bundle.get("post_evidence"),
        expected_run_id=str(bundle["run_id"]),
        expected_request_id=bundle.get("post_request_id"),
        last_action_at=float(bundle["last_action_at"]),
        runtime=bundle.get("runtime") or {},
        blocked_reason=bundle.get("blocked_reason"),
        ui_change_evidence=bundle.get("ui_change_evidence"),
    )

    return {
        "skill_id": bundle["skill_id"],
        "run_id": bundle["run_id"],
        "preflight": preflight.to_dict(),
        "decision": decision.to_dict(),
    }


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    contract = _load_contract(args.contract)
    verifier = DeterministicVerifier(contract)

    if args.command == "validate-contract":
        result = {
            "status": "PASS",
            "format_version": contract.raw.get("format_version"),
            "skill_count": len(contract.skills),
            "fixture_count": len(contract.fixtures),
            "required_repetitions": contract.required_repetitions,
            "reader_version": contract.expected_reader_version(),
            "reader_schema_version": contract.expected_reader_schema_version(),
        }
        _print(result)
        return 0

    if args.command == "calibrate":
        result = run_calibration(contract)
        _print(result)
        return 0 if result["passed"] else 1

    if args.command == "verify-run":
        bundle = _load_json(args.bundle)
        result = _verify_bundle(verifier, bundle)
        _print(result)
        status = result["decision"]["run_status"]
        return 0 if status == "PASS" else 2

    if args.command == "aggregate":
        result = verifier.aggregate_skill(args.statuses).to_dict()
        _print(result)
        return 0 if result["skill_status"] == "VERIFIED" else 2

    return 2


if __name__ == "__main__":
    sys.exit(main())
