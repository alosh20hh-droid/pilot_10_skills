# Deterministic Verifier — Step 2

This package is the final judge for the AE 10-skill verification pilot.

It does **not** control After Effects and it does **not** decide how UFO should perform a skill. Its only job is to decide whether a measured run may start and whether the observed result is proven by fresh AE Reader evidence.

## Decision pipeline

```
pilot skill specification
        +
canonical fixture
        +
locked environment evidence
        +
fresh AE Reader pre-state
        |
        v
    PREFLIGHT
        |
        |-- mismatch / missing capability / stale evidence --> BLOCKED
        |
        v
UFO measured UI execution
        |
        v
fresh AE Reader post-state
        |
        v
deterministic assertions
        |
        |-- all pass ------------------------------> PASS
        |-- fresh state disproves expectation ----> VERIFICATION_FAILED
        |-- missing/stale/malformed evidence -----> INCONCLUSIVE
        |-- measured UI sequence cannot finish ---> EXECUTION_FAILED
        |-- evidence-backed route/layout change --> UI_CHANGED
```

A skill becomes `VERIFIED` only after exactly three independent `PASS` runs.

## Fail-closed rules

The verifier never accepts:

- the agent saying it finished,
- screenshots alone when AE Reader can inspect the state,
- stale pre- or post-state,
- a different `run_id`,
- a different `request_id`,
- an unexpected Reader version/schema,
- a missing required Reader capability,
- a malformed fixture,
- an unknown assertion operator,
- an ambiguous filtered path,
- a missing runtime calibration value,
- an environment that violates the locked pilot contract.

## Supported assertion operators

Exactly the operators declared in `pilot_10_skills.yaml` are implemented:

- `eq`
- `approx`
- `count_eq`
- `contains_layer`
- `not_contains_layer_name`
- `count_layer_name`
- `contains_keyframe`
- `contains_effect_stable_id`

Unknown operators are a contract error and cannot silently pass.

## Assertion paths

The resolver understands the pilot path language, including:

```text
project.composition_count
active_comp.name
layers[0].type
layer[name=PILOT_TEXT].transform.position.x
layer[name=PILOT_TEXT].properties.opacity.keyframes
layer[name=PILOT_TEXT].effects[stable_id=stable_effect_id].property[display_name=Blurriness].value
```

`layer[...]` aliases the root `layers` list and `property[...]` aliases an effect's `properties` list.

A filter must resolve to exactly one object. Zero matches are missing evidence; multiple matches are ambiguous evidence.

## Preflight

`DeterministicVerifier.verify_preflight()` checks:

1. locked Windows/display/After Effects/workspace environment,
2. pinned AE build when one has already been selected,
3. fresh Reader identity and timestamp,
4. Reader version and schema,
5. required Reader capabilities,
6. required runtime calibration values,
7. the complete canonical fixture partial-state,
8. every skill precondition assertion.

If any check fails, the skill must not execute and the run is `BLOCKED`.

## Post verification

`DeterministicVerifier.verify_post()` checks:

1. preflight succeeded,
2. no later blocking condition was reported,
3. explicit UI-change evidence if `UI_CHANGED` is claimed,
4. the measured execution completed,
5. post-state exists and is fresh after the last measured action,
6. every postcondition assertion.

Only step 6 passing in full can produce `PASS`.

## Skill aggregation

`aggregate_skill()` implements the pilot aggregate contract:

- `PASS, PASS, PASS` → `VERIFIED`
- completed execution/verification failure with no unresolved ambiguity → `NOT_VERIFIED`
- `UI_CHANGED`, `BLOCKED`, `INCONCLUSIVE`, or incomplete run count → `NEEDS_REVIEW`

## Calibration

There are two deliberately separate calibration levels.

### Software self-calibration

CI runs:

```bat
python -m verifier.cli calibrate
```

This proves the verifier software itself can accept a known-correct synthetic state, reject a deliberately false expectation, and reject stale evidence. It must produce:

```text
CAL-POSITIVE  -> PASS
CAL-NEGATIVE  -> VERIFICATION_FAILED
CAL-STALE     -> INCONCLUSIVE
```

This check is useful, but it **does not satisfy the real pilot gate** because it does not read an actual canonical After Effects fixture.

### Pilot evidence calibration

After Step 3 creates and proves a canonical fixture, capture a fresh AE Reader response from that fixture and run:

```bat
python -m verifier.cli calibrate-pilot ^
  --evidence calibration-evidence.json ^
  --fixture-id FX-002-COMP-EMPTY ^
  --run-id CAL-LIVE-001 ^
  --request-id <the-reader-request-id> ^
  --fixture-path "<exact-canonical-fixture-path>" ^
  --fresh-after <run-start-timestamp>
```

Only this mode can return `satisfies_pilot_gate: true`.

It performs the contract's three controls against the same real fixture evidence:

- positive: the fresh state must match the canonical fixture,
- negative: the verifier injects a deliberately false expected composition count without changing AE,
- stale: the same response is replayed against a deliberately wrong request identity.

Neither calibration mode mutates After Effects.

## Validate the source contract

```bat
python -m verifier.cli validate-contract
```

This checks that all ten skills, ten fixtures, statuses, capabilities, and assertion operators are internally compatible with the verifier.

## Verify a complete run

The future runner will create a JSON bundle and call:

```bat
python -m verifier.cli verify-run --bundle run.json
```

Bundle shape:

```json
{
  "skill_id": "AE-PILOT-004",
  "run_id": "AE-PILOT-004-RUN-1",
  "pre_request_id": "reader-pre-id",
  "post_request_id": "reader-post-id",
  "run_started_at": 100.0,
  "last_action_at": 120.0,
  "expected_ae_build": "26.x build pinned by pilot",
  "environment": {
    "operating_system": "Windows",
    "after_effects_process_running": true,
    "unknown_modal_dialog": false,
    "display_resolution": "1920x1080",
    "display_scaling_percent": 100,
    "ae_major_version": 26,
    "ae_language": "en-US",
    "workspace_id": "PILOT_WORKSPACE",
    "ae_build": "26.x build pinned by pilot"
  },
  "runtime": {},
  "pre_evidence": {},
  "execution_completed": true,
  "post_evidence": {}
}
```

For skill 10, `runtime` must include a calibrated `stable_effect_id`.

## Tests

```bat
python -m pip install -r requirements.txt
python -m verifier.cli validate-contract
python -m verifier.cli calibrate
python -m unittest discover -s tests -v
```

GitHub Actions runs the same checks on Windows.

## Boundary

This verifier is complete as a deterministic software component. It does not make live claims about After Effects, UFO, UI Automation, or fixtures that have not yet been tested in their own project steps.
