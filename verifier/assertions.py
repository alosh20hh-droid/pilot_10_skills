"""Deterministic assertion operators for the AE verification pilot."""

from __future__ import annotations

import math
from numbers import Real
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .model import AssertionBatchResult, AssertionResult
from .path import resolve_path


SUPPORTED_OPERATORS = {
    "eq",
    "approx",
    "count_eq",
    "contains_layer",
    "not_contains_layer_name",
    "count_layer_name",
    "contains_keyframe",
    "contains_effect_stable_id",
}


def _is_number(value: Any) -> bool:
    return (
        isinstance(value, Real)
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _safe_expected(assertion: Dict[str, Any]) -> Any:
    if "value" in assertion:
        return assertion.get("value")
    interesting = {
        key: value
        for key, value in assertion.items()
        if key not in {"path", "op", "tolerance", "value_tolerance", "runtime_key"}
    }
    return interesting or None


def _numeric_equal(actual: Any, expected: Any, tolerance: float) -> bool:
    return _is_number(actual) and _is_number(expected) and abs(float(actual) - float(expected)) <= tolerance


def _operator_eq(actual: Any, assertion: Dict[str, Any], defaults: Dict[str, float]) -> Tuple[bool, str]:
    expected = assertion.get("value")
    if _is_number(actual) and _is_number(expected):
        tolerance = float(assertion.get("tolerance", defaults["numeric"]))
        passed = _numeric_equal(actual, expected, tolerance)
        return passed, f"numeric equality tolerance={tolerance}"
    return actual == expected, "exact equality"


def _operator_approx(actual: Any, assertion: Dict[str, Any], defaults: Dict[str, float]) -> Tuple[bool, str]:
    expected = assertion.get("value")
    tolerance = float(assertion.get("tolerance", defaults["numeric"]))
    if not _is_number(actual) or not _is_number(expected):
        return False, "approx requires numeric actual and expected values"
    return _numeric_equal(actual, expected, tolerance), f"absolute tolerance={tolerance}"


def _operator_count_eq(actual: Any, assertion: Dict[str, Any], defaults: Dict[str, float]) -> Tuple[bool, str]:
    expected = assertion.get("value")
    if not isinstance(expected, int) or isinstance(expected, bool) or expected < 0:
        return False, "count_eq requires a non-negative integer expectation"
    if not isinstance(actual, (list, tuple, dict, str)):
        return False, "count_eq requires a countable value"
    return len(actual) == expected, f"count={len(actual)} expected={expected}"


def _layer_matches(layer: Any, assertion: Dict[str, Any]) -> bool:
    if not isinstance(layer, dict):
        return False
    for key in ("name", "type", "source_text"):
        if key in assertion and layer.get(key) != assertion.get(key):
            return False
    return True


def _operator_contains_layer(actual: Any, assertion: Dict[str, Any], defaults: Dict[str, float]) -> Tuple[bool, str]:
    if not isinstance(actual, list):
        return False, "contains_layer requires a list"
    matched = [layer for layer in actual if _layer_matches(layer, assertion)]
    if len(matched) == 1:
        return True, "exactly one matching layer found"
    if len(matched) > 1:
        return False, "matching layer is ambiguous"
    return False, "matching layer not found"


def _operator_not_contains_layer_name(actual: Any, assertion: Dict[str, Any], defaults: Dict[str, float]) -> Tuple[bool, str]:
    if not isinstance(actual, list):
        return False, "not_contains_layer_name requires a list"
    target = assertion.get("value")
    matches = [layer for layer in actual if isinstance(layer, dict) and layer.get("name") == target]
    return len(matches) == 0, f"matching layer count={len(matches)}"


def _operator_count_layer_name(actual: Any, assertion: Dict[str, Any], defaults: Dict[str, float]) -> Tuple[bool, str]:
    if not isinstance(actual, list):
        return False, "count_layer_name requires a list"
    target = assertion.get("name")
    expected = assertion.get("value")
    if not isinstance(expected, int) or isinstance(expected, bool) or expected < 0:
        return False, "count_layer_name requires a non-negative integer expectation"
    count = sum(
        1
        for layer in actual
        if isinstance(layer, dict) and layer.get("name") == target
    )
    return count == expected, f"layer name count={count} expected={expected}"


def _operator_contains_keyframe(actual: Any, assertion: Dict[str, Any], defaults: Dict[str, float]) -> Tuple[bool, str]:
    if not isinstance(actual, list):
        return False, "contains_keyframe requires a list"

    expected_frame = assertion.get("frame")
    expected_value = assertion.get("value")
    expected_seconds = assertion.get("time_seconds")
    frame_tolerance = int(assertion.get("frame_tolerance", defaults["frame"]))
    value_tolerance = float(assertion.get("value_tolerance", defaults["numeric"]))
    seconds_tolerance = float(assertion.get("seconds_tolerance", defaults["seconds"]))

    matches = []
    for keyframe in actual:
        if not isinstance(keyframe, dict):
            continue

        if expected_frame is not None:
            actual_frame = keyframe.get("frame")
            if not isinstance(actual_frame, int) or isinstance(actual_frame, bool):
                continue
            if abs(actual_frame - int(expected_frame)) > frame_tolerance:
                continue

        if expected_seconds is not None:
            actual_seconds = keyframe.get("time_seconds")
            if not _numeric_equal(actual_seconds, expected_seconds, seconds_tolerance):
                continue

        if expected_value is not None:
            actual_value = keyframe.get("value")
            if _is_number(actual_value) and _is_number(expected_value):
                if not _numeric_equal(actual_value, expected_value, value_tolerance):
                    continue
            elif actual_value != expected_value:
                continue

        matches.append(keyframe)

    if len(matches) == 1:
        return True, "exactly one matching keyframe found"
    if len(matches) > 1:
        return False, "matching keyframe is ambiguous"
    return False, "matching keyframe not found"


def _operator_contains_effect_stable_id(
    actual: Any,
    assertion: Dict[str, Any],
    defaults: Dict[str, float],
    runtime: Dict[str, Any],
) -> Tuple[bool, str]:
    if not isinstance(actual, list):
        return False, "contains_effect_stable_id requires a list"
    runtime_key = assertion.get("runtime_key")
    if not isinstance(runtime_key, str) or runtime_key not in runtime:
        return False, f"runtime calibration value missing: {runtime_key}"
    stable_id = runtime[runtime_key]
    matches = [
        effect
        for effect in actual
        if isinstance(effect, dict) and effect.get("stable_id") == stable_id
    ]
    if len(matches) == 1:
        return True, "exactly one matching effect found"
    if len(matches) > 1:
        return False, "matching effect identity is ambiguous"
    return False, "matching effect not found"


def evaluate_assertions(
    state: Dict[str, Any],
    assertions: Iterable[Dict[str, Any]],
    *,
    runtime: Optional[Dict[str, Any]] = None,
    comparison_policy: Optional[Dict[str, Any]] = None,
) -> AssertionBatchResult:
    runtime = runtime or {}
    policy = comparison_policy or {}

    defaults = {
        "numeric": float(policy.get("default_numeric_absolute_tolerance", 0.001)),
        "seconds": float(
            (policy.get("keyframe_time_policy") or {}).get(
                "secondary_seconds_tolerance",
                0.001,
            )
        ),
        "frame": int(
            (policy.get("keyframe_time_policy") or {}).get(
                "frame_tolerance",
                0,
            )
        ),
    }

    results: List[AssertionResult] = []
    contract_error = False

    for index, assertion in enumerate(assertions):
        if not isinstance(assertion, dict):
            contract_error = True
            results.append(
                AssertionResult(
                    index=index,
                    path="",
                    operator="",
                    passed=False,
                    reason="assertion must be an object",
                    error_code="ASSERTION_CONTRACT_ERROR",
                )
            )
            continue

        path = assertion.get("path")
        operator = assertion.get("op")
        if not isinstance(path, str) or not path or not isinstance(operator, str):
            contract_error = True
            results.append(
                AssertionResult(
                    index=index,
                    path=str(path or ""),
                    operator=str(operator or ""),
                    passed=False,
                    expected=_safe_expected(assertion),
                    reason="assertion requires path and op",
                    error_code="ASSERTION_CONTRACT_ERROR",
                )
            )
            continue

        if operator not in SUPPORTED_OPERATORS:
            contract_error = True
            results.append(
                AssertionResult(
                    index=index,
                    path=path,
                    operator=operator,
                    passed=False,
                    expected=_safe_expected(assertion),
                    reason=f"unsupported assertion operator: {operator}",
                    error_code="UNKNOWN_ASSERTION_OPERATOR",
                )
            )
            continue

        resolved = resolve_path(state, path, runtime)
        if not resolved.ok:
            results.append(
                AssertionResult(
                    index=index,
                    path=path,
                    operator=operator,
                    passed=False,
                    expected=_safe_expected(assertion),
                    actual=None,
                    reason=resolved.reason,
                    error_code=resolved.error_code,
                )
            )
            continue

        actual = resolved.value
        try:
            if operator == "eq":
                passed, reason = _operator_eq(actual, assertion, defaults)
            elif operator == "approx":
                passed, reason = _operator_approx(actual, assertion, defaults)
            elif operator == "count_eq":
                passed, reason = _operator_count_eq(actual, assertion, defaults)
            elif operator == "contains_layer":
                passed, reason = _operator_contains_layer(actual, assertion, defaults)
            elif operator == "not_contains_layer_name":
                passed, reason = _operator_not_contains_layer_name(actual, assertion, defaults)
            elif operator == "count_layer_name":
                passed, reason = _operator_count_layer_name(actual, assertion, defaults)
            elif operator == "contains_keyframe":
                passed, reason = _operator_contains_keyframe(actual, assertion, defaults)
            elif operator == "contains_effect_stable_id":
                passed, reason = _operator_contains_effect_stable_id(
                    actual,
                    assertion,
                    defaults,
                    runtime,
                )
            else:
                # Guarded above; kept fail-closed if the dispatch table changes.
                passed = False
                reason = "unreachable unsupported operator"
                contract_error = True
        except (TypeError, ValueError, OverflowError) as exc:
            passed = False
            reason = f"operator evaluation failed: {exc}"
            contract_error = True

        results.append(
            AssertionResult(
                index=index,
                path=path,
                operator=operator,
                passed=passed,
                expected=_safe_expected(assertion),
                actual=actual,
                reason=reason,
                error_code=None if passed else "ASSERTION_FAILED",
            )
        )

    passed = bool(results) and all(item.passed for item in results)
    if not results:
        passed = True

    return AssertionBatchResult(
        passed=passed and not contract_error,
        results=results,
        contract_error=contract_error,
    )
