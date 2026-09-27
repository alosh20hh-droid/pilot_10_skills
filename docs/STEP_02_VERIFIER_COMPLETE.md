# Step 02 — Deterministic Verifier

Status: **CODE COMPLETE**

This document closes Step 02 as one self-contained system. Step 03 (fixtures) must not be mixed into this step.

## Responsibility

The verifier is the final deterministic judge for one measured pilot run.

It does not control After Effects.
It does not drive UFO.
It does not infer success from screenshots or an agent FINISH message.

It consumes the locked pilot contract plus fresh AE Reader evidence and returns one allowed run status.

## Completed components

- strict pilot contract loader and invariant validation,
- fail-closed assertion path resolver,
- all eight assertion operators required by pilot format 1.2,
- canonical fixture partial-state comparison,
- locked environment preflight checks,
- run/request identity checks,
- Reader version/schema checks,
- Reader capability gating,
- runtime calibration gating,
- precondition verification,
- postcondition verification,
- stale-evidence rejection,
- evidence-backed UI_CHANGED classification,
- deterministic run-status classification,
- three-run skill aggregation,
- software self-calibration,
- real canonical-fixture pilot calibration interface,
- command-line interface,
- Windows CI,
- comprehensive unit tests,
- documentation.

## Allowed run outcomes

- PASS
- UI_CHANGED
- EXECUTION_FAILED
- VERIFICATION_FAILED
- BLOCKED
- INCONCLUSIVE

No other run status is accepted.

## Allowed skill outcomes

- VERIFIED
- NOT_VERIFIED
- NEEDS_REVIEW

A skill is VERIFIED only when all three required independent runs are PASS.

## False-PASS protections

The implementation refuses PASS when any of the following applies:

- missing or stale post evidence,
- mismatched run_id,
- missing or mismatched request_id,
- malformed Reader response,
- unexpected Reader version/schema,
- missing required capability,
- invalid fixture state,
- environment mismatch,
- missing runtime calibration,
- unknown assertion operator,
- ambiguous path selection,
- failed postcondition.

## Calibration

CI performs a software self-calibration:

- CAL-POSITIVE -> PASS
- CAL-NEGATIVE -> VERIFICATION_FAILED
- CAL-STALE -> INCONCLUSIVE

That self-calibration intentionally reports `satisfies_pilot_gate: false`.

The actual pre-pilot gate is implemented by `calibrate-pilot`, which must later consume a fresh AE Reader response from a materialized canonical fixture. That live evidence becomes possible only after Step 03 creates the fixture files.

## Integration boundary for later systems

Step 03 must provide materialized .aep fixtures matching `fixture_specs`.

Step 04 (UFO) will perform measured UI actions.

The later runner will supply the verifier with:

- skill_id,
- run_id,
- pre and post request_id,
- timestamps,
- locked environment evidence,
- runtime calibration,
- fresh AE Reader pre/post evidence,
- execution completion/failure evidence.

The verifier API and CLI are already ready for that integration.

## Acceptance gate

Step 02 is considered complete when the repository's Windows workflow passes all of:

1. dependency installation,
2. AE Reader self-check,
3. AE Reader contract alignment,
4. verifier contract validation,
5. verifier software calibration,
6. complete unit-test suite.

A real After Effects run is not claimed by this step. Runtime certification belongs to the applicable live system steps.
