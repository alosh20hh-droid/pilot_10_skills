"""CLI for Step 04: Microsoft UFO² Follower execution layer."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any

from verifier.contract import PilotContract

from .installation import UFOInstallation, UFOInstallationError, UFOReferenceLock
from .launcher import UFOExecutionError, UFOFollowerExecutor
from .plan import UFOPlanError, compile_all_plans, compile_skill_plan, write_compiled_plan


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONTRACT = ROOT / "pilot_10_skills.yaml"
DEFAULT_LOCK = ROOT / "ufo_lab" / "UPSTREAM_UFO.lock.json"


def _print(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def _load(args: argparse.Namespace) -> tuple[PilotContract, UFOReferenceLock]:
    contract = PilotContract.load(args.contract)
    lock = UFOReferenceLock.load(args.lock)
    return contract, lock


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AE pilot UFO² integration")
    parser.add_argument("--contract", default=str(DEFAULT_CONTRACT))
    parser.add_argument("--lock", default=str(DEFAULT_LOCK))
    parser.add_argument("--ufo-root", default=None)

    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("validate-plans", help="Compile all ten skills into Follower plans")

    inspect = sub.add_parser("inspect", help="Inspect the existing local UFO checkout")
    inspect.add_argument("--allow-compatible-fork", action="store_true")

    plan = sub.add_parser("plan", help="Print one compiled Follower plan")
    plan.add_argument("--skill-id", required=True)

    compile_one = sub.add_parser("compile", help="Write one Follower plan + provenance manifest")
    compile_one.add_argument("--skill-id", required=True)
    compile_one.add_argument("--output", required=True)

    compile_all = sub.add_parser("compile-all", help="Write all ten Follower plans")
    compile_all.add_argument("--output-dir", required=True)

    execute = sub.add_parser("execute", help="Run one skill through existing UFO Follower Mode")
    execute.add_argument("--skill-id", required=True)
    execute.add_argument("--run-id", required=True)
    execute.add_argument("--timeout", type=float, default=900.0)
    execute.add_argument("--allow-compatible-fork", action="store_true")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        contract, lock = _load(args)

        if args.command == "validate-plans":
            plans = compile_all_plans(contract)
            _print(
                {
                    "status": "PASS",
                    "plan_count": len(plans),
                    "skills": [
                        {
                            "skill_id": plan.skill_id,
                            "fixture_id": plan.fixture_id,
                            "step_count": len(plan.steps),
                            "plan_sha256": plan.plan_sha256,
                        }
                        for plan in plans
                    ],
                }
            )
            return 0

        if args.command == "plan":
            plan = compile_skill_plan(contract, args.skill_id)
            _print(
                {
                    "ufo_plan": plan.to_ufo_dict(),
                    "manifest": plan.to_manifest_dict(),
                }
            )
            return 0

        if args.command == "compile":
            plan = compile_skill_plan(contract, args.skill_id)
            result = write_compiled_plan(plan, args.output)
            _print({"status": "COMPILED", **result})
            return 0

        if args.command == "compile-all":
            output_dir = Path(args.output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)
            written = []
            for plan in compile_all_plans(contract):
                output = output_dir / f"{plan.skill_id}.plan.json"
                written.append(
                    {
                        "skill_id": plan.skill_id,
                        **write_compiled_plan(plan, output),
                    }
                )
            _print({"status": "COMPILED", "plan_count": len(written), "plans": written})
            return 0

        installation = UFOInstallation.discover(lock, args.ufo_root)

        if args.command == "inspect":
            inspection = installation.inspect()
            launchable = False
            launch_error = None
            try:
                installation.require_launchable(
                    allow_compatible_fork=args.allow_compatible_fork,
                    require_clean_tree=True,
                )
            except UFOInstallationError as exc:
                launch_error = str(exc)
            else:
                launchable = True

            _print(
                {
                    "status": "PASS" if inspection.structurally_compatible else "FAIL",
                    "launchable": launchable,
                    "launch_error": launch_error,
                    "reference_commit": lock.reference_commit,
                    "inspection": inspection.to_dict(),
                }
            )
            return 0 if inspection.structurally_compatible else 2

        if args.command == "execute":
            executor = UFOFollowerExecutor(
                contract,
                lock,
                installation,
            )
            record = executor.execute(
                skill_id=args.skill_id,
                run_id=args.run_id,
                timeout=args.timeout,
                allow_compatible_fork=args.allow_compatible_fork,
            )
            _print(
                {
                    "status": "PROCESS_EXIT_ZERO" if record.process_exit_zero else "PROCESS_NONZERO",
                    "note": "This is not a skill PASS. Only the deterministic verifier can assign PASS.",
                    "execution": record.to_dict(),
                }
            )
            return 0 if record.process_exit_zero else 2

        return 2

    except (
        UFOInstallationError,
        UFOExecutionError,
        UFOPlanError,
        RuntimeError,
        ValueError,
    ) as exc:
        _print({"status": "ERROR", "error": str(exc)})
        return 2


if __name__ == "__main__":
    sys.exit(main())
