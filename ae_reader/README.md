# AE Reader v2

This folder contains the read-only After Effects state reader used by the 10-skill verification pilot.

Current reader version: `2.0.0`

Current schema version: `2`

## Purpose

The reader is the measurement side of the lab. It does not perform the skill under test.

Its job is to capture fresh, machine-readable After Effects state so a deterministic verifier can decide whether the UI operation really produced the expected result.

## Architecture

```
pilot run
  -> Python observer
  -> isolated request directory
  -> AfterFX.exe -r read_state.jsx
  -> read-only AE DOM inspection
  -> response.json
  -> typed Python schema
  -> pilot-shaped state
  -> deterministic verifier
```

Each request receives its own directory under the IPC root. The directory contains only the files needed for that request:

- `request.json`
- `capabilities.json`
- `read_state.jsx`
- `json2.jsx`
- `response.json` after AE replies

The request directory is keyed by an opaque hash of `run_id` plus a unique `request_id`.

## What v2 reads

- application version/build/language when exposed by AE,
- project item and composition counts,
- active composition identity/settings/current time,
- every layer in the active composition,
- persistent layer ID when exposed by AE,
- layer index/order,
- layer selection/lock/enabled flags,
- layer type,
- source text,
- in/out/start timing,
- Position including separated dimensions,
- Scale,
- Opacity,
- keyframe count/time/frame/value,
- effects,
- effect `matchName`,
- recursive effect property identity/value/keyframes.

## Stable identity

Verification should prefer After Effects internal `matchName` values over localized display labels.

Examples used by the external reference audit:

- Gaussian Blur effect: `ADBE Gaussian Blur 2`
- Blurriness property: `ADBE Gaussian Blur 2-0001`

Display names are retained for diagnostics only.

## Read-only guarantee

`read_state.jsx` contains no project mutation calls.

The test suite rejects known mutation operations such as property setters, effect insertion, layer duplication/reordering, command execution, and undo-group mutation flows.

File writes are limited to IPC output and are not project mutation.

## Capability manifest

`capabilities.json` is the single declared-capability source.

The same manifest is:

1. loaded by Python,
2. copied into the request directory,
3. returned by the JSX response,
4. compared byte-for-meaning by Python.

A mismatched manifest causes `INVALID_RESPONSE`.

## Freshness and identity

A response is rejected if:

- `request_id` differs,
- `run_id` differs,
- legacy session/lesson/step identity differs when supplied,
- `captured_at` predates the request,
- schema or reader version is unexpected,
- capability manifest differs,
- typed parsing fails.

## Local checks

From the repository root:

```bat
python -m ae_reader.cli self-check
python -m unittest discover -s tests -v
```

Print the capability manifest:

```bat
python -m ae_reader.cli manifest
```

## Live Windows probe

After Effects must be installed and scripting must be allowed.

The observer searches normal Adobe installation paths automatically. A specific executable can also be supplied:

```bat
python -m ae_reader.cli --afterfx-path "C:\Program Files\Adobe\Adobe After Effects 2026\Support Files\AfterFX.exe" probe --run-id AE-R2-LIVE-001 --timeout 15
```

If AE is installed in a non-standard location, either use `--afterfx-path` or set:

```bat
set UFO_AFTERFX_PATH=C:\full\path\to\AfterFX.exe
```

For a failed probe where the raw IPC directory should remain for inspection:

```bat
python -m ae_reader.cli probe --run-id AE-R2-LIVE-FAIL-001 --retain-failed-request
```

## Pilot adapter

`AEStateSnapshot.to_pilot_state()` converts the reader-native representation to the normalized structure expected by `pilot_10_skills.yaml`.

This keeps raw AE details separate from the test contract.

## Compatibility

The original AE-R1 positional call shape is preserved:

```python
observer.read_state(session_id, lesson_id, step_id)
```

New pilot code should instead use an explicit run ID:

```python
observer.read_state(run_id="pilot-skill-004-run-1")
```

or:

```python
observer.read_pilot_state("pilot-skill-004-run-1")
```

## Current certification level

The repository-level reader is code-complete for the capabilities required by the 10-skill pilot.

It is not yet runtime-certified against the user's real Windows + After Effects 26.x installation. That requires the live AE-R2 probe described in `docs/AE_READER_AUDIT.md`.
