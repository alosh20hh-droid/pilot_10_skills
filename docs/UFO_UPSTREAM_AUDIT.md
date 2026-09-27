# Microsoft UFO upstream audit for Step 04

Pinned source:

- repository: `microsoft/UFO`
- commit: `e2a03126241c696fdaf9a669a271ca3fca6d9916`

Audited files:

- `ufo/ufo.py`
- `ufo/module/session_pool.py`
- `ufo/module/sessions/plan_reader.py`
- `ufo/module/sessions/session.py`
- `ufo/automator/ui_control/controller.py`

## Findings

### CLI

The pinned `ufo/ufo.py` accepts:

- `--task`
- `--mode`
- `--plan`
- `--request`
- `--log-level`

Follower execution is documented upstream as:

```text
python -m ufo -t <task> -m follower -p <plan>
```

The pilot adapter emits the equivalent long-form flags.

### Follower session

`SessionFactory` selects `FollowerSession` when mode is exactly `follower`.

If the plan path is a folder, upstream can create a sequence of Follower sessions. The pilot deliberately uses one explicit plan file per measured run to preserve run identity and evidence boundaries.

### Plan contract

`PlanReader` reads JSON and consumes:

- `task`
- `steps`
- `object`
- optional `close`

`FollowerSession` uses the first round to select/open the target application and later rounds consume the authored plan steps sequentially.

### Why batch mode is not used

The pinned `FromFileSession` / batch path contains explicit Word/Excel/PowerPoint application mappings and an allowlist around those applications. That is not the correct execution route for After Effects.

The pilot therefore authorizes only Follower Mode for AE.

### Controller

The pinned UI controller exposes both semantic UI Automation interaction and coordinate-relative fallback behavior, including click, drag, keyboard, key press, mouse movement, scroll, text input, and annotation mechanisms.

This is sufficient as an execution substrate for the pilot, but the adapter does not treat those capabilities as proof of successful AE behavior. Live behavior must be tested on Windows + AE.

## Pilot design consequence

The Step 04 adapter does not fork or patch Microsoft UFO.

It:

1. locks a known upstream commit,
2. rejects dirty/mismatched checkouts,
3. compiles the pilot's measured UI steps into upstream Follower plans,
4. launches the upstream package unchanged,
5. captures process-level execution evidence,
6. leaves success judgment to AE Reader + deterministic verifier.
