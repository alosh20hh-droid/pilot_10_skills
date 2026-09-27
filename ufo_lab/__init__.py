"""Step 04 Microsoft UFO² integration for the AE verification pilot."""

from .installation import (
    UFOInstallation,
    UFOInstallationError,
    UFOInspection,
    UFOReferenceLock,
)
from .launcher import UFOExecutionError, UFOExecutionRecord, UFOFollowerExecutor
from .plan import (
    CompiledUFOPlan,
    UFOPlanError,
    compile_all_plans,
    compile_skill_plan,
    write_compiled_plan,
)
from .workspace import UFOWorkspace, UFOWorkspaceError, UFOWorkspaceManager

__all__ = [
    "UFOInstallation",
    "UFOInstallationError",
    "UFOInspection",
    "UFOReferenceLock",
    "UFOExecutionError",
    "UFOExecutionRecord",
    "UFOFollowerExecutor",
    "CompiledUFOPlan",
    "UFOPlanError",
    "compile_all_plans",
    "compile_skill_plan",
    "write_compiled_plan",
    "UFOWorkspace",
    "UFOWorkspaceError",
    "UFOWorkspaceManager",
]
