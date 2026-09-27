# Step 03 — Canonical Fixture System

Status: **CODE COMPLETE / LIVE MATERIALIZATION GATE PENDING**

This document closes the software-build portion of Step 03 as one self-contained system. Step 04 (UFO) must not be mixed into this step.

## Responsibility

The fixture system owns the trusted starting state for every measured skill run.

It does not execute the skill under test.
It does not judge success.
It does not replace AE Reader or the deterministic verifier.

Its responsibility is:

1. compile the ten canonical fixture specifications from `pilot_10_skills.yaml`,
2. construct a disposable After Effects project matching one specification,
3. save the canonical `.aep`,
4. read it back through AE Reader,
5. prove the live state matches the canonical specification,
6. bind the proof to the exact project file path and SHA-256,
7. create a certification record,
8. produce a fresh, hash-verified per-run copy for later UFO execution.

## Completed components

- fixture spec compiler driven directly by `fixture_specs`,
- validation for all ten source specifications,
- generic ExtendScript fixture constructor,
- hard disposable-project mutation guard,
- explicit user acknowledgement gate before destructive AE setup,
- Windows After Effects builder orchestration,
- read-back certification through AE Reader,
- saved-project file identity binding,
- post-save freshness binding,
- canonical state comparison through the deterministic verifier,
- SHA-256 binary integrity records,
- pilot contract hash binding,
- per-fixture required-state hash binding,
- portable canonical relative-path records,
- resumable multi-fixture materialization,
- cleanup of untrusted binaries after failed certification,
- canonical integrity re-validation,
- unique fresh run-copy creation,
- run-id reuse rejection,
- disposable run-copy cleanup,
- command-line interface,
- Windows CI,
- comprehensive unit tests,
- operational documentation.

## Canonical artifact policy

A `.aep` file is **not** canonical merely because the builder saved it.

It becomes usable only after:

```text
BUILD
  -> SAVE
  -> FRESH AE READER READ
  -> PROJECT FILE IDENTITY MATCH
  -> REQUIRED STATE MATCH
  -> SHA-256
  -> CERTIFICATION RECORD
```

If certification fails, the newly built untrusted canonical binary is removed.

## Fresh-run policy

Measured runs never modify the certified canonical file.

Every run gets a new copy only after the source binary and certification record are re-validated.

Reusing the same `run_id` is rejected.

## Safety boundary

Fixture construction is explicitly outside measured execution and may use the After Effects scripting API only to create the disposable starting project.

The builder refuses to run unless both layers of intent are present:

- request mode: `DISPOSABLE_FIXTURE_BUILD`
- CLI acknowledgement: `--ack-disposable-ae-project`

The current AE project may be closed without saving during materialization. Valuable work must not be open.

## CI acceptance gate

The Windows workflow must pass:

1. dependency installation,
2. AE Reader self-check,
3. Reader contract alignment,
4. verifier contract validation,
5. verifier software calibration,
6. fixture specification validation,
7. complete unit-test suite.

## Live materialization gate

GitHub CI cannot create genuine Adobe After Effects project files because Adobe After Effects is not installed on the hosted runner.

Therefore the **software system is complete**, but Step 03 must not be described as having ten live-certified `.aep` artifacts until this is run on the real Windows + After Effects 26.x lab:

```bat
python -m fixtures.cli materialize-all --ack-disposable-ae-project
```

Successful completion must produce ten certified canonical binaries and ten certification records.

After that:

```bat
python -m fixtures.cli status
```

must report all ten fixtures as `CERTIFIED`.

## Integration boundary for Step 04

UFO will receive only a disposable per-run copy created by this fixture system.

UFO must never receive permission to alter the canonical fixture directory or certification records.
