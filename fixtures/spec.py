"""Compile the canonical fixture specifications into deterministic build plans."""

from __future__ import annotations

import copy
import math
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



def _finite_number(value: Any, field_name: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
    ):
        raise FixtureSpecError(f"{field_name} must be a finite number")
    return float(value)


def _optional_finite_number(value: Any, field_name: str) -> float | None:
    if value is None:
        return None
    return _finite_number(value, field_name)


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
    if declared_index is not None and (
        not isinstance(declared_index, int)
        or isinstance(declared_index, bool)
        or declared_index < 1
    ):
        raise FixtureSpecError(f"{fixture_id}: layer index must be a positive integer")
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

    for timing_field in ("in_seconds", "out_seconds", "start_seconds"):
        if timing_field in layer:
            _optional_finite_number(
                layer.get(timing_field),
                f"{fixture_id}: layer.{timing_field}",
            )

    transform = layer.get("transform") or {}
    if not isinstance(transform, dict):
        raise FixtureSpecError(f"{fixture_id}: layer transform must be an object")

    position = transform.get("position")
    if position is not None:
        if not isinstance(position, dict):
            raise FixtureSpecError(f"{fixture_id}: position must be an object")
        for axis in ("x", "y"):
            if axis not in position:
                raise FixtureSpecError(f"{fixture_id}: position.{axis} is required")
            _finite_number(position[axis], f"{fixture_id}: position.{axis}")

    scale = transform.get("scale")
    if scale is not None:
        if not isinstance(scale, dict):
            raise FixtureSpecError(f"{fixture_id}: scale must be an object")
        for axis in ("x_percent", "y_percent"):
            if axis not in scale:
                raise FixtureSpecError(f"{fixture_id}: scale.{axis} is required")
            _finite_number(scale[axis], f"{fixture_id}: scale.{axis}")

    if "opacity_percent" in transform:
        opacity_value = _finite_number(
            transform["opacity_percent"],
            f"{fixture_id}: opacity_percent",
        )
        if opacity_value < 0 or opacity_value > 100:
            raise FixtureSpecError(
                f"{fixture_id}: opacity_percent must be between 0 and 100"
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
        value = _finite_number(
            active_comp[field],
            f"{fixture_id}: active_comp.{field}",
        )
        if value <= 0:
            raise FixtureSpecError(f"{fixture_id}: active_comp.{field} must be positive")

    width = active_comp["width"]
    height = active_comp["height"]
    if (
        not isinstance(width, int)
        or isinstance(width, bool)
        or not isinstance(height, int)
        or isinstance(height, bool)
    ):
        raise FixtureSpecError(
            f"{fixture_id}: composition width/height must be integers"
        )

    current_seconds = active_comp.get("current_time_seconds")
    current_frame = active_comp.get("current_time_frame")
    if current_seconds is not None:
        current_seconds = _finite_number(
            current_seconds,
            f"{fixture_id}: active_comp.current_time_seconds",
        )
        if current_seconds < 0 or current_seconds > float(active_comp["duration_seconds"]):
            raise FixtureSpecError(
                f"{fixture_id}: active composition current time is outside its duration"
            )
    if current_frame is not None:
        if (
            not isinstance(current_frame, int)
            or isinstance(current_frame, bool)
            or current_frame < 0
        ):
            raise FixtureSpecError(
                f"{fixture_id}: active_comp.current_time_frame must be a non-negative integer"
            )
        max_frame = round(
            float(active_comp["duration_seconds"])
            * float(active_comp["frame_rate"])
        )
        if current_frame > max_frame:
            raise FixtureSpecError(
                f"{fixture_id}: active_comp.current_time_frame is outside its duration"
            )

    if current_seconds is not None and current_frame is not None:
        expected_frame = current_seconds * float(active_comp["frame_rate"])
        if abs(expected_frame - current_frame) > 0.000001:
            raise FixtureSpecError(
                f"{fixture_id}: active composition seconds/frame time disagree"
            )

    seen_names = set()
    duration = float(active_comp["duration_seconds"])
    for expected_index, layer in enumerate(layers, start=1):
        _validate_layer(fixture_id, layer, expected_index)
        name = layer["name"]
        if name in seen_names:
            raise FixtureSpecError(
                f"{fixture_id}: duplicate canonical layer name {name!r}"
            )
        seen_names.add(name)

        in_seconds = layer.get("in_seconds")
        out_seconds = layer.get("out_seconds")
        if in_seconds is not None and (
            float(in_seconds) < 0 or float(in_seconds) > duration
        ):
            raise FixtureSpecError(
                f"{fixture_id}: layer in_seconds is outside composition duration"
            )
        if out_seconds is not None and (
            float(out_seconds) < 0 or float(out_seconds) > duration
        ):
            raise FixtureSpecError(
                f"{fixture_id}: layer out_seconds is outside composition duration"
            )
        if (
            in_seconds is not None
            and out_seconds is not None
            and float(in_seconds) > float(out_seconds)
        ):
            raise FixtureSpecError(
                f"{fixture_id}: layer in_seconds cannot exceed out_seconds"
            )

    return FixtureBuildPlan(fixture_id, required_state)


def compile_all_fixture_plans(contract: PilotContract) -> List[FixtureBuildPlan]:
    return [
        compile_fixture_plan(contract, fixture_id)
        for fixture_id in contract.fixtures
    ]
