# Fixture System — Step 03

The fixture system creates, certifies, protects, and reproduces the ten canonical After Effects starting states used by the verification pilot.

It is deliberately separate from UFO and from measured skill execution.

## Core rule

A measured run may never start from an arbitrary project file.

The chain is:

```text
pilot_10_skills.yaml
        ↓
fixture spec compiler
        ↓
disposable AE fixture builder
        ↓
canonical .aep
        ↓
fresh AE Reader evidence
        ↓
deterministic state comparison
        ↓
CERTIFIED fixture record + SHA-256
        ↓
fresh per-run copy
        ↓
UFO measured run
```

## Ten canonical fixtures

The source of truth remains `fixture_specs` inside `pilot_10_skills.yaml`.

The system compiles all ten specifications instead of maintaining a second hand-written fixture definition.

Current fixture IDs:

- `FX-001-EMPTY-PROJECT`
- `FX-002-COMP-EMPTY`
- `FX-003-TEXT-TO-RENAME`
- `FX-004-POSITION-READY`
- `FX-005-SCALE-READY`
- `FX-006-OPACITY-READY`
- `FX-007-OPACITY-ANIMATION-READY`
- `FX-008-DUPLICATE-READY`
- `FX-009-REORDER-READY`
- `FX-010-EFFECT-READY`

## Safety boundary

The fixture builder is the one place in this repository that is intentionally allowed to mutate an After Effects project.

That mutation happens **before measured execution** and is limited to preparing disposable test projects.

The builder refuses to run unless the request contains:

```text
lab_mode = DISPOSABLE_FIXTURE_BUILD
```

The Python CLI additionally requires:

```text
--ack-disposable-ae-project
```

This acknowledgement matters because the fixture builder closes the currently open After Effects project without saving before constructing a fresh fixture.

Never run materialization while valuable work is open in After Effects.

## Specification validation

No After Effects installation is needed for this check:

```bat
python -m fixtures.cli validate-specs
```

The compiler rejects unsupported or contaminated baseline states, including:

- unsupported layer types,
- inconsistent layer indices,
- measured keyframes already present in a canonical fixture,
- measured effects already installed in a canonical fixture,
- invalid composition counts,
- invalid or incomplete composition settings.

## Inspect one build plan

```bat
python -m fixtures.cli plan --fixture-id FX-004-POSITION-READY
```

This prints the exact state that will be sent to the disposable AE builder.

## Live materialization

After Effects 26.x must be installed.

To build and certify one fixture:

```bat
python -m fixtures.cli materialize ^
  --fixture-id FX-004-POSITION-READY ^
  --ack-disposable-ae-project
```

To build and certify all ten:

```bat
python -m fixtures.cli materialize-all ^
  --ack-disposable-ae-project
```

A custom After Effects executable can be supplied with:

```bat
--afterfx-path "C:\Program Files\Adobe\Adobe After Effects 2026\Support Files\AfterFX.exe"
```

## What certification proves

A fixture is not certified merely because After Effects saved a file.

After each build, the system invokes AE Reader and requires:

1. Reader status `OK`.
2. Matching certification `run_id`.
3. Matching Reader `request_id`.
4. Fresh capture timestamp.
5. Expected Reader version/schema.
6. Saved project file identity matching the exact generated `.aep`.
7. Every canonical `required_state` field matching the live Reader state.
8. A SHA-256 hash of the generated binary.

Only then is a certification record written.

## Certification records

Live records are stored under:

```text
fixtures/certifications/
```

Each record binds:

- fixture ID,
- canonical relative path,
- exact SHA-256,
- byte size,
- pilot contract SHA-256,
- fixture required-state SHA-256,
- Reader version/schema,
- Reader request ID,
- certification run ID,
- capture time,
- AE application/build metadata,
- fixture builder result.

Changing the pilot contract, changing the required fixture state, or changing the `.aep` bytes invalidates the certification.

## Canonical fixture binaries

Certified files live under:

```text
fixtures/canonical/
```

Canonical files are never used directly for a measured run.

## Fresh run copies

Before a measured run:

```bat
python -m fixtures.cli create-run-copy ^
  --fixture-id FX-004-POSITION-READY ^
  --run-id AE-PILOT-004-RUN-1
```

The fixture manager:

1. re-validates certification,
2. re-hashes the canonical binary,
3. creates a run-specific directory from an opaque hash of `run_id`,
4. copies the canonical fixture,
5. re-hashes the copy,
6. rejects reused run IDs.

The disposable copies live under `fixtures/runs/` and are ignored by Git.

Remove one after a run:

```bat
python -m fixtures.cli remove-run-copy --run-id AE-PILOT-004-RUN-1
```

## Integrity status

```bat
python -m fixtures.cli status
```

A fixture reports `CERTIFIED` only when its record, current pilot contract, required state, file size, and SHA-256 still agree.

## Important distinction

GitHub CI can prove the fixture **system software** is correct and fail-closed.

GitHub CI cannot manufacture genuine `.aep` binaries because the runner does not contain Adobe After Effects.

Therefore:

- fixture specification/compiler/manager/builder orchestration: testable in CI,
- real `.aep` materialization/certification: requires the live Windows + After Effects 26.x lab.

No fixture should be called live-certified until the latter has actually run.
