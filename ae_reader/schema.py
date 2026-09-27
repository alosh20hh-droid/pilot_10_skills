"""Typed, fail-closed data contract for the pilot After Effects reader."""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any, Dict, Iterable, List, Optional

READER_VERSION = "2.1.0"
SCHEMA_VERSION = 2


def _primitive(value: Any) -> Any:
    """Keep only JSON-compatible values; never expose host application objects."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (list, tuple)):
        return [_primitive(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _primitive(item) for key, item in value.items()}
    return None


def _number_or_none(value: Any, field_name: str) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"invalid {field_name}")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"non-finite {field_name}")
    return number


def _int_or_none(value: Any, field_name: str) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"invalid {field_name}")
    return value


@dataclass(frozen=True)
class AEReadRequest:
    request_id: str
    run_id: str
    requested_at: float
    session_id: Optional[str] = None
    lesson_id: Optional[str] = None
    step_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "request_id": self.request_id,
            "run_id": self.run_id,
            "requested_at": self.requested_at,
            "session_id": self.session_id,
            "lesson_id": self.lesson_id,
            "step_id": self.step_id,
        }


@dataclass(frozen=True)
class AECapabilityManifest:
    reader_version: str
    schema_version: int
    supported_capabilities: List[str]

    @classmethod
    def from_dict(cls, value: Any) -> "AECapabilityManifest":
        if not isinstance(value, dict):
            raise ValueError("invalid capability manifest")
        reader_version = value.get("reader_version")
        schema_version = value.get("schema_version")
        capabilities = value.get("supported_capabilities")
        if not isinstance(reader_version, str) or not reader_version:
            raise ValueError("invalid reader version")
        if not isinstance(schema_version, int) or isinstance(schema_version, bool):
            raise ValueError("invalid manifest schema version")
        if not isinstance(capabilities, list) or not all(isinstance(item, str) and item for item in capabilities):
            raise ValueError("invalid supported capabilities")
        if len(set(capabilities)) != len(capabilities):
            raise ValueError("duplicate capability id")
        return cls(reader_version, schema_version, list(capabilities))

    def supports(self, required: Iterable[str]) -> bool:
        available = set(self.supported_capabilities)
        return all(item in available for item in required)

    def missing(self, required: Iterable[str]) -> List[str]:
        available = set(self.supported_capabilities)
        return [item for item in required if item not in available]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "reader_version": self.reader_version,
            "schema_version": self.schema_version,
            "supported_capabilities": list(self.supported_capabilities),
        }


@dataclass(frozen=True)
class AEPropertyKey:
    index: int
    time_seconds: Optional[float]
    frame: Optional[int]
    value: Any

    @classmethod
    def from_dict(cls, value: Any) -> "AEPropertyKey":
        if not isinstance(value, dict):
            raise ValueError("invalid property key")
        index = value.get("index")
        if not isinstance(index, int) or isinstance(index, bool) or index < 1:
            raise ValueError("invalid property key index")
        return cls(
            index=index,
            time_seconds=_number_or_none(value.get("time_seconds"), "property key time"),
            frame=_int_or_none(value.get("frame"), "property key frame"),
            value=_primitive(value.get("value")),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "index": self.index,
            "time_seconds": self.time_seconds,
            "frame": self.frame,
            "value": _primitive(self.value),
        }


@dataclass(frozen=True)
class AEPropertySnapshot:
    available: bool
    name: Optional[str] = None
    match_name: Optional[str] = None
    num_keys: int = 0
    is_time_varying: bool = False
    current_value: Any = None
    keys: List[AEPropertyKey] = field(default_factory=list)

    @classmethod
    def from_dict(cls, value: Any) -> "AEPropertySnapshot":
        if not isinstance(value, dict) or not isinstance(value.get("available"), bool):
            raise ValueError("invalid property snapshot")
        num_keys = value.get("num_keys", 0)
        if not isinstance(num_keys, int) or isinstance(num_keys, bool) or num_keys < 0:
            raise ValueError("invalid property key count")
        varying = value.get("is_time_varying", False)
        if not isinstance(varying, bool):
            raise ValueError("invalid time-varying flag")
        keys_raw = value.get("keys") or []
        if not isinstance(keys_raw, list):
            raise ValueError("invalid property keys")
        keys = [AEPropertyKey.from_dict(item) for item in keys_raw]
        if value["available"] and len(keys) != num_keys:
            raise ValueError("property key count does not match keys")
        name = value.get("name")
        match_name = value.get("match_name")
        if name is not None and not isinstance(name, str):
            raise ValueError("invalid property name")
        if match_name is not None and not isinstance(match_name, str):
            raise ValueError("invalid property match name")
        return cls(
            available=value["available"],
            name=name,
            match_name=match_name,
            num_keys=num_keys,
            is_time_varying=varying,
            current_value=_primitive(value.get("current_value")),
            keys=keys,
        )

    @classmethod
    def unavailable(cls) -> "AEPropertySnapshot":
        return cls(False)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "available": self.available,
            "name": self.name,
            "match_name": self.match_name,
            "num_keys": self.num_keys,
            "is_time_varying": self.is_time_varying,
            "current_value": _primitive(self.current_value),
            "keys": [key.to_dict() for key in self.keys],
        }


@dataclass(frozen=True)
class AEPositionSnapshot:
    mode: str
    property: Optional[AEPropertySnapshot] = None
    separated: Dict[str, AEPropertySnapshot] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, value: Any) -> "AEPositionSnapshot":
        if not isinstance(value, dict) or value.get("mode") not in {"combined", "separated", "unavailable"}:
            raise ValueError("invalid position snapshot")
        prop = value.get("property")
        separated_raw = value.get("separated") or {}
        if not isinstance(separated_raw, dict):
            raise ValueError("invalid separated position")
        return cls(
            mode=value["mode"],
            property=AEPropertySnapshot.from_dict(prop) if isinstance(prop, dict) else None,
            separated={str(key): AEPropertySnapshot.from_dict(item) for key, item in separated_raw.items()},
        )

    @classmethod
    def unavailable(cls) -> "AEPositionSnapshot":
        return cls("unavailable")

    def current_xy(self) -> tuple[Optional[float], Optional[float]]:
        if self.mode == "combined" and self.property and isinstance(self.property.current_value, list):
            values = self.property.current_value
            x = float(values[0]) if len(values) > 0 and isinstance(values[0], (int, float)) else None
            y = float(values[1]) if len(values) > 1 and isinstance(values[1], (int, float)) else None
            return x, y
        if self.mode == "separated":
            x_prop = self.separated.get("ADBE Position_0")
            y_prop = self.separated.get("ADBE Position_1")
            x = float(x_prop.current_value) if x_prop and isinstance(x_prop.current_value, (int, float)) else None
            y = float(y_prop.current_value) if y_prop and isinstance(y_prop.current_value, (int, float)) else None
            return x, y
        return None, None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mode": self.mode,
            "property": self.property.to_dict() if self.property else None,
            "separated": {key: item.to_dict() for key, item in self.separated.items()},
        }


@dataclass(frozen=True)
class AEEffectPropertySnapshot:
    name: str
    match_name: str
    value: Any = None
    num_keys: int = 0
    keys: List[AEPropertyKey] = field(default_factory=list)
    properties: List["AEEffectPropertySnapshot"] = field(default_factory=list)

    @classmethod
    def from_dict(cls, value: Any) -> "AEEffectPropertySnapshot":
        if not isinstance(value, dict):
            raise ValueError("invalid effect property")
        name = value.get("name")
        match_name = value.get("match_name")
        if not isinstance(name, str) or not isinstance(match_name, str):
            raise ValueError("invalid effect property identity")
        num_keys = value.get("num_keys", 0)
        if not isinstance(num_keys, int) or isinstance(num_keys, bool) or num_keys < 0:
            raise ValueError("invalid effect property key count")
        keys_raw = value.get("keys") or []
        children_raw = value.get("properties") or []
        if not isinstance(keys_raw, list) or not isinstance(children_raw, list):
            raise ValueError("invalid effect property containers")
        keys = [AEPropertyKey.from_dict(item) for item in keys_raw]
        if len(keys) != num_keys:
            raise ValueError("effect property key count does not match keys")
        return cls(
            name=name,
            match_name=match_name,
            value=_primitive(value.get("value")),
            num_keys=num_keys,
            keys=keys,
            properties=[cls.from_dict(item) for item in children_raw],
        )

    def walk(self) -> Iterable["AEEffectPropertySnapshot"]:
        yield self
        for child in self.properties:
            yield from child.walk()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "match_name": self.match_name,
            "value": _primitive(self.value),
            "num_keys": self.num_keys,
            "keys": [key.to_dict() for key in self.keys],
            "properties": [item.to_dict() for item in self.properties],
        }


@dataclass(frozen=True)
class AEEffectSnapshot:
    name: str
    match_name: str
    enabled: bool
    properties: List[AEEffectPropertySnapshot] = field(default_factory=list)

    @classmethod
    def from_dict(cls, value: Any) -> "AEEffectSnapshot":
        if not isinstance(value, dict):
            raise ValueError("invalid effect snapshot")
        name = value.get("name")
        match_name = value.get("match_name")
        enabled = value.get("enabled")
        props = value.get("properties") or []
        if not isinstance(name, str) or not isinstance(match_name, str) or not isinstance(enabled, bool):
            raise ValueError("invalid effect identity")
        if not isinstance(props, list):
            raise ValueError("invalid effect properties")
        return cls(name, match_name, enabled, [AEEffectPropertySnapshot.from_dict(item) for item in props])

    def find_property(self, *, match_name: Optional[str] = None, name: Optional[str] = None) -> Optional[AEEffectPropertySnapshot]:
        for root in self.properties:
            for prop in root.walk():
                if match_name is not None and prop.match_name == match_name:
                    return prop
                if match_name is None and name is not None and prop.name == name:
                    return prop
        return None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "match_name": self.match_name,
            "enabled": self.enabled,
            "properties": [item.to_dict() for item in self.properties],
        }


@dataclass(frozen=True)
class AELayerSnapshot:
    index: int
    layer_id: Optional[int]
    name: str
    match_name: str
    layer_type: str
    selected: bool
    locked: bool
    enabled: bool
    source_text: Optional[str]
    in_seconds: Optional[float]
    out_seconds: Optional[float]
    start_seconds: Optional[float]
    position: AEPositionSnapshot
    opacity: AEPropertySnapshot
    scale: AEPropertySnapshot
    effects: List[AEEffectSnapshot] = field(default_factory=list)

    @classmethod
    def from_dict(cls, value: Any) -> "AELayerSnapshot":
        required = (
            "index", "layer_id", "name", "match_name", "layer_type", "selected",
            "locked", "enabled", "source_text", "in_seconds", "out_seconds",
            "start_seconds", "position", "opacity", "scale", "effects",
        )
        if not isinstance(value, dict) or any(key not in value for key in required):
            raise ValueError("invalid layer snapshot")
        index = value["index"]
        if not isinstance(index, int) or isinstance(index, bool) or index < 1:
            raise ValueError("invalid layer index")
        layer_id = _int_or_none(value.get("layer_id"), "layer id")
        if not all(isinstance(value[key], bool) for key in ("selected", "locked", "enabled")):
            raise ValueError("invalid layer flags")
        if not all(isinstance(value[key], str) for key in ("name", "match_name", "layer_type")):
            raise ValueError("invalid layer identity")
        source_text = value.get("source_text")
        if source_text is not None and not isinstance(source_text, str):
            raise ValueError("invalid source text")
        effects_raw = value.get("effects") or []
        if not isinstance(effects_raw, list):
            raise ValueError("invalid layer effects")
        return cls(
            index=index,
            layer_id=layer_id,
            name=value["name"],
            match_name=value["match_name"],
            layer_type=value["layer_type"],
            selected=value["selected"],
            locked=value["locked"],
            enabled=value["enabled"],
            source_text=source_text,
            in_seconds=_number_or_none(value.get("in_seconds"), "layer in point"),
            out_seconds=_number_or_none(value.get("out_seconds"), "layer out point"),
            start_seconds=_number_or_none(value.get("start_seconds"), "layer start time"),
            position=AEPositionSnapshot.from_dict(value["position"]),
            opacity=AEPropertySnapshot.from_dict(value["opacity"]),
            scale=AEPropertySnapshot.from_dict(value["scale"]),
            effects=[AEEffectSnapshot.from_dict(item) for item in effects_raw],
        )

    def to_pilot_dict(self) -> Dict[str, Any]:
        x, y = self.position.current_xy()
        scale_value = self.scale.current_value if isinstance(self.scale.current_value, list) else []
        scale_x = float(scale_value[0]) if len(scale_value) > 0 and isinstance(scale_value[0], (int, float)) else None
        scale_y = float(scale_value[1]) if len(scale_value) > 1 and isinstance(scale_value[1], (int, float)) else None
        opacity_value = self.opacity.current_value if isinstance(self.opacity.current_value, (int, float)) else None
        opacity_keys = [
            {"frame": key.frame, "time_seconds": key.time_seconds, "value": key.value}
            for key in self.opacity.keys
        ]
        effects = []
        for effect in self.effects:
            props = []
            for root in effect.properties:
                for prop in root.walk():
                    props.append({
                        "display_name": prop.name,
                        "stable_id": prop.match_name,
                        "value": _primitive(prop.value),
                        "keyframe_count": prop.num_keys,
                        "keyframes": [key.to_dict() for key in prop.keys],
                    })
            effects.append({
                "display_name": effect.name,
                "stable_id": effect.match_name,
                "enabled": effect.enabled,
                "properties": props,
            })
        return {
            "id": self.layer_id,
            "index": self.index,
            "name": self.name,
            "type": self.layer_type,
            "selected": self.selected,
            "source_text": self.source_text,
            "in_seconds": self.in_seconds,
            "out_seconds": self.out_seconds,
            "start_seconds": self.start_seconds,
            "transform": {
                "position": {"x": x, "y": y},
                "scale": {"x_percent": scale_x, "y_percent": scale_y},
                "opacity_percent": float(opacity_value) if opacity_value is not None else None,
            },
            "properties": {
                "opacity": {
                    "keyframe_count": self.opacity.num_keys,
                    "keyframes": opacity_keys,
                }
            },
            "effects": effects,
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "index": self.index,
            "layer_id": self.layer_id,
            "name": self.name,
            "match_name": self.match_name,
            "layer_type": self.layer_type,
            "selected": self.selected,
            "locked": self.locked,
            "enabled": self.enabled,
            "source_text": self.source_text,
            "in_seconds": self.in_seconds,
            "out_seconds": self.out_seconds,
            "start_seconds": self.start_seconds,
            "position": self.position.to_dict(),
            "opacity": self.opacity.to_dict(),
            "scale": self.scale.to_dict(),
            "effects": [item.to_dict() for item in self.effects],
        }


@dataclass(frozen=True)
class AECompositionSnapshot:
    available: bool
    item_id: Optional[int] = None
    name: Optional[str] = None
    width: Optional[float] = None
    height: Optional[float] = None
    duration: Optional[float] = None
    frame_rate: Optional[float] = None
    time_seconds: Optional[float] = None
    time_frame: Optional[int] = None
    num_layers: Optional[int] = None
    selected_layers_count: int = 0

    @classmethod
    def from_dict(cls, value: Any) -> "AECompositionSnapshot":
        if not isinstance(value, dict) or not isinstance(value.get("available"), bool):
            raise ValueError("invalid composition snapshot")
        count = value.get("selected_layers_count", 0)
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            raise ValueError("invalid selected layer count")
        name = value.get("name")
        if name is not None and not isinstance(name, str):
            raise ValueError("invalid composition name")
        return cls(
            available=value["available"],
            item_id=_int_or_none(value.get("item_id"), "composition id"),
            name=name,
            width=_number_or_none(value.get("width"), "composition width"),
            height=_number_or_none(value.get("height"), "composition height"),
            duration=_number_or_none(value.get("duration"), "composition duration"),
            frame_rate=_number_or_none(value.get("frame_rate"), "composition frame rate"),
            time_seconds=_number_or_none(value.get("time_seconds"), "composition time"),
            time_frame=_int_or_none(value.get("time_frame"), "composition time frame"),
            num_layers=_int_or_none(value.get("num_layers"), "composition layer count"),
            selected_layers_count=count,
        )

    @classmethod
    def unavailable(cls) -> "AECompositionSnapshot":
        return cls(False)

    def to_pilot_dict(self) -> Optional[Dict[str, Any]]:
        if not self.available:
            return None
        return {
            "id": self.item_id,
            "name": self.name,
            "width": self.width,
            "height": self.height,
            "duration_seconds": self.duration,
            "frame_rate": self.frame_rate,
            "current_time_seconds": self.time_seconds,
            "current_time_frame": self.time_frame,
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "available": self.available,
            "item_id": self.item_id,
            "name": self.name,
            "width": self.width,
            "height": self.height,
            "duration": self.duration,
            "frame_rate": self.frame_rate,
            "time_seconds": self.time_seconds,
            "time_frame": self.time_frame,
            "num_layers": self.num_layers,
            "selected_layers_count": self.selected_layers_count,
        }


@dataclass(frozen=True)
class AEProjectSnapshot:
    item_count: int
    composition_count: int
    file_path: Optional[str] = None

    @classmethod
    def from_dict(cls, value: Any) -> "AEProjectSnapshot":
        if not isinstance(value, dict):
            raise ValueError("invalid project snapshot")
        item_count = value.get("item_count")
        composition_count = value.get("composition_count")
        if (
            not isinstance(item_count, int) or isinstance(item_count, bool) or item_count < 0
            or not isinstance(composition_count, int) or isinstance(composition_count, bool) or composition_count < 0
        ):
            raise ValueError("invalid project counts")
        file_path = value.get("file_path")
        if file_path is not None and not isinstance(file_path, str):
            raise ValueError("invalid project file path")
        return cls(item_count, composition_count, file_path)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "item_count": self.item_count,
            "composition_count": self.composition_count,
            "file_path": self.file_path,
        }


@dataclass(frozen=True)
class AEStateSnapshot:
    schema_version: int
    reader_version: str
    status: str
    request_id: str
    run_id: str
    captured_at: Optional[float]
    application: Dict[str, Any]
    capabilities: AECapabilityManifest
    project: AEProjectSnapshot
    composition: AECompositionSnapshot
    layers: List[AELayerSnapshot]
    errors: List[str]
    session_id: Optional[str] = None
    lesson_id: Optional[str] = None
    step_id: Optional[str] = None

    @classmethod
    def from_dict(cls, value: Any) -> "AEStateSnapshot":
        required = (
            "schema_version", "reader_version", "status", "request_id", "run_id",
            "captured_at", "application", "capabilities", "project",
            "composition", "layers", "errors",
        )
        if not isinstance(value, dict) or any(key not in value for key in required):
            raise ValueError("missing required response field")
        if value["schema_version"] != SCHEMA_VERSION:
            raise ValueError("unsupported response schema")
        if value["reader_version"] != READER_VERSION:
            raise ValueError("unexpected reader version")
        if not all(isinstance(value[key], str) for key in ("status", "request_id", "run_id")):
            raise ValueError("invalid response identity")
        captured = _number_or_none(value["captured_at"], "capture timestamp")
        application = value["application"]
        layers_raw = value["layers"]
        errors = value["errors"]
        if not isinstance(application, dict) or not isinstance(layers_raw, list) or not isinstance(errors, list):
            raise ValueError("invalid response containers")
        if not all(isinstance(item, str) for item in errors):
            raise ValueError("response errors must contain strings only")
        for optional_identity in ("session_id", "lesson_id", "step_id"):
            if value.get(optional_identity) is not None and not isinstance(value.get(optional_identity), str):
                raise ValueError(f"invalid {optional_identity}")
        capabilities = AECapabilityManifest.from_dict(value["capabilities"])
        project = AEProjectSnapshot.from_dict(value["project"])
        composition = AECompositionSnapshot.from_dict(value["composition"])
        layers = [AELayerSnapshot.from_dict(item) for item in layers_raw]

        if project.item_count < project.composition_count:
            raise ValueError("project composition count exceeds item count")

        if composition.available:
            if project.composition_count < 1:
                raise ValueError("active composition exists while project reports zero compositions")
            if composition.item_id is None or composition.item_id < 1:
                raise ValueError("active composition is missing a stable item id")
            if composition.num_layers is None or composition.num_layers < 0:
                raise ValueError("active composition is missing a valid layer count")
            if len(layers) != composition.num_layers:
                raise ValueError("composition layer count does not match returned layers")
            expected_indices = list(range(1, composition.num_layers + 1))
            actual_indices = [layer.index for layer in layers]
            if actual_indices != expected_indices:
                raise ValueError("returned layer indices are incomplete or out of order")
            selected_count = sum(1 for layer in layers if layer.selected)
            if selected_count != composition.selected_layers_count:
                raise ValueError("selected layer count does not match layer flags")
        elif layers:
            raise ValueError("layers returned without an active composition")

        layer_ids = []
        for layer in layers:
            if layer.layer_id is None or layer.layer_id < 1:
                raise ValueError("layer is missing a stable identity")
            layer_ids.append(layer.layer_id)
        if len(layer_ids) != len(set(layer_ids)):
            raise ValueError("duplicate layer identity")

        return cls(
            schema_version=SCHEMA_VERSION,
            reader_version=READER_VERSION,
            status=value["status"],
            request_id=value["request_id"],
            run_id=value["run_id"],
            captured_at=captured,
            application=_primitive(application),
            capabilities=capabilities,
            project=project,
            composition=composition,
            layers=layers,
            errors=list(errors),
            session_id=value.get("session_id"),
            lesson_id=value.get("lesson_id"),
            step_id=value.get("step_id"),
        )

    def find_layer(self, name: str) -> Optional[AELayerSnapshot]:
        matches = [layer for layer in self.layers if layer.name == name]
        return matches[0] if len(matches) == 1 else None

    def to_pilot_state(self) -> Dict[str, Any]:
        return {
            "project": self.project.to_dict(),
            "active_comp": self.composition.to_pilot_dict(),
            "layers": [layer.to_pilot_dict() for layer in self.layers],
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "reader_version": self.reader_version,
            "status": self.status,
            "request_id": self.request_id,
            "run_id": self.run_id,
            "captured_at": self.captured_at,
            "application": _primitive(self.application),
            "capabilities": self.capabilities.to_dict(),
            "project": self.project.to_dict(),
            "composition": self.composition.to_dict(),
            "layers": [item.to_dict() for item in self.layers],
            "errors": list(self.errors),
            "session_id": self.session_id,
            "lesson_id": self.lesson_id,
            "step_id": self.step_id,
        }


def invalid_state(
    request: AEReadRequest,
    status: str,
    error: str,
    manifest: Optional[AECapabilityManifest] = None,
) -> AEStateSnapshot:
    manifest = manifest or AECapabilityManifest(READER_VERSION, SCHEMA_VERSION, [])
    return AEStateSnapshot(
        schema_version=SCHEMA_VERSION,
        reader_version=READER_VERSION,
        status=status,
        request_id=request.request_id,
        run_id=request.run_id,
        captured_at=None,
        application={"name": "After Effects"},
        capabilities=manifest,
        project=AEProjectSnapshot(0, 0, None),
        composition=AECompositionSnapshot.unavailable(),
        layers=[],
        errors=[error],
        session_id=request.session_id,
        lesson_id=request.lesson_id,
        step_id=request.step_id,
    )
