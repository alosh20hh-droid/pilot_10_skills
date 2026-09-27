"""Load and validate the pilot verification contract."""

from __future__ import annotations

from dataclasses import dataclass
import math
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

        if self.raw.get("format_version") != "1.2":
            errors.append("unsupported pilot format_version")

        expected_skill_ids = {f"AE-PILOT-{index:03d}" for index in range(1, 11)}
        if set(self.skills) != expected_skill_ids:
            missing = sorted(expected_skill_ids - set(self.skills))
            extra = sorted(set(self.skills) - expected_skill_ids)
            if missing:
                errors.append("pilot is missing baseline skills: " + ", ".join(missing))
            if extra:
                errors.append("pilot has unexpected baseline skill ids: " + ", ".join(extra))
        if len(self.fixtures) != 10:
            errors.append("format 1.2 baseline requires exactly 10 fixture specifications")

        pilot = self.raw.get("pilot") or {}
        if pilot.get("execution_mode") != "UI_ONLY":
            errors.append("pilot execution_mode must remain UI_ONLY")
        if pilot.get("source_of_truth_for_success") != "AE_READER":
            errors.append("pilot source_of_truth_for_success must remain AE_READER")
        if pilot.get("isolation_model") != "ONE_SKILL_ONE_FRESH_FIXTURE":
            errors.append("pilot isolation model must remain one-skill-one-fresh-fixture")
        if self.required_repetitions != 3:
            errors.append("format 1.2 baseline requires exactly 3 repetitions per skill")

        expected_environment = {
            "operating_system": "Windows",
        }
        for key, expected in expected_environment.items():
            if self.environment_contract.get(key) != expected:
                errors.append(f"environment_contract.{key} must be {expected!r}")

        display = self.environment_contract.get("display") or {}
        if display.get("required_resolution") != "1920x1080":
            errors.append("environment_contract.display.required_resolution must be 1920x1080")
        if display.get("required_scaling_percent") != 100:
            errors.append("environment_contract.display.required_scaling_percent must be 100")

        ae_environment = self.environment_contract.get("after_effects") or {}
        if ae_environment.get("required_major_version") != 26:
            errors.append("environment_contract.after_effects.required_major_version must be 26")
        if ae_environment.get("required_language") != "en-US":
            errors.append("environment_contract.after_effects.required_language must be en-US")
        if ae_environment.get("required_workspace_id") != "PILOT_WORKSPACE":
            errors.append("environment_contract.after_effects.required_workspace_id must be PILOT_WORKSPACE")
        if ae_environment.get("exact_build_policy") != "record_and_pin_for_pilot_batch":
            errors.append("environment_contract.after_effects.exact_build_policy must remain record_and_pin_for_pilot_batch")

        run_identity = self.environment_contract.get("run_identity") or {}
        for identity_flag in (
            "require_unique_run_id",
            "require_start_timestamp",
            "require_fixture_id",
            "require_fixture_path",
            "require_request_id",
        ):
            if run_identity.get(identity_flag) is not True:
                errors.append(f"environment_contract.run_identity.{identity_flag} must be true")

        policy = self.comparison_policy
        numeric_tolerance_keys = (
            "default_numeric_absolute_tolerance",
            "percent_absolute_tolerance",
            "pixel_absolute_tolerance",
            "duration_seconds_absolute_tolerance",
            "frame_rate_absolute_tolerance",
        )
        for tolerance_key in numeric_tolerance_keys:
            value = policy.get(tolerance_key)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or float(value) < 0
            ):
                errors.append(f"comparison_policy.{tolerance_key} must be a finite non-negative number")
        keyframe_policy = policy.get("keyframe_time_policy") or {}
        if keyframe_policy.get("primary_unit") != "frame":
            errors.append("comparison_policy.keyframe_time_policy.primary_unit must be frame")
        frame_tolerance = keyframe_policy.get("frame_tolerance")
        if not isinstance(frame_tolerance, int) or isinstance(frame_tolerance, bool) or frame_tolerance < 0:
            errors.append("comparison_policy.keyframe_time_policy.frame_tolerance must be a non-negative integer")
        seconds_tolerance = keyframe_policy.get("secondary_seconds_tolerance")
        if (
            isinstance(seconds_tolerance, bool)
            or not isinstance(seconds_tolerance, (int, float))
            or not math.isfinite(float(seconds_tolerance))
            or float(seconds_tolerance) < 0
        ):
            errors.append("comparison_policy.keyframe_time_policy.secondary_seconds_tolerance must be finite and non-negative")

        if not isinstance(self.ae_reader_contract.get("expected_reader_version"), str):
            errors.append("ae_reader_contract.expected_reader_version is required")
        if not isinstance(self.ae_reader_contract.get("expected_schema_version"), int):
            errors.append("ae_reader_contract.expected_schema_version is required")

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

        known_capability_list = self.ae_reader_contract.get("known_capability_ids") or []
        if not isinstance(known_capability_list, list) or not all(
            isinstance(item, str) and item for item in known_capability_list
        ):
            errors.append("ae_reader_contract.known_capability_ids must be a list of non-empty strings")
            known_capabilities = set()
        else:
            known_capabilities = set(known_capability_list)
            if len(known_capabilities) != len(known_capability_list):
                errors.append("ae_reader_contract.known_capability_ids contains duplicates")
        if "project.file_identity" not in known_capabilities:
            errors.append("ae_reader_contract must include project.file_identity")

        used_fixtures: List[str] = []
        for skill_id, skill in self.skills.items():
            if skill.get("independent") is not True:
                errors.append(f"{skill_id} must be marked independent")

            goal = skill.get("goal")
            if not isinstance(goal, str) or not goal.strip():
                errors.append(f"{skill_id} is missing a non-empty goal")
            measured_steps = skill.get("measured_ui_steps")
            if not isinstance(measured_steps, list) or not measured_steps or not all(
                isinstance(step, str) and step.strip() for step in measured_steps
            ):
                errors.append(f"{skill_id} measured_ui_steps must be a non-empty list of strings")

            fixture_id = skill.get("fixture_id")
            used_fixtures.append(str(fixture_id))
            if fixture_id not in self.fixtures:
                errors.append(f"{skill_id} references unknown fixture {fixture_id!r}")

            required_caps = skill.get("required_reader_capabilities") or []
            if not isinstance(required_caps, list) or not all(isinstance(item, str) and item for item in required_caps):
                errors.append(f"{skill_id} has invalid required_reader_capabilities")
            else:
                if len(set(required_caps)) != len(required_caps):
                    errors.append(f"{skill_id} has duplicate required_reader_capabilities")
                unknown_caps = sorted(set(required_caps) - known_capabilities)
                if unknown_caps:
                    errors.append(
                        f"{skill_id} references unknown reader capabilities: "
                        + ", ".join(unknown_caps)
                    )

            preferred_caps = skill.get("preferred_reader_capabilities") or []
            if not isinstance(preferred_caps, list) or not all(isinstance(item, str) and item for item in preferred_caps):
                errors.append(f"{skill_id} has invalid preferred_reader_capabilities")
            else:
                unknown_preferred = sorted(set(preferred_caps) - known_capabilities)
                if unknown_preferred:
                    errors.append(
                        f"{skill_id} references unknown preferred reader capabilities: "
                        + ", ".join(unknown_preferred)
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

                    required_for_assertion = set()
                    if isinstance(path, str):
                        if path == "project.composition_count":
                            required_for_assertion.add("project.composition_count")
                        if path.startswith("active_comp."):
                            if path.endswith(".name"):
                                required_for_assertion.add("composition.identity")
                            if path.endswith(".width") or path.endswith(".height"):
                                required_for_assertion.add("composition.dimensions")
                            if path.endswith(".duration_seconds"):
                                required_for_assertion.add("composition.duration")
                            if path.endswith(".frame_rate"):
                                required_for_assertion.add("composition.frame_rate")
                            if (
                                path.endswith(".current_time_seconds")
                                or path.endswith(".current_time_frame")
                            ):
                                required_for_assertion.add("composition.current_time")

                        if path == "layers" or path.startswith("layers[") or path.startswith("layer["):
                            required_for_assertion.add("layer.list")
                        if path.startswith("layer["):
                            required_for_assertion.add("layer.identity")
                        if ".type" in path:
                            required_for_assertion.add("layer.type")
                        if ".source_text" in path:
                            required_for_assertion.add("layer.source_text")
                        if ".index" in path and (
                            path.startswith("layer[") or path.startswith("layers[")
                        ):
                            required_for_assertion.add("layer.index")
                        if any(
                            token in path
                            for token in (".in_seconds", ".out_seconds", ".start_seconds")
                        ):
                            required_for_assertion.add("layer.timing")
                        if ".transform.position." in path:
                            required_for_assertion.add("layer.transform.position")
                        if ".transform.scale." in path:
                            required_for_assertion.add("layer.transform.scale")
                        if ".transform.opacity_percent" in path:
                            required_for_assertion.add("layer.transform.opacity")
                        if ".properties.opacity.keyframe_count" in path:
                            required_for_assertion.add("property.keyframes.count")
                        if ".properties.opacity.keyframes" in path:
                            if op == "contains_keyframe":
                                if assertion.get("frame") is not None or assertion.get("time_seconds") is not None:
                                    required_for_assertion.add("property.keyframes.time")
                                if assertion.get("value") is not None:
                                    required_for_assertion.add("property.keyframes.value")

                        if path == "layers":
                            if op in {"contains_layer", "not_contains_layer_name", "count_layer_name"}:
                                required_for_assertion.add("layer.identity")
                            if op == "contains_layer":
                                if "type" in assertion:
                                    required_for_assertion.add("layer.type")
                                if "source_text" in assertion:
                                    required_for_assertion.add("layer.source_text")

                        if ".effects" in path or path.endswith(".effects"):
                            required_for_assertion.add("effect.list")
                        if "stable_id" in path or op == "contains_effect_stable_id":
                            required_for_assertion.add("effect.identity.stable_id")
                        if ".property[" in path:
                            required_for_assertion.add("effect.property.identity")
                        if ".effects" in path and path.endswith(".value"):
                            required_for_assertion.add("effect.property.value")
                    missing_assertion_caps = sorted(
                        required_for_assertion - set(required_caps if isinstance(required_caps, list) else [])
                    )
                    if missing_assertion_caps:
                        errors.append(
                            f"{skill_id} {phase}[{index}] requires undeclared reader capabilities: "
                            + ", ".join(missing_assertion_caps)
                        )

        if len(used_fixtures) != len(set(used_fixtures)):
            errors.append("each skill must use a distinct fixture in the baseline pilot")

        for fixture_id, fixture in self.fixtures.items():
            if not isinstance(fixture.get("required_state"), dict):
                errors.append(f"{fixture_id} is missing required_state")

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
