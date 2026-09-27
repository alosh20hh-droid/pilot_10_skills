"""Compile the canonical fixture specifications into deterministic build plans."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Dict, List

from verifier.contract import PilotContract


class FixtureSpecError(ValueError):
    pass


@dataclass(frozen=True)
class FixtureBuildPlan:
    fixture_id: str
    required_state: Dict[str, Any]

    def to_request(self, output_path: str) -> Dict[str, Any]:
        return {
            "fixture_id": self.fixture_id,
            "lab_mode": "DISPOSABLE_FIXTURE_BUILD",
            "output_path": output_path,
            "required_state": copy.deepcopy(self.required_state),
        }


def _validate_layer(fixture_id: str, layer: Dict[str, Any], expected_index: int) -> None:
    if not isinstance(layer, dict):
        raise FixtureSpecError(f"{fixture_id}: every layer spec must be an object")

    layer_type = layer.get("type")
    if layer_type != "text":
        raise FixtureSpecError(
            f"{fixture_id}: baseline builder currently supports only text layers, got {layer_type!r}"
        )

    if not isinstance(layer.get("name"), str) or not layer["name"]:
        raise FixtureSpecError(f"{fixture_id}: layer name is required")
    if not isinstance(layer.get("source_text"), str):
        raise FixtureSpecError(f"{fixture_id}: text layer requires source_text")

    declared_index = layer.get("index")
    if declared_index is not None and declared_index != expected_index:
        raise FixtureSpecError(
            f"{fixture_id}: layer order/index mismatch at expected index {expected_index}"
        )

    properties = layer.get("properties") or {}
    opacity = properties.get("opacity") or {}
    if opacity:
        count = opacity.get("keyframe_count")
        keys = opacity.get("keyframes")
        if count not in (None, 0) or keys not in (None, []):
            raise FixtureSpecError(
                f"{fixture_id}: canonical fixtures must not contain measured keyframes"
            )

    effects = layer.get("effects")
    if effects not in (None, []):
        raise FixtureSpecError(
            f"{fixture_id}: canonical fixtures must not pre-install measured effects"
        )


def compile_fixture_plan(contract: PilotContract, fixture_id: str) -> FixtureBuildPlan:
    try:
        fixture = contract.fixtures[fixture_id]
    except KeyError as exc:
        raise FixtureSpecError(f"unknown fixture id: {fixture_id}") from exc

    required_state = copy.deepcopy(fixture.get("required_state"))
    if not isinstance(required_state, dict):
        raise FixtureSpecError(f"{fixture_id}: required_state must be an object")

    project = required_state.get("project")
    layers = required_state.get("layers")
    if not isinstance(project, dict) or not isinstance(layers, list):
        raise FixtureSpecError(f"{fixture_id}: project and layers are required")

    composition_count = project.get("composition_count")
    if composition_count not in (0, 1):
        raise FixtureSpecError(
            f"{fixture_id}: baseline builder supports composition_count 0 or 1"
        )

    active_comp = required_state.get("active_comp")
    if composition_count == 0:
        if active_comp is not None or layers:
            raise FixtureSpecError(
                f"{fixture_id}: empty project cannot declare active_comp or layers"
            )
        return FixtureBuildPlan(fixture_id, required_state)

    if not isinstance(active_comp, dict):
        raise FixtureSpecError(
            f"{fixture_id}: composition_count=1 requires active_comp"
        )

    required_comp_fields = (
        "name",
        "width",
        "height",
        "duration_seconds",
        "frame_rate",
    )
    missing = [field for field in required_comp_fields if field not in active_comp]
    if missing:
        raise FixtureSpecError(
            f"{fixture_id}: active_comp missing fields: {', '.join(missing)}"
        )

    if not isinstance(active_comp["name"], str) or not active_comp["name"]:
        raise FixtureSpecError(f"{fixture_id}: active composition name is invalid")
    for field in ("width", "height", "duration_seconds", "frame_rate"):
        value = active_comp[field]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            raise FixtureSpecError(f"{fixture_id}: active_comp.{field} must be positive")

    for expected_index, layer in enumerate(layers, start=1):
        _validate_layer(fixture_id, layer, expected_index)

    return FixtureBuildPlan(fixture_id, required_state)


def compile_all_fixture_plans(contract: PilotContract) -> List[FixtureBuildPlan]:
    return [
        compile_fixture_plan(contract, fixture_id)
        for fixture_id in contract.fixtures
    ]
