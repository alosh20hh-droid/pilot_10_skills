"""Compile pilot skills into UFO Follower Mode plans."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass
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


def _validate_source_step(skill_id: str, step: str) -> None:
    if not isinstance(step, str) or not step.strip():
        raise UFOPlanError(f"{skill_id}: measured UI step must be a non-empty string")
    for pattern in _FORBIDDEN_SOURCE_PATTERNS:
        if re.search(pattern, step, re.IGNORECASE):
            raise UFOPlanError(
                f"{skill_id}: measured UI step contains prohibited execution route: {step!r}"
            )
    if _ABSOLUTE_COORDINATE_ONLY.search(step):
        raise UFOPlanError(
            f"{skill_id}: absolute screen coordinates cannot be the sole control locator"
        )


@dataclass(frozen=True)
class UFOPlan:
    skill_id: str
    fixture_id: str
    payload: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return copy.deepcopy(self.payload)

    def serialized_bytes(self) -> bytes:
        return (
            json.dumps(
                self.payload,
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
            )
            + "\n"
        ).encode("utf-8")

    def sha256(self) -> str:
        return hashlib.sha256(self.serialized_bytes()).hexdigest()

    def bind_object(self, object_value: str) -> "UFOPlan":
        if not isinstance(object_value, str) or not object_value.strip():
            raise UFOPlanError("bound UFO object must be a non-empty string")
        payload = self.to_dict()
        payload["object"] = object_value
        return UFOPlan(
            skill_id=self.skill_id,
            fixture_id=self.fixture_id,
            payload=payload,
        )


def compile_skill_plan(contract: PilotContract, skill_id: str) -> UFOPlan:
    skill = contract.skill(skill_id)

    pilot = contract.raw.get("pilot") or {}
    if pilot.get("execution_mode") != "UI_ONLY":
        raise UFOPlanError("UFO plan compilation requires UI_ONLY pilot mode")

    if skill.get("independent") is not True:
        raise UFOPlanError(f"{skill_id} must remain independent")

    fixture_id = skill.get("fixture_id")
    if fixture_id not in contract.fixtures:
        raise UFOPlanError(f"{skill_id} references unknown fixture")

    goal = skill.get("goal")
    steps = skill.get("measured_ui_steps")
    if not isinstance(goal, str) or not goal.strip():
        raise UFOPlanError(f"{skill_id} goal is missing")
    if not isinstance(steps, list) or not steps:
        raise UFOPlanError(f"{skill_id} measured_ui_steps are invalid")
    for step in steps:
        _validate_source_step(skill_id, step)

    # Preserve the authored measured UI steps verbatim. Add the execution
    # boundary only to the task instruction, never to the measured steps.
    guard = (
        "Operate only inside the already-open disposable Adobe After Effects fixture. "
        "Use visible UI interactions only. Prefer semantic controls, labels, UIA state, "
        "and relative targeting. Standard keyboard shortcuts are allowed. "
        "Do not use scripts, ExtendScript, expressions, shell commands, COM, "
        "application APIs, direct .aep mutation, or hidden automation. "
        "Do not decide whether the skill passed; stop after the declared UI steps. "
    )
    payload = {
        "task": guard + "Measured skill " + skill_id + ": " + goal.strip(),
        "steps": list(steps),
        "object": "AfterFX.exe",
        "close": False,
    }

    return UFOPlan(
        skill_id=skill_id,
        fixture_id=str(fixture_id),
        payload=payload,
    )


def compile_all_plans(contract: PilotContract) -> List[UFOPlan]:
    return [compile_skill_plan(contract, skill_id) for skill_id in contract.skills]
