"""Command-line interface for fixture specification, materialization, certification, and run copies."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from verifier.contract import PilotContract

from .builder import FixtureBuildError
from .manager import FixtureCertificationError, FixtureRepository
from .materializer import FixtureMaterializer
from .spec import FixtureSpecError, compile_all_fixture_plans, compile_fixture_plan


DEFAULT_CONTRACT = Path(__file__).resolve().parents[1] / "pilot_10_skills.yaml"


def _print(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def _load_contract(path: str) -> PilotContract:
    return PilotContract.load(path)


def _acknowledged(args: argparse.Namespace) -> bool:
    return bool(getattr(args, "ack_disposable_ae_project", False))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AE pilot fixture system")
    parser.add_argument("--contract", default=str(DEFAULT_CONTRACT))
    parser.add_argument("--afterfx-path", default=None)

    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("validate-specs", help="Compile and validate all ten fixture specs")

    plan = sub.add_parser("plan", help="Print the deterministic build plan for one fixture")
    plan.add_argument("--fixture-id", required=True)
    plan.add_argument("--output", default="<canonical-fixture-path>")

    materialize = sub.add_parser(
        "materialize",
        help="Build and certify one canonical .aep fixture on real After Effects",
    )
    materialize.add_argument("--fixture-id", required=True)
    materialize.add_argument("--timeout", type=float, default=30.0)
    materialize.add_argument(
        "--ack-disposable-ae-project",
        action="store_true",
        help="Required: confirms current AE project may be closed without saving",
    )

    materialize_all = sub.add_parser(
        "materialize-all",
        help="Build and certify all ten canonical .aep fixtures",
    )
    materialize_all.add_argument("--timeout", type=float, default=30.0)
    materialize_all.add_argument(
        "--ack-disposable-ae-project",
        action="store_true",
        help="Required: confirms current AE project may be closed without saving",
    )

    status = sub.add_parser("status", help="Check certification/integrity state of all fixtures")

    verify = sub.add_parser("verify-canonical", help="Verify one canonical fixture hash and certification")
    verify.add_argument("--fixture-id", required=True)

    run_copy = sub.add_parser("create-run-copy", help="Create one fresh immutable-certified run copy")
    run_copy.add_argument("--fixture-id", required=True)
    run_copy.add_argument("--run-id", required=True)

    cleanup = sub.add_parser("remove-run-copy", help="Delete one disposable run workspace")
    cleanup.add_argument("--run-id", required=True)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        contract = _load_contract(args.contract)
        repository = FixtureRepository(contract)

        if args.command == "validate-specs":
            plans = compile_all_fixture_plans(contract)
            _print({
                "status": "PASS",
                "fixture_count": len(plans),
                "fixture_ids": [plan.fixture_id for plan in plans],
            })
            return 0

        if args.command == "plan":
            plan = compile_fixture_plan(contract, args.fixture_id)
            _print(plan.to_request(args.output))
            return 0

        if args.command == "materialize":
            materializer = FixtureMaterializer(
                contract,
                repository=repository,
                afterfx_path=args.afterfx_path,
            )
            result = materializer.materialize_one(
                args.fixture_id,
                timeout=args.timeout,
                acknowledge_disposable_project=_acknowledged(args),
            )
            _print(result)
            return 0

        if args.command == "materialize-all":
            materializer = FixtureMaterializer(
                contract,
                repository=repository,
                afterfx_path=args.afterfx_path,
            )
            results = materializer.materialize_all(
                timeout=args.timeout,
                acknowledge_disposable_project=_acknowledged(args),
            )
            _print({
                "status": "CERTIFIED" if len(results) == len(contract.fixtures) else "INCOMPLETE",
                "fixture_count": len(results),
                "fixtures": results,
            })
            return 0 if len(results) == len(contract.fixtures) else 2

        if args.command == "status":
            _print(repository.status())
            return 0

        if args.command == "verify-canonical":
            _print(repository.verify_canonical(args.fixture_id))
            return 0

        if args.command == "create-run-copy":
            _print(repository.create_run_copy(args.fixture_id, args.run_id))
            return 0

        if args.command == "remove-run-copy":
            repository.remove_run_copy(args.run_id)
            _print({"status": "REMOVED", "run_id": args.run_id})
            return 0

        return 2

    except (
        FixtureSpecError,
        FixtureBuildError,
        FixtureCertificationError,
        RuntimeError,
        ValueError,
    ) as exc:
        _print({"status": "ERROR", "error": str(exc)})
        return 2


if __name__ == "__main__":
    sys.exit(main())
