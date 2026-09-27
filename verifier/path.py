"""Safe resolver for the pilot assertion path language."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


@dataclass(frozen=True)
class PathResolution:
    ok: bool
    value: Any = None
    error_code: Optional[str] = None
    reason: Optional[str] = None


def _split_segments(path: str) -> List[str]:
    segments: List[str] = []
    current: List[str] = []
    depth = 0

    for char in path:
        if char == "." and depth == 0:
            if not current:
                raise ValueError("empty path segment")
            segments.append("".join(current))
            current = []
            continue
        if char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth < 0:
                raise ValueError("unbalanced path brackets")
        current.append(char)

    if depth != 0:
        raise ValueError("unbalanced path brackets")
    if current:
        segments.append("".join(current))
    if not segments:
        raise ValueError("empty path")
    return segments


def _parse_segment(segment: str) -> Tuple[str, List[str]]:
    name_chars: List[str] = []
    selectors: List[str] = []
    index = 0

    while index < len(segment) and segment[index] != "[":
        name_chars.append(segment[index])
        index += 1

    name = "".join(name_chars)
    if not name:
        raise ValueError("missing segment name")

    while index < len(segment):
        if segment[index] != "[":
            raise ValueError("invalid selector syntax")
        end = segment.find("]", index + 1)
        if end < 0:
            raise ValueError("unterminated selector")
        selector = segment[index + 1:end]
        if not selector:
            raise ValueError("empty selector")
        selectors.append(selector)
        index = end + 1

    return name, selectors


def _resolve_name(container: Any, name: str) -> PathResolution:
    if not isinstance(container, dict):
        return PathResolution(False, error_code="PATH_TYPE_MISMATCH", reason=f"cannot access {name} on non-object")

    aliases = {
        "layer": "layers",
        "property": "properties",
    }
    actual_name = aliases.get(name, name)
    if actual_name not in container:
        return PathResolution(False, error_code="PATH_NOT_FOUND", reason=f"field {actual_name} not found")
    return PathResolution(True, value=container[actual_name])


def _resolve_selector(value: Any, selector: str, runtime: Dict[str, Any]) -> PathResolution:
    if selector.isdigit():
        if not isinstance(value, list):
            return PathResolution(False, error_code="PATH_TYPE_MISMATCH", reason="index selector requires a list")
        index = int(selector)
        if index < 0 or index >= len(value):
            return PathResolution(False, error_code="PATH_NOT_FOUND", reason=f"index {index} out of range")
        return PathResolution(True, value=value[index])

    if "=" not in selector:
        return PathResolution(False, error_code="INVALID_PATH", reason=f"invalid selector {selector}")

    key, expected_raw = selector.split("=", 1)
    key = key.strip()
    expected_raw = expected_raw.strip()
    if not key:
        return PathResolution(False, error_code="INVALID_PATH", reason="empty selector key")

    if (
        len(expected_raw) >= 2
        and expected_raw[0] == expected_raw[-1]
        and expected_raw[0] in {'"', "'"}
    ):
        expected = expected_raw[1:-1]
    elif expected_raw in runtime:
        expected = runtime[expected_raw]
    else:
        expected = expected_raw

    if not isinstance(value, list):
        return PathResolution(False, error_code="PATH_TYPE_MISMATCH", reason="filter selector requires a list")

    matches = [
        item
        for item in value
        if isinstance(item, dict) and item.get(key) == expected
    ]
    if not matches:
        return PathResolution(
            False,
            error_code="PATH_NOT_FOUND",
            reason=f"no item matched {key}={expected!r}",
        )
    if len(matches) > 1:
        return PathResolution(
            False,
            error_code="AMBIGUOUS_PATH",
            reason=f"multiple items matched {key}={expected!r}",
        )
    return PathResolution(True, value=matches[0])


def resolve_path(state: Dict[str, Any], path: str, runtime: Optional[Dict[str, Any]] = None) -> PathResolution:
    runtime = runtime or {}
    if not isinstance(state, dict):
        return PathResolution(False, error_code="INVALID_STATE", reason="state root must be an object")
    if not isinstance(path, str) or not path:
        return PathResolution(False, error_code="INVALID_PATH", reason="path must be a non-empty string")

    try:
        segments = _split_segments(path)
    except ValueError as exc:
        return PathResolution(False, error_code="INVALID_PATH", reason=str(exc))

    current: Any = state
    for segment in segments:
        try:
            name, selectors = _parse_segment(segment)
        except ValueError as exc:
            return PathResolution(False, error_code="INVALID_PATH", reason=str(exc))

        name_result = _resolve_name(current, name)
        if not name_result.ok:
            return name_result
        current = name_result.value

        for selector in selectors:
            selector_result = _resolve_selector(current, selector, runtime)
            if not selector_result.ok:
                return selector_result
            current = selector_result.value

    return PathResolution(True, value=current)
