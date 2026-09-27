# Step 04 — Microsoft UFO² Execution Layer

Status: **CODE COMPLETE / LIVE MEASURED EXECUTION GATE PENDING**

This document closes Step 04 as one self-contained system.

Step 05 (model selection/benchmarking) must remain separate.

## Responsibility

Step 04 turns each canonical pilot skill into a Microsoft UFO Follower Mode execution plan and launches that plan through the visible Windows UI.

UFO is an execution body only.

UFO does **not**:

- define the skill specification,
- prepare canonical fixtures,
- certify fixtures,
- decide PASS,
- overwrite the deterministic verifier,
- promote knowledge automatically.

## Upstream lock

Measured execution is pinned to:

\`\`\`text
microsoft/UFO
e2a03126241c696fdaf9a669a271ca3fca6d9916
\`\`\`

The adapter verifies exact Git HEAD, clean worktree, and exact blob hashes for the audited upstream files.

The audited surface includes:

- CLI entrypoint,
- Follower Mode session factory,
- FollowerSession,
- PlanReader,
- BaseSession round limits,
- UI controller,
- system configuration,
- configuration loader,
- official Follower Mode documentation.

## Existing checkout

The user already has UFO locally.

Step 04 auto-discovers common locations including:

\`\`\`text
%USERPROFILE%\UFO
%USERPROFILE%\Desktop\UFO
%USERPROFILE%\Documents\UFO
\`\`\`

or accepts:

\`\`\`text
UFO_ROOT
--ufo-checkout
\`\`\`

The source checkout is never modified by measured execution.

## Follower plan compiler

All ten skills compile directly from \`pilot_10_skills.yaml\`.

The canonical \`measured_ui_steps\` are preserved verbatim.

The compiler rejects hidden/non-UI execution routes such as scripts, JSX, PowerShell, shell commands, COM automation, application APIs, expressions, and direct \`.aep\` mutation.

The Follower plan is bound to:

\`\`\`text
object = AfterFX.exe
mode   = follower
\`\`\`

## Isolated execution

Measured execution runs from a detached Git worktree at the locked commit.

A temporary UFO test-environment override is written only inside that worktree:

\`\`\`text
config/ufo/system_test.yaml
UFO_ENV=test
\`\`\`

The original UFO checkout remains untouched.

## UI-only overlay

The measured worktree forces:

\`\`\`text
CONTROL_BACKEND = ["uia"]
USE_APIS = false
USE_MCP = false
MCP_FALLBACK_TO_UI = false
EVA_SESSION = false
EVA_ROUND = false
TASK_STATUS = false
SAVE_EXPERIENCE = always_not
ASK_QUESTION = false
USE_CUSTOMIZATION = false
ENABLED_THIRD_PARTY_AGENTS = []
INPUT_TEXT_API = type_keys
CLICK_API = click_input
\`\`\`

This removes API/MCP/self-evaluation/experience-learning routes from the measured path.

## Follower round budget

The pinned upstream default \`MAX_ROUND: 1\` is insufficient for multi-step Follower plans because the first Follower round selects the application.

Step 04 therefore sets:

\`\`\`text
MAX_ROUND = measured_step_count + 2
MAX_STEP  = max(50, measured_step_count * 12)
\`\`\`

inside the isolated worktree only.

## Fixture boundary

UFO may execute only against a Step 03 disposable run copy.

Before plan preparation, Step 04 verifies:

- \`.aep\` exists,
- filename matches the skill fixture ID,
- parent directory matches the hashed run ID,
- binary SHA-256 equals the certified copy hash.

The canonical fixture itself cannot satisfy this binding.

## Run identity

Each measured \`run_id\` is permanently one-use.

A persistent reservation is created before execution.

Deleting execution output does not make the ID reusable.

## Execution evidence

Step 04 records:

- run ID,
- skill ID,
- fixture ID/path/hash,
- plan and plan hash,
- pinned UFO commit,
- exact command,
- timestamps,
- stdout,
- stderr,
- UFO logs when produced,
- process exit code,
- timeout state,
- isolated overlay round/step budgets.

A zero process exit code is **not PASS**.

The result explicitly records:

\`\`\`text
success_oracle = external_deterministic_verifier
ufo_finish_is_not_success = true
\`\`\`

## Safety arm

Measured UI control cannot start without the explicit flag:

\`\`\`text
--arm-measured-execution
\`\`\`

## CI gate

Step 04 is software-complete only when Windows CI passes:

1. AE Reader checks,
2. verifier checks,
3. fixture-spec checks,
4. all ten UFO plan compilation,
5. UFO adapter unit tests,
6. detached-worktree overlay tests.

## Live gate

No claim is made that a real After Effects skill was executed yet.

Live measured execution depends on:

1. Step 03 live-certified \`.aep\` fixtures,
2. a local UFO checkout matching the pinned commit,
3. Step 05 model configuration,
4. real After Effects preflight.

Those live dependencies belong to their respective steps and the later integrated Runner.

## Step 05 boundary

Step 05 will choose and benchmark the model used by UFO.

Step 04 does not select a winner, tune a model, or change the deterministic verification oracle.
