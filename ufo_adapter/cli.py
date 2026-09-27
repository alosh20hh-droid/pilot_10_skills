"""Command-line interface for the UFO Step 04 adapter."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from verifier.contract import PilotContract

from .lock import UFOLockError, inspect_checkout
from .plan import UFOPlanError, compile_all_plans, compile_skill_plan
from .runner import UFOExecutionError, UFOMeasuredRunner


DEFAULT_CONTRACT = Path(__file__).resolve().parents[1] / "pilot_10_skills.yaml"


def _print(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))



def _resolve_ufo_checkout(value: str | None) -> str:
    candidates = []
    if value:
        candidates.append(Path(value).expanduser())
    env_root = os.environ.get("UFO_ROOT")
    if env_root:
        candidates.append(Path(env_root).expanduser())
    home = Path.home()
    candidates.extend([
        home / "UFO",
        home / "Desktop" / "UFO",
        home / "Documents" / "UFO",
    ])

    seen = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        key = str(resolved).lower()
        if key in seen:
            continue
        seen.add(key)
        if (resolved / "ufo" / "__main__.py").is_file():
            return str(resolved)

    raise UFOExecutionError(
        "existing UFO checkout was not found; pass --ufo-checkout or set UFO_ROOT"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="UFO adapter for the AE pilot")
    parser.add_argument("--contract", default=str(DEFAULT_CONTRACT))

    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("validate-plans", help="Compile and validate all ten Follower Mode plans")

    plan = sub.add_parser("plan", help="Print one generated UFO plan")
    plan.add_argument("--skill-id", required=True)

    compile_all = sub.add_parser("compile-all", help="Write all ten UFO plans to a directory")
    compile_all.add_argument("--output-dir", required=True)

    check = sub.add_parser("validate-checkout", help="Validate a local UFO checkout against the pinned upstream commit")
    check.add_argument("--ufo-checkout", default=None)

    command = sub.add_parser("command", help="Print the exact locked UFO command for one skill without executing it")
    command.add_argument("--ufo-checkout", default=None)
    command.add_argument("--skill-id", required=True)
    command.add_argument("--run-id", required=True)
    command.add_argument("--fixture-path", required=True)
    command.add_argument("--fixture-sha256", required=True)

    execute = sub.add_parser("execute", help="Run one measured UFO Follower Mode plan")
    execute.add_argument("--ufo-checkout", default=None)
    execute.add_argument("--skill-id", required=True)
    execute.add_argument("--run-id", required=True)
    execute.add_argument("--fixture-path", required=True)
    execute.add_argument("--fixture-sha256", required=True)
    execute.add_argument("--timeout", type=float, default=None)
    execute.add_argument(
        "--arm-measured-execution",
        action="store_true",
        help="Required safety acknowledgement before UFO is allowed to drive the UI",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        contract = PilotContract.load(args.contract)

        if args.command == "validate-plans":
            plans = compile_all_plans(contract)
            _print({
                "status": "PASS",
                "plan_count": len(plans),
                "mode": "follower",
                "object": "AfterFX.exe",
                "skill_ids": [plan.skill_id for plan in plans],
                "plan_hashes": {
                    plan.skill_id: plan.sha256()
                    for plan in plans
                },
            })
            return 0

        if args.command == "plan":
            plan = compile_skill_plan(contract, args.skill_id)
            _print({
                "skill_id": plan.skill_id,
                "fixture_id": plan.fixture_id,
                "sha256": plan.sha256(),
                "plan": plan.to_dict(),
            })
            return 0

        if args.command == "compile-all":
            output = Path(args.output_dir).expanduser().resolve()
            output.mkdir(parents=True, exist_ok=True)
            results = []
            for plan in compile_all_plans(contract):
                target = output / f"{plan.skill_id}.json"
                target.write_bytes(plan.serialized_bytes())
                results.append({
                    "skill_id": plan.skill_id,
                    "fixture_id": plan.fixture_id,
                    "path": str(target),
                    "sha256": plan.sha256(),
                })
            _print({"status": "PASS", "plans": results})
            return 0

        if args.command == "validate-checkout":
            result = inspect_checkout(_resolve_ufo_checkout(args.ufo_checkout))
            _print(result)
            return 0 if result["valid"] else 2

        if args.command == "command":
            plan = compile_skill_plan(contract, args.skill_id)
            runner = UFOMeasuredRunner(_resolve_ufo_checkout(args.ufo_checkout))
            checkout = runner.validate_environment()
            preview = runner.preview_command(
                run_id=args.run_id,
                plan=plan,
                fixture_path=args.fixture_path,
                fixture_sha256=args.fixture_sha256,
            )
            _print({
                "status": "READY",
                "checkout": checkout,
                "plan_sha256": preview["plan_sha256"],
                "future_plan_path": preview["plan_path"],
                "command": preview["command"],
                "note": "Preview only; no run directory was created and the run_id remains unused.",
            })
            return 0

        if args.command == "execute":
            plan = compile_skill_plan(contract, args.skill_id)
            runner = UFOMeasuredRunner(_resolve_ufo_checkout(args.ufo_checkout))
            result = runner.execute(
                run_id=args.run_id,
                plan=plan,
                fixture_path=args.fixture_path,
                fixture_sha256=args.fixture_sha256,
                arm_measured_execution=args.arm_measured_execution,
                timeout=args.timeout,
            )
            _print(result.to_dict())
            return 0 if result.process_exit_ok else 2

        return 2

    except (UFOPlanError, UFOLockError, UFOExecutionError, ValueError, OSError) as exc:
        _print({"status": "ERROR", "error": str(exc)})
        return 2


if __name__ == "__main__":
    sys.exit(main())
