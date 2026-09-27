"""Compile pilot skills into UFO Follower Mode plans."""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from typing import Any, Dict, List

from verifier.contract import PilotContract


class UFOPlanError(ValueError):
    pass


@dataclass(frozen=True)
class UFOPlan:
    skill_id: str
    fixture_id: str
    payload: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return copy.deepcopy(self.payload)

    def sha256(self) -> str:
        encoded = json.dumps(
            self.payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


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
    if not isinstance(steps, list) or not steps or not all(
        isinstance(step, str) and step.strip() for step in steps
    ):
        raise UFOPlanError(f"{skill_id} measured_ui_steps are invalid")

    # Preserve the authored measured UI steps verbatim. The compiler is not
    # allowed to invent extra actions, hidden APIs, scripts, or recovery steps.
    payload = {
        "task": goal,
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
