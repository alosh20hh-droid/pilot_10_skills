# Step 04 — UFO Execution Adapter

Status: **CODE COMPLETE / LIVE UFO+AE GATE PENDING**

This closes the software-build portion of Step 04 as a separate system.

## Responsibility

UFO is the execution body of the validation lab.

It receives only the already-authored UI steps for one skill and drives After Effects through the Windows UI.

It is not the source of truth for success.

## Completed

- pinned Microsoft UFO upstream commit,
- source audit of upstream CLI, FollowerSession, PlanReader, SessionFactory, and UI controller,
- clean-checkout and exact-commit enforcement,
- Follower Mode-only authorization,
- explicit rejection of measured batch/operator modes,
- deterministic compiler for all ten pilot skills,
- exact preservation of `measured_ui_steps`,
- fixed AE target object `AfterFX.exe`,
- deterministic plan SHA-256,
- unique run directories,
- run-id reuse rejection,
- explicit measured-execution arming gate,
- stdout/stderr/process result capture,
- start/end timestamps and exit code capture,
- Windows-only live execution gate,
- CLI for plan inspection, compile-all, checkout validation, command preparation, and measured execution,
- Windows CI and unit tests,
- operational documentation.

## Fail-closed boundaries

Measured execution is refused when:

- the local UFO checkout is not the pinned commit,
- the local UFO worktree is dirty,
- an audited upstream source file is missing,
- execution is not on Windows,
- the adapter is not armed explicitly,
- the same run_id already has an execution workspace,
- the source pilot is no longer UI_ONLY.

## Live gate

CI proves the adapter software and plan contracts, but it does not prove that the pinned UFO model/provider can operate the real After Effects UI on the user's machine.

The remaining live Step 04 gate is:

1. materialize/certify the needed Step 03 fixture,
2. create a fresh run copy,
3. load that run copy in AE 26.x,
4. validate the pinned local UFO checkout,
5. execute one low-risk pilot skill through Follower Mode,
6. capture UFO logs,
7. use AE Reader + Verifier to prove the resulting AE state.

Until this live gate passes, the adapter is code-complete but not runtime-certified.

## Boundary to the next step

The next system is the model/provider layer. It must plug into this fixed UFO execution contract and be compared on the same skills; it must not change the fixture, Reader, verifier, or plan contract merely to make a model look successful.
