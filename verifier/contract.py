"""Load and validate the pilot verification contract."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from .assertions import SUPPORTED_OPERATORS


class ContractError(ValueError):
    pass


@dataclass(frozen=True)
class PilotContract:
    raw: Dict[str, Any]
    skills: Dict[str, Dict[str, Any]]
    fixtures: Dict[str, Dict[str, Any]]
    comparison_policy: Dict[str, Any]
    environment_contract: Dict[str, Any]
    ae_reader_contract: Dict[str, Any]
    required_repetitions: int

    @classmethod
    def load(cls, path: str | Path) -> "PilotContract":
        contract_path = Path(path)
        try:
            raw = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            raise ContractError(f"unable to load pilot contract: {exc}") from exc

        if not isinstance(raw, dict):
            raise ContractError("pilot contract root must be an object")

        skills_raw = raw.get("skills")
        fixtures_raw = raw.get("fixture_specs")
        if not isinstance(skills_raw, list) or not isinstance(fixtures_raw, list):
            raise ContractError("pilot contract requires skills and fixture_specs lists")

        skills: Dict[str, Dict[str, Any]] = {}
        for skill in skills_raw:
            if not isinstance(skill, dict) or not isinstance(skill.get("id"), str):
                raise ContractError("every skill requires a string id")
            if skill["id"] in skills:
                raise ContractError(f"duplicate skill id: {skill['id']}")
            skills[skill["id"]] = skill

        fixtures: Dict[str, Dict[str, Any]] = {}
        for fixture in fixtures_raw:
            if not isinstance(fixture, dict) or not isinstance(fixture.get("id"), str):
                raise ContractError("every fixture requires a string id")
            if fixture["id"] in fixtures:
                raise ContractError(f"duplicate fixture id: {fixture['id']}")
            fixtures[fixture["id"]] = fixture

        repetitions = ((raw.get("pilot") or {}).get("required_repetitions_per_skill"))
        if not isinstance(repetitions, int) or isinstance(repetitions, bool) or repetitions < 1:
            raise ContractError("required_repetitions_per_skill must be a positive integer")

        contract = cls(
            raw=raw,
            skills=skills,
            fixtures=fixtures,
            comparison_policy=dict(raw.get("comparison_policy") or {}),
            environment_contract=dict(raw.get("environment_contract") or {}),
            ae_reader_contract=dict(raw.get("ae_reader_contract") or {}),
            required_repetitions=repetitions,
        )
        errors = contract.validate()
        if errors:
            raise ContractError("; ".join(errors))
        return contract

    def validate(self) -> List[str]:
        errors: List[str] = []

        declared_ops = (
            ((self.raw.get("assertion_operator_contract") or {}).get("supported"))
            or []
        )
        if set(declared_ops) != SUPPORTED_OPERATORS:
            missing = sorted(SUPPORTED_OPERATORS - set(declared_ops))
            extra = sorted(set(declared_ops) - SUPPORTED_OPERATORS)
            if missing:
                errors.append("pilot omits verifier operators: " + ", ".join(missing))
            if extra:
                errors.append("pilot declares unsupported operators: " + ", ".join(extra))

        known_capabilities = set(
            self.ae_reader_contract.get("known_capability_ids") or []
        )

        for skill_id, skill in self.skills.items():
            fixture_id = skill.get("fixture_id")
            if fixture_id not in self.fixtures:
                errors.append(f"{skill_id} references unknown fixture {fixture_id!r}")

            required_caps = skill.get("required_reader_capabilities") or []
            if not isinstance(required_caps, list) or not all(isinstance(item, str) for item in required_caps):
                errors.append(f"{skill_id} has invalid required_reader_capabilities")
            else:
                unknown_caps = sorted(set(required_caps) - known_capabilities)
                if unknown_caps:
                    errors.append(
                        f"{skill_id} references unknown reader capabilities: "
                        + ", ".join(unknown_caps)
                    )

            assertions = skill.get("assertions")
            if not isinstance(assertions, dict):
                errors.append(f"{skill_id} is missing assertions")
                continue

            for phase in ("pre", "post"):
                phase_assertions = assertions.get(phase)
                if not isinstance(phase_assertions, list):
                    errors.append(f"{skill_id} assertions.{phase} must be a list")
                    continue
                for index, assertion in enumerate(phase_assertions):
                    if not isinstance(assertion, dict):
                        errors.append(f"{skill_id} {phase}[{index}] must be an object")
                        continue
                    path = assertion.get("path")
                    op = assertion.get("op")
                    if not isinstance(path, str) or not path:
                        errors.append(f"{skill_id} {phase}[{index}] missing path")
                    if op not in SUPPORTED_OPERATORS:
                        errors.append(
                            f"{skill_id} {phase}[{index}] unsupported operator {op!r}"
                        )

        status_model = self.raw.get("status_model") or {}
        allowed_runs = set(((status_model.get("run_status") or {}).get("allowed")) or [])
        expected_runs = {
            "PASS",
            "UI_CHANGED",
            "EXECUTION_FAILED",
            "VERIFICATION_FAILED",
            "BLOCKED",
            "INCONCLUSIVE",
        }
        if allowed_runs != expected_runs:
            errors.append("run status contract differs from verifier status model")

        allowed_skills = set(((status_model.get("skill_status") or {}).get("allowed")) or [])
        expected_skills = {"VERIFIED", "NOT_VERIFIED", "NEEDS_REVIEW"}
        if allowed_skills != expected_skills:
            errors.append("skill status contract differs from verifier status model")

        return errors

    def skill(self, skill_id: str) -> Dict[str, Any]:
        try:
            return self.skills[skill_id]
        except KeyError as exc:
            raise ContractError(f"unknown skill id: {skill_id}") from exc

    def fixture_for_skill(self, skill_id: str) -> Dict[str, Any]:
        skill = self.skill(skill_id)
        fixture_id = skill["fixture_id"]
        return self.fixtures[fixture_id]

    def required_capabilities(self, skill_id: str) -> List[str]:
        return list(self.skill(skill_id).get("required_reader_capabilities") or [])

    def pre_assertions(self, skill_id: str) -> List[Dict[str, Any]]:
        return list((self.skill(skill_id).get("assertions") or {}).get("pre") or [])

    def post_assertions(self, skill_id: str) -> List[Dict[str, Any]]:
        return list((self.skill(skill_id).get("assertions") or {}).get("post") or [])

    def runtime_calibration_requirements(self, skill_id: str) -> Dict[str, Any]:
        skill = self.skill(skill_id)
        calibration = skill.get("runtime_calibration")
        return dict(calibration) if isinstance(calibration, dict) else {}

    def expected_reader_version(self) -> Optional[str]:
        value = self.ae_reader_contract.get("expected_reader_version")
        return value if isinstance(value, str) else None

    def expected_reader_schema_version(self) -> Optional[int]:
        value = self.ae_reader_contract.get("expected_schema_version")
        return value if isinstance(value, int) and not isinstance(value, bool) else None
