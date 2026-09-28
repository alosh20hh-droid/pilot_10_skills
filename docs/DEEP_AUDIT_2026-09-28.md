# Deep Repository Audit — 2026-09-28

Scope: the complete current implementation of the first four pilot systems:

1. AE Reader
2. Deterministic Verifier
3. Canonical Fixture System
4. Microsoft UFO² Execution Adapter

This is a repository-level software audit. It does not claim that the live Windows + After Effects + UFO runtime gates have passed.

## Audit method

The audit re-read the current source, cross-checked contracts between subsystems, reviewed the pinned Microsoft UFO source paths used by Step 04, looked specifically for false-PASS and provenance gaps, added regression tests for every material issue found, and reran Windows GitHub Actions after code changes.

The latest code-bearing audit commit with a complete green CI run is:

```text
29cc9d749ab0aefc9af56cea23cc0c13ac96c76a
```

Passing workflow:

```text
https://github.com/alosh20hh-droid/pilot_10_skills/actions/runs/36409267513
```

Observed result:

```text
Ran 160 tests
OK
```

Later commits after that point are documentation-only.

## High-value defects found and fixed

### 1. Verifier freshness boundary accepted a non-finite boundary

A non-finite freshness boundary such as NaN could make the stale comparison ineffective.

Fixed:

- both Reader capture time and the supplied freshness boundary must be finite numbers,
- malformed boundaries are rejected rather than interpreted as fresh,
- live calibration has a regression test for this case.

### 2. Runtime selector variables could shadow literal layer names

The path resolver previously substituted any selector value that happened to match a runtime key.

Example risk:

```text
layer[name=PILOT_TEXT]
```

could be reinterpreted if a runtime dictionary happened to contain a key named `PILOT_TEXT`.

Fixed:

- runtime substitution is permitted only for `stable_id=...` selectors,
- literal layer names remain literal,
- regression test added.

### 3. Assertion contracts were under-validated

The source contract validated operator names, but malformed operands could survive until runtime.

Fixed validation now covers:

- required `value` fields,
- finite/non-negative tolerances,
- non-negative integer counts,
- layer-identity fields,
- keyframe frame/time/value shapes,
- runtime calibration keys,
- stable-ID path tokens,
- Reader capabilities implied by each assertion.

Malformed contracts are rejected before execution.

### 4. Reader transform normalization could coerce booleans to numbers

Python booleans are integers, so malformed transform values such as `True` could previously normalize to `1.0`.

Fixed:

- Position, Scale, and Opacity normalization accepts only finite numeric non-boolean values,
- malformed booleans become unavailable evidence rather than numeric evidence,
- regression test added.

### 5. Reader project composition counting silently ignored item-read failures

The project composition counter previously swallowed per-item read errors. In an extreme case this could undercount compositions and make an expected zero-composition state look valid.

Fixed:

- project item enumeration now fails closed,
- missing/unreadable project items make the Reader response invalid,
- regression test added.

### 6. Missing AE effect group was treated as an empty effect list

A missing/unreadable `ADBE Effect Parade` could previously look identical to a valid empty effect collection.

Fixed:

- missing effect-group access is now a Reader failure,
- valid empty effect groups still return an empty list,
- regression test added.

### 7. Step 03 → Step 04 fixture provenance was not strong enough

The UFO adapter previously checked that a fixture:

- lived in a hash-named directory,
- had the right filename,
- matched a caller-supplied hash.

A hand-created file could imitate that directory shape.

Fixed:

Step 03 now persists a `READY` run-registry record containing:

- run ID,
- run key,
- fixture ID,
- canonical SHA-256,
- run-copy SHA-256,
- exact run-copy path,
- certified AE build identity.

Step 04 now requires that registry and checks it against the actual bytes.

An unregistered hashed directory no longer qualifies as a trusted Step 03 fixture.

### 8. Fixture run-copy public API temporarily regressed during provenance hardening

The new provenance record renamed the returned `path` field to `copy_path`, breaking an existing test/caller contract.

Fixed immediately:

- persistent registry uses `copy_path`,
- public return value preserves the existing `path` alias,
- CI returned green.

### 9. Canonical fixture certification path was too permissive

Certification records could theoretically omit the canonical relative path.

Fixed:

- certification is allowed only for `fixtures/canonical/<fixture_id>.aep`,
- `canonical_relpath` is mandatory,
- verification rejects missing or mismatched canonical paths,
- regression tests added.

### 10. Fixture certification did not propagate exact AE build provenance far enough

The builder and Reader already had build metadata, but the disposable run-copy provenance did not carry a single exact build identity into Step 04.

Fixed:

