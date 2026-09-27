"""Deterministic verifier result models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


RUN_STATUSES = {
    "PASS",
    "UI_CHANGED",
    "EXECUTION_FAILED",
    "VERIFICATION_FAILED",
    "BLOCKED",
    "INCONCLUSIVE",
}

SKILL_STATUSES = {
    "VERIFIED",
    "NOT_VERIFIED",
    "NEEDS_REVIEW",
}


@dataclass(frozen=True)
class AssertionResult:
    index: int
    path: str
    operator: str
    passed: bool
    expected: Any = None
    actual: Any = None
    reason: Optional[str] = None
    error_code: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "index": self.index,
            "path": self.path,
            "operator": self.operator,
            "passed": self.passed,
            "expected": self.expected,
            "actual": self.actual,
            "reason": self.reason,
            "error_code": self.error_code,
        }


@dataclass(frozen=True)
class AssertionBatchResult:
    passed: bool
    results: List[AssertionResult] = field(default_factory=list)
    contract_error: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "contract_error": self.contract_error,
            "results": [item.to_dict() for item in self.results],
        }


@dataclass(frozen=True)
class PreflightDecision:
    can_execute: bool
    run_status: Optional[str]
    reason_code: Optional[str]
    reason: Optional[str]
    assertion_results: Optional[AssertionBatchResult] = None
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "can_execute": self.can_execute,
            "run_status": self.run_status,
            "reason_code": self.reason_code,
            "reason": self.reason,
            "assertion_results": (
                self.assertion_results.to_dict()
                if self.assertion_results is not None
                else None
            ),
            "details": dict(self.details),
        }


@dataclass(frozen=True)
class RunDecision:
    run_status: str
    reason_code: str
    reason: str
    assertion_results: Optional[AssertionBatchResult] = None
    details: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.run_status not in RUN_STATUSES:
            raise ValueError(f"invalid run status: {self.run_status}")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_status": self.run_status,
            "reason_code": self.reason_code,
            "reason": self.reason,
            "assertion_results": (
                self.assertion_results.to_dict()
                if self.assertion_results is not None
                else None
            ),
            "details": dict(self.details),
        }


@dataclass(frozen=True)
class SkillDecision:
    skill_status: str
    run_statuses: List[str]
    verified_run_count: int
    review_reason: Optional[str] = None

    def __post_init__(self) -> None:
        if self.skill_status not in SKILL_STATUSES:
            raise ValueError(f"invalid skill status: {self.skill_status}")
        for status in self.run_statuses:
            if status not in RUN_STATUSES:
                raise ValueError(f"invalid run status: {status}")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "skill_status": self.skill_status,
            "run_statuses": list(self.run_statuses),
            "verified_run_count": self.verified_run_count,
            "review_reason": self.review_reason,
        }


@dataclass(frozen=True)
class EvidenceValidation:
    valid: bool
    error_code: Optional[str] = None
    reason: Optional[str] = None
    state: Optional[Dict[str, Any]] = None
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "valid": self.valid,
            "error_code": self.error_code,
            "reason": self.reason,
            "state": self.state,
            "details": dict(self.details),
        }
