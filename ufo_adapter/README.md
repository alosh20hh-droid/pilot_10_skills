# Step 04 — Microsoft UFO² execution adapter

This package connects the **existing** Microsoft UFO checkout to the AE 10-skill verification pilot.

UFO is the execution body only. It does not define success, it does not prepare canonical fixtures, and its own FINISH/evaluation output is never accepted as PASS.

\`\`\`text
certified Step 03 run copy
        ↓
Verifier preflight (later orchestrator)
        ↓
pilot skill measured_ui_steps
        ↓
UFO Follower Mode plan
        ↓
isolated detached UFO worktree
        ↓
UIA-only pilot overlay
        ↓
UFO AppAgent + controller
        ↓
visible After Effects UI
        ↓
fresh AE Reader post-state
        ↓
deterministic Verifier
\`\`\`

## Existing UFO checkout

Step 04 does **not** clone or modify the user's working UFO folder.

The adapter expects an existing checkout, for example:

\`\`\`text
C:\Users\AL-BASHA\UFO
\`\`\`

Measured execution validates that the local Git repository contains the pinned upstream commit and that the audited blobs at that pinned commit match the lock. The user's current branch/HEAD does **not** need to be moved to the pinned commit, and local uncommitted work is not executed.

The actual run always uses a temporary detached Git worktree at the pinned commit. The original checkout is not modified by the adapter.

## Pinned upstream

\`\`\`text
repository: microsoft/UFO
commit: e2a03126241c696fdaf9a669a271ca3fca6d9916
mode: follower
\`\`\`

\`upstream_lock.json\` contains exact blob hashes for the audited upstream files.

Measured execution refuses:

- a local repository that does not contain the pinned UFO commit,
- missing audited files at that pinned commit,
- changed audited blobs at that pinned commit.

The source checkout may remain on another branch or contain local work because that source working tree is never used for measured execution.

The lock covers Follower Mode, plan parsing, session limits, UI controller actions, system configuration, and environment-specific configuration overlay behavior.

## Why Follower Mode

The pinned upstream implementation accepts a JSON plan containing:

\`\`\`json
{
  "task": "...",
  "steps": ["...", "..."],
  "object": "AfterFX.exe"
}
\`\`\`

\`FollowerSession\` reads those steps in order through \`PlanReader\`.

The adapter compiles directly from each skill's canonical:

- \`goal\`
- \`measured_ui_steps\`
- \`fixture_id\`

The measured steps are preserved verbatim.

The task instruction adds only the execution boundary: visible After Effects UI only; no scripts, expressions, COM, application APIs, shell commands, or direct \`.aep\` mutation.

## Critical upstream round-budget fix

The pinned upstream \`config/ufo/system.yaml\` defaults:

\`\`\`text
MAX_ROUND: 1
\`\`\`

Follower Mode uses its first round to select the target application and subsequent rounds for the supplied plan steps. Therefore the baseline value is not sufficient for our multi-step pilot plans.

The isolated pilot overlay sets:

\`\`\`text
MAX_ROUND = measured_step_count + 2
MAX_STEP  = max(50, measured_step_count * 12)
\`\`\`

This is applied only inside the temporary execution worktree.

## Measured-execution overlay

For every run the adapter creates:

\`\`\`text
config/ufo/system_test.yaml
\`\`\`

and starts UFO with:

\`\`\`text
UFO_ENV=test
\`\`\`

The overlay enforces:

\`\`\`yaml
CONTROL_BACKEND: ["uia"]
USE_APIS: false
USE_MCP: false
MCP_FALLBACK_TO_UI: false
EVA_SESSION: false
EVA_ROUND: false
TASK_STATUS: false
SAVE_EXPERIENCE: "always_not"
ASK_QUESTION: false
USE_CUSTOMIZATION: false
ENABLED_THIRD_PARTY_AGENTS: []
INPUT_TEXT_API: "type_keys"
CLICK_API: "click_input"
\`\`\`

This keeps the measured path on the visible Windows UI and removes UFO's API/MCP/evaluation/experience routes from the pilot execution.

The deterministic verifier remains the only success oracle.

## Fixture binding

UFO cannot run against an arbitrary \`.aep\`.

The adapter requires the Step 03 **disposable run copy** and checks:

- file exists,
- extension is \`.aep\`,
- filename matches the skill's \`fixture_id\`,
- parent folder equals the SHA-256-derived run workspace,
- actual fixture SHA-256 equals the certified run-copy hash.

The canonical fixture itself is rejected.

The fixture must already be loaded before measured UFO execution. Opening/preparing the fixture is not counted as a measured UFO action.

## Run identity

Each \`run_id\` is one-use only.

The adapter writes a persistent run registry record before execution. Deleting the run output directory does not make the ID reusable.

Every prepared run stores:

- skill ID,
- fixture ID,
- fixture path/hash,
- Follower plan,
- plan SHA-256,
- required UFO commit,
- timestamps,
- stdout/stderr,
- copied UFO logs when available,
- execution result.

## Validate all ten plans

\`\`\`bat
python -m ufo_adapter.cli validate-plans
\`\`\`

## Inspect one compiled plan

\`\`\`bat
python -m ufo_adapter.cli plan --skill-id AE-PILOT-004
\`\`\`

## Validate the existing UFO checkout

\`\`\`bat
python -m ufo_adapter.cli validate-checkout ^
  --ufo-checkout "C:\Users\AL-BASHA\UFO"
\`\`\`

This does not run UFO or change the checkout.

## Preview the measured command

Requires a Step 03 disposable fixture copy:

\`\`\`bat
python -m ufo_adapter.cli command ^
  --ufo-checkout "C:\Users\AL-BASHA\UFO" ^
  --skill-id AE-PILOT-004 ^
  --run-id AE-PILOT-004-RUN-1 ^
  --fixture-path "<run-copy>\FX-004-POSITION-READY.aep" ^
  --fixture-sha256 "<certified-copy-sha256>"
\`\`\`

Preview does not consume the run ID.

## Execute one measured plan

Execution requires an explicit arm flag:

\`\`\`bat
python -m ufo_adapter.cli execute ^
  --ufo-checkout "C:\Users\AL-BASHA\UFO" ^
  --skill-id AE-PILOT-004 ^
  --run-id AE-PILOT-004-RUN-1 ^
  --fixture-path "<run-copy>\FX-004-POSITION-READY.aep" ^
  --fixture-sha256 "<certified-copy-sha256>" ^
  --arm-measured-execution
\`\`\`

A zero UFO process exit code is **not PASS**. It is execution evidence only.

## Step boundary

Step 04 is responsible only for the UFO execution layer.

It does not:

- materialize fixtures,
- choose or benchmark the final model (Step 05),
- orchestrate the complete pre/post run lifecycle (later Runner step),
- assign pilot run status.

This separation keeps the lab auditable and prevents UFO from becoming its own judge.