- canonical certification derives and stores an exact AE build identity,
- builder and Reader build identities must agree,
- Step 03 run registry carries `certified_ae_build_identity`,
- Step 04 execution provenance carries the same identity,
- regression tests added.

### 11. UFO runner accepted arbitrary UFOPlan objects from API callers

The CLI compiled canonical plans, but the runner API itself could receive a modified `UFOPlan` with extra steps or a different application object.

Fixed:

- immediately before fixture binding, Step 04 recompiles the canonical plan from `pilot_10_skills.yaml`,
- skill ID, fixture ID, payload, and SHA-256 must match,
- extra steps and rebound application objects are rejected,
- regression tests added.

### 12. Detached UFO worktree integrity was not explicitly checked

The pinned commit was verified before worktree creation, but an unexpected checkout-time modification could theoretically contaminate the detached worktree.

Fixed:

- detached worktree HEAD must equal the pinned commit,
- it must be clean before the pilot overlay,
- after overlay, exactly one tracked modification is allowed: `config/ufo/mcp.yaml`,
- exactly one untracked file is allowed: `config/ufo/system_test.yaml`,
- any other worktree modification aborts execution,
- regression test added.

### 13. UFO UI-only boundary needed a more accurate MCP model

The prior wording implied that MCP was completely removed. In pinned UFO, local UI collection/action tools themselves use internal MCP transport.

Fixed architecture:

- non-UI API/MCP/command-line/COM/hardware routes are disabled,
- temporary `mcp.yaml` exposes only:
  - `UICollector`
  - `HostUIExecutor`
  - `AppUIExecutor`
- command-line, COM, hardware, Bash, mobile, and other namespaces are absent,
- the policy and relevant upstream routing files are pinned and tested.

### 14. Dependency and syntax reproducibility was weaker than necessary

Fixed:

- PyYAML is pinned to `6.0.3`,
- Windows CI now includes a Python compile gate before subsystem tests.

### 15. Documentation had drifted from the code

Fixed examples and descriptions include:

- live verifier calibration now documents mandatory `--fixture-path`,
- verifier bundle documentation includes exact fixture identity and build identity,
- fixture docs include certified build/run provenance,
- UFO docs describe internal UI-MCP transport accurately,
- duplicate stale Step 04 completion document removed,
- the 2026-09-27 audit is explicitly marked historical.

## Current repository-level conclusions

### AE Reader

Repository-level properties now enforced:

- read-only project observation,
- isolated request IPC,
- run/request/freshness binding,
- application/build/language metadata,
- project-file identity,
- project/composition/layer cross-object consistency,
- finite numeric timestamps/transforms,
- exact-frame keyframe behavior,
- fail-closed effect and project enumeration,
- all required pilot state normalized for the verifier.

Live AE26 runtime proof is still required.

### Deterministic Verifier

Repository-level properties now enforced:

- exact format-1.2 baseline contract,
- exactly ten skills and fixtures,
- exactly three runs for verification,
- locked environment/tolerances,
- strict assertion shapes,
- assertion-to-capability consistency,
- exact run/request/fixture/build identity,
- immutable preflight runtime calibration,
- stale/malformed/ambiguous evidence cannot PASS,
- UFO completion cannot PASS by itself,
- only three PASS runs produce VERIFIED.

### Canonical Fixture System

Repository-level properties now enforced:

- single source of truth from `fixture_specs`,
- disposable-only build mutation,
- canonical-path-only certification,
- post-save Reader read-back,
- exact file/state/build/language binding,
- binary SHA-256,
- contract and required-state hashes,
- persistent one-use run registry,
- run-copy path/hash/build provenance,
- failed certification does not leave a trusted canonical file.

The ten actual AE project binaries still need live materialization.

### UFO² Execution Adapter

Repository-level properties now enforced:

- pinned upstream commit and audited blobs,
- Follower Mode only,
- canonical plan recompilation before execution,
- canonical Step 03 fixture provenance,
- one-use run identity,
- detached pinned worktree,
- clean-worktree check,
- tightly bounded overlay changes,
- UIA control backend,
- UI-only local tool namespaces,
- no success judgment from UFO,
- process/log/provenance capture.

A real Follower run in After Effects still needs the live gate.

## What remains intentionally unproven

These are the remaining live/system-integration gates, not repository-code claims:

1. AE Reader against the actual installed AE 26.x build.
2. Materialization and certification of all ten real `.aep` fixtures.
3. The exact model/provider configuration for UFO (Step 05).
4. One real measured UFO Follower execution through After Effects.
5. The integrated Runner that performs preflight → UFO → post-read → verifier.
6. The final 30 independent measured runs.

## Audit disposition

No repository-level PASS claim is based only on documentation or agent output. The code-bearing audited state passed the Windows CI gate with 160 tests. Live runtime certification remains explicitly separate.
