"""Compile pilot skills into deterministic UFO Follower Mode plans."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

from verifier.contract import PilotContract


class UFOPlanError(ValueError):
    pass


_FORBIDDEN_SOURCE_PATTERNS = (
    r"extendscript",
    r"\.jsx\b",
    r"powershell",
    r"cmd\.exe",
    r"shell command",
    r"com automation",
    r"scripting api",
    r"direct \.aep",
    r"application api",
    r"expression\b",
)

_ABSOLUTE_COORDINATE_ONLY = re.compile(
    r"\b(?:click|drag|move)\b[^\n]*\b(?:at|from|to)\s*\(?\s*\d{2,4}\s*[,x]\s*\d{2,4}\s*\)?",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class CompiledUFOPlan:
    skill_id: str
    fixture_id: str
    task: str
    steps: List[str]
    object_name: str = "Adobe After Effects"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task": self.task,
            "steps": list(self.steps),
            "object": self.object_name,
            "close": False,
        }

    def canonical_json(self) -> str:
        return json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


def _validate_source_step(skill_id: str, step: str) -> None:
    if not isinstance(step, str) or not step.strip():
        raise UFOPlanError(f"{skill_id}: measured UI step must be a non-empty string")

    lowered = step.lower()
    for pattern in _FORBIDDEN_SOURCE_PATTERNS:
        if re.search(pattern, lowered, re.IGNORECASE):
            raise UFOPlanError(
                f"{skill_id}: measured UI step contains prohibited execution route: {step!r}"
            )

    if _ABSOLUTE_COORDINATE_ONLY.search(step):
        raise UFOPlanError(
            f"{skill_id}: absolute screen coordinates cannot be the sole control locator"
        )


def compile_skill_plan(contract: PilotContract, skill_id: str) -> CompiledUFOPlan:
    skill = contract.skill(skill_id)
    fixture_id = skill.get("fixture_id")
    goal = skill.get("goal")
    steps = skill.get("measured_ui_steps")

    if not isinstance(fixture_id, str) or not fixture_id:
        raise UFOPlanError(f"{skill_id}: fixture_id is required")
    if not isinstance(goal, str) or not goal.strip():
        raise UFOPlanError(f"{skill_id}: goal is required")
    if not isinstance(steps, list) or not steps:
        raise UFOPlanError(f"{skill_id}: measured_ui_steps must be a non-empty list")

    clean_steps: List[str] = []
    for index, step in enumerate(steps, start=1):
        _validate_source_step(skill_id, step)
        clean_steps.append(f"{index}. {step.strip()}")

    guard = (
        "Operate only inside the already-open disposable Adobe After Effects fixture. "
        "Use visible UI interactions only. Prefer semantic controls, labels, UIA state, "
        "and relative targeting. Standard keyboard shortcuts are allowed. "
        "Do not use scripts, ExtendScript, expressions, shell commands, MCP tools, COM, "
        "application APIs, direct .aep mutation, or hidden automation. "
        "Do not decide whether the skill passed; stop after the declared UI steps. "
    )

    task = f"{guard}Measured skill {skill_id}: {goal.strip()}"

    return CompiledUFOPlan(
        skill_id=skill_id,
        fixture_id=fixture_id,
        task=task,
        steps=clean_steps,
    )


def compile_all_skill_plans(contract: PilotContract) -> List[CompiledUFOPlan]:
    return [
        compile_skill_plan(contract, skill_id)
        for skill_id in contract.skills
    ]


def write_plan(plan: CompiledUFOPlan, output_path: str | Path) -> Dict[str, Any]:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.suffix.lower() != ".json":
        raise UFOPlanError("UFO follower plan output must use .json extension")

    payload = json.dumps(
        plan.to_dict(),
        ensure_ascii=False,
        indent=2,
    ) + "\n"

    temporary = output.with_suffix(".tmp")
    temporary.write_text(payload, encoding="utf-8")
    temporary.replace(output)

    return {
        "skill_id": plan.skill_id,
        "fixture_id": plan.fixture_id,
        "path": str(output.resolve()),
        "sha256": plan.sha256(),
    }


def write_all_plans(
    contract: PilotContract,
    output_dir: str | Path,
) -> List[Dict[str, Any]]:
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    results = []
    for plan in compile_all_skill_plans(contract):
        results.append(
            write_plan(
                plan,
                directory / f"{plan.skill_id}.json",
            )
        )
    return results
