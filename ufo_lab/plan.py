"""Compile pilot skills into UFO Follower Mode plans."""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

from verifier.contract import PilotContract


class UFOPlanError(ValueError):
    pass


FORBIDDEN_STEP_TERMS = (
    "extendscript",
    "script api",
    "scripting api",
    "com automation",
    "powershell",
    "command prompt",
    "cmd.exe",
    "terminal",
    "shell command",
    "direct .aep",
    "modify the .aep",
)

UI_ONLY_SUFFIX = (
    "Use only visible Adobe After Effects UI interactions. "
    "Do not use scripts, expressions, COM, application APIs, shell/terminal commands, "
    "or direct project-file mutation."
)


@dataclass(frozen=True)
class CompiledUFOPlan:
    skill_id: str
    fixture_id: str
    task: str
    object_name: str
    steps: List[str]
    source_steps: List[str]
    plan_sha256: str

    def to_ufo_dict(self) -> Dict[str, Any]:
        return {
            "task": self.task,
            "steps": list(self.steps),
            "object": self.object_name,
        }

    def to_manifest_dict(self) -> Dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            "fixture_id": self.fixture_id,
            "task": self.task,
            "object": self.object_name,
            "source_steps": list(self.source_steps),
            "compiled_steps": list(self.steps),
            "plan_sha256": self.plan_sha256,
            "execution_mode": "follower",
            "success_oracle": "external_deterministic_verifier",
            "ufo_finish_is_not_success": True,
        }


def _hash_plan(plan: Dict[str, Any]) -> str:
    encoded = json.dumps(
        plan,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_source_step(skill_id: str, step: Any, index: int) -> str:
    if not isinstance(step, str) or not step.strip():
        raise UFOPlanError(f"{skill_id}: measured_ui_steps[{index}] must be a non-empty string")
    normalized = step.lower()
    for term in FORBIDDEN_STEP_TERMS:
        if term in normalized:
            raise UFOPlanError(
                f"{skill_id}: measured UI step contains forbidden non-UI execution term: {term}"
            )
    return step.strip()


def compile_skill_plan(
    contract: PilotContract,
    skill_id: str,
    *,
    object_name: str = "Adobe After Effects",
) -> CompiledUFOPlan:
    skill = contract.skill(skill_id)

    if skill.get("independent") is not True:
        raise UFOPlanError(f"{skill_id}: skill must be independent")
    if not isinstance(object_name, str) or not object_name.strip():
        raise UFOPlanError("UFO object/application name must be a non-empty string")

    source_steps_raw = skill.get("measured_ui_steps")
    if not isinstance(source_steps_raw, list) or not source_steps_raw:
        raise UFOPlanError(f"{skill_id}: measured_ui_steps must be a non-empty list")

    source_steps = [
        _validate_source_step(skill_id, step, index)
        for index, step in enumerate(source_steps_raw)
    ]

    goal = skill.get("goal")
    if not isinstance(goal, str) or not goal.strip():
        raise UFOPlanError(f"{skill_id}: goal must be a non-empty string")

    compiled_steps = [
        f"{index + 1}. {step} {UI_ONLY_SUFFIX}"
        for index, step in enumerate(source_steps)
    ]

    task = (
        f"{goal.strip()} "
        "Follow the supplied steps exactly in order using only the visible Adobe After Effects UI. "
        "Completion reported by UFO is execution evidence only; an external verifier decides success."
    )

    ufo_plan = {
        "task": task,
        "steps": compiled_steps,
        "object": object_name.strip(),
    }

    return CompiledUFOPlan(
        skill_id=skill_id,
        fixture_id=str(skill["fixture_id"]),
        task=task,
        object_name=object_name.strip(),
        steps=compiled_steps,
        source_steps=copy.deepcopy(source_steps),
        plan_sha256=_hash_plan(ufo_plan),
    )


def compile_all_plans(
    contract: PilotContract,
    *,
    object_name: str = "Adobe After Effects",
) -> List[CompiledUFOPlan]:
    return [
        compile_skill_plan(contract, skill_id, object_name=object_name)
        for skill_id in contract.skills
    ]


def write_compiled_plan(
    compiled: CompiledUFOPlan,
    output_path: str | Path,
    *,
    manifest_path: str | Path | None = None,
) -> Dict[str, str]:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    payload = json.dumps(
        compiled.to_ufo_dict(),
        ensure_ascii=False,
        indent=2,
    ) + "\n"
    output.write_text(payload, encoding="utf-8")

    actual_hash = hashlib.sha256(
        json.dumps(
            compiled.to_ufo_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    if actual_hash != compiled.plan_sha256:
        raise UFOPlanError("written UFO plan hash differs from compiled plan hash")

    manifest = Path(manifest_path) if manifest_path is not None else output.with_suffix(".manifest.json")
    manifest.write_text(
        json.dumps(compiled.to_manifest_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    return {
        "plan_path": str(output.resolve()),
        "manifest_path": str(manifest.resolve()),
        "plan_sha256": compiled.plan_sha256,
    }
