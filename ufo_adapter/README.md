# UFO Step 04 Adapter

This package integrates a pinned Microsoft UFO checkout with the AE 10-skill pilot.

## Design

The adapter treats UFO as the execution body only.

It does not define success, does not modify fixture specifications, and does not replace AE Reader or the deterministic verifier.

```text
pilot skill
  -> compile exact measured_ui_steps
  -> Follower Mode plan
  -> locked UFO checkout
  -> UFO AppAgent + UI controller
  -> After Effects UI
```

Success is still decided later by AE Reader + Verifier.

## Pinned upstream

The adapter is pinned to:

```text
repository: microsoft/UFO
commit: e2a03126241c696fdaf9a669a271ca3fca6d9916
```

The audited files are recorded in `upstream_lock.json`.

The local checkout must:

- have exactly the locked HEAD commit,
- have a clean Git worktree,
- contain every audited source file,
- run on Windows.

Otherwise measured execution is refused.

## Mode

Only UFO `follower` mode is authorized.

The generated command is:

```text
python -m ufo --task <task> --mode follower --plan <plan.json> --log-level INFO
```

The adapter never emits `batch_normal`, `operator`, or `normal_operator` for measured AE execution.

This matches the audited upstream implementation where `SessionFactory` creates `FollowerSession`, which consumes the plan through `PlanReader`.

## Plan compilation

Each pilot skill is compiled directly from:

- `goal`
- `measured_ui_steps`
- `fixture_id`

The plan schema is:

```json
{
  "task": "<skill goal>",
  "steps": ["<measured UI step 1>", "..."],
  "object": "AfterFX.exe",
  "close": false
}
```

The compiler preserves `measured_ui_steps` verbatim. It does not invent recovery actions, scripts, APIs, or hidden automation.

## Observed controller capabilities in the pinned upstream

The audited UFO controller exposes mechanisms for:

- semantic control click,
- relative-coordinate click,
- relative-coordinate drag,
- keyboard input,
- key press,
- mouse movement,
- scrolling,
- text input,
- control annotation.

These are execution capabilities only. The pilot still forbids absolute coordinates as the sole targeting method and forbids scripting APIs for the measured skill.

## Validate plans

```bat
python -m ufo_adapter.cli validate-plans
```

This compiles all ten skills and reports their deterministic plan hashes.

## Inspect one plan

```bat
python -m ufo_adapter.cli plan --skill-id AE-PILOT-004
```

## Validate a local UFO checkout

```bat
python -m ufo_adapter.cli validate-checkout ^
  --ufo-checkout C:\path\to\UFO
```

A mismatched commit or dirty checkout is rejected.

## Prepare a command without executing UFO

```bat
python -m ufo_adapter.cli command ^
  --ufo-checkout C:\path\to\UFO ^
  --skill-id AE-PILOT-004 ^
  --run-id AE-PILOT-004-RUN-1
```

This creates the run-specific immutable plan and prints the exact command. UFO is not launched.

## Execute one measured plan

Execution is guarded by an explicit arming flag:

```bat
python -m ufo_adapter.cli execute ^
  --ufo-checkout C:\path\to\UFO ^
  --skill-id AE-PILOT-004 ^
  --run-id AE-PILOT-004-RUN-1 ^
  --arm-measured-execution
```

Run IDs cannot be reused.

Every run stores:

- generated plan,
- plan SHA-256,
- locked UFO commit,
- stdout,
- stderr,
- start/end timestamps,
- process exit code,
- execution result JSON.

These artifacts are execution evidence, not success evidence.

## Integration boundary

Before UFO runs, the later orchestrator must ensure:

1. a certified Step 03 run copy exists,
2. the expected fixture is loaded,
3. AE Reader pre-state is fresh,
4. Verifier preflight says the run may execute.

After UFO finishes:

1. capture a fresh AE Reader post-state,
2. pass the post-state and execution metadata to the deterministic verifier,
3. let the verifier assign the run status.

UFO's own FINISH/completion output never produces PASS by itself.
