"""Conservative data structures for the AE-R1 file IPC contract."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


def _primitive(value: Any) -> Any:
    """Keep only JSON-like values; never expose host application objects."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (list, tuple)):
        return [_primitive(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _primitive(item) for key, item in value.items()}
    return None


@dataclass(frozen=True)
class AEReadRequest:
    request_id: str
    session_id: str
    lesson_id: str
    step_id: str
    requested_at: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "request_id": self.request_id,
            "session_id": self.session_id,
            "lesson_id": self.lesson_id,
            "step_id": self.step_id,
            "requested_at": self.requested_at,
        }


@dataclass(frozen=True)
class AEPropertyKey:
    index: int
    time: Optional[float]
    value: Any

    @classmethod
    def from_dict(cls, value: Any) -> "AEPropertyKey":
        if not isinstance(value, dict) or not isinstance(value.get("index"), int):
            raise ValueError("invalid property key")
        key_time = value.get("time")
        if key_time is not None and not isinstance(key_time, (int, float)):
            raise ValueError("invalid property key time")
        return cls(value["index"], key_time, _primitive(value.get("value")))


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
        if not isinstance(num_keys, int) or num_keys < 0:
            raise ValueError("invalid property key count")
        varying = value.get("is_time_varying", False)
        if not isinstance(varying, bool):
            raise ValueError("invalid time-varying flag")
        keys = [AEPropertyKey.from_dict(item) for item in (value.get("keys") or [])]
        if value["available"] and len(keys) != num_keys:
            raise ValueError("property key count does not match keys")
        return cls(
            available=value["available"],
            name=value.get("name"),
            match_name=value.get("match_name"),
            num_keys=num_keys,
            is_time_varying=varying,
            current_value=_primitive(value.get("current_value")),
            keys=keys,
        )


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
        return cls(
            mode=value["mode"],
            property=AEPropertySnapshot.from_dict(prop) if isinstance(prop, dict) else None,
            separated={
                str(key): AEPropertySnapshot.from_dict(item)
                for key, item in (value.get("separated") or {}).items()
            },
        )


@dataclass(frozen=True)
class AELayerSnapshot:
    index: int
    name: str
    match_name: str
    locked: bool
    enabled: bool
    is_text_layer: bool
    position: AEPositionSnapshot
    opacity: AEPropertySnapshot
    scale: AEPropertySnapshot

    @classmethod
    def from_dict(cls, value: Any) -> "AELayerSnapshot":
        required = ("index", "name", "match_name", "locked", "enabled", "is_text_layer", "position", "opacity", "scale")
        if not isinstance(value, dict) or any(key not in value for key in required):
            raise ValueError("invalid layer snapshot")
        if not isinstance(value["index"], int) or not all(isinstance(value[key], bool) for key in ("locked", "enabled", "is_text_layer")):
            raise ValueError("invalid layer identity")
        return cls(
            index=value["index"], name=str(value["name"]), match_name=str(value["match_name"]),
            locked=value["locked"], enabled=value["enabled"], is_text_layer=value["is_text_layer"],
            position=AEPositionSnapshot.from_dict(value.get("position", {"mode": "unavailable"})),
            opacity=AEPropertySnapshot.from_dict(value.get("opacity", {"available": False})),
            scale=AEPropertySnapshot.from_dict(value.get("scale", {"available": False})),
        )


@dataclass(frozen=True)
class AECompositionSnapshot:
    available: bool
    name: Optional[str] = None
    width: Optional[float] = None
    height: Optional[float] = None
    duration: Optional[float] = None
    frame_rate: Optional[float] = None
    time: Optional[float] = None
    num_layers: Optional[int] = None
    selected_layers_count: int = 0

    @classmethod
    def from_dict(cls, value: Any) -> "AECompositionSnapshot":
        if not isinstance(value, dict) or not isinstance(value.get("available"), bool):
            raise ValueError("invalid composition snapshot")
        count = value.get("selected_layers_count", 0)
        if not isinstance(count, int) or count < 0:
            raise ValueError("invalid selected layer count")
        return cls(
            available=value["available"], name=value.get("name"), width=value.get("width"),
            height=value.get("height"), duration=value.get("duration"),
            frame_rate=value.get("frame_rate"), time=value.get("time"),
            num_layers=value.get("num_layers"), selected_layers_count=count,
        )


@dataclass(frozen=True)
class AEStateSnapshot:
    schema_version: int
    status: str
    request_id: str
    session_id: str
    lesson_id: str
    step_id: str
    captured_at: Optional[float]
    application: Dict[str, Any]
    composition: AECompositionSnapshot
    selected_layers: List[AELayerSnapshot]
    errors: List[str]

    @classmethod
    def from_dict(cls, value: Any) -> "AEStateSnapshot":
        required = ("schema_version", "status", "request_id", "session_id", "lesson_id", "step_id", "captured_at", "application", "composition", "selected_layers", "errors")
        if not isinstance(value, dict) or any(key not in value for key in required):
            raise ValueError("missing required response field")
        if value["schema_version"] != 1 or not isinstance(value["status"], str):
            raise ValueError("invalid response schema")
        if not all(isinstance(value[key], str) for key in ("request_id", "session_id", "lesson_id", "step_id")):
            raise ValueError("invalid response identity")
        captured = value["captured_at"]
        if captured is not None and not isinstance(captured, (int, float)):
            raise ValueError("invalid capture timestamp")
        if not isinstance(value["application"], dict) or not isinstance(value["errors"], list) or not isinstance(value["selected_layers"], list):
            raise ValueError("invalid response containers")
        return cls(
            schema_version=1, status=value["status"], request_id=value["request_id"],
            session_id=value["session_id"], lesson_id=value["lesson_id"], step_id=value["step_id"],
            captured_at=captured, application=_primitive(value["application"]),
            composition=AECompositionSnapshot.from_dict(value["composition"]),
            selected_layers=[AELayerSnapshot.from_dict(item) for item in value["selected_layers"]],
            errors=[str(item) for item in value["errors"]],
        )


def invalid_state(request: AEReadRequest, status: str, error: str) -> AEStateSnapshot:
    return AEStateSnapshot(
        schema_version=1, status=status, request_id=request.request_id,
        session_id=request.session_id, lesson_id=request.lesson_id, step_id=request.step_id,
        captured_at=None, application={"name": "After Effects"},
        composition=AECompositionSnapshot(False), selected_layers=[], errors=[error],
    )
