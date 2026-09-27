# Four-System Audit — 2026-09-27

Scope:

1. AE Reader
2. Deterministic Verifier
3. Canonical Fixture System
4. UFO Execution Adapter

This audit reviewed the current `main` implementation and its cross-system contracts. The purpose was to look specifically for false-PASS paths, stale/wrong-project evidence, fixture contamination, run-identity reuse, and UFO execution routes that could escape the UI-only pilot contract.

## Result

The four software systems are internally consistent at repository level after the fixes listed below.

The Windows CI gate passed all checks and **91 unit tests** after the audit fixes.

Live After Effects/UFO runtime certification is still a separate gate and is not claimed by this document.

---

## 1. AE Reader

### Verified

- request-isolated IPC directories,
- unique request IDs,
- run/request/session identity checks,
- fail-closed stale-response handling,
- capture timestamp published after state collection,
- Reader/schema version binding,
- capability-manifest binding,
- read-only JSX boundary,
- all-layer capture,
- layer/property/keyframe/effect state,
- project-file identity through `project.file_path`,
- cleanup of request-registry entries after completion.

### Cross-system importance

`project.file_path` is now the identity anchor used by both fixture certification and verifier pre/post checks. A state snapshot from another project file cannot be accepted as proof for the intended disposable run fixture.

### Remaining live gate

The Reader still requires the real Windows + After Effects 26.x probe before runtime certification.

---

## 2. Deterministic Verifier

### Audit issues fixed

#### Post-state project identity

Previously, preflight bound the run to the expected fixture path, but post verification could evaluate a fresh Reader state without re-checking that it came from the same project file.

Fixed:

- post evidence must advertise `project.file_identity`,
- post `project.file_path` must match the exact preflight fixture path,
- mismatch returns `INCONCLUSIVE`, never `PASS`.

#### UI_CHANGED precedence

Previously, evidence-backed `UI_CHANGED` could override a completed execution even when deterministic postconditions could still be verified.

Fixed:

- `UI_CHANGED` is used only when measured execution did not complete because the stored UI route changed,
- completed execution proceeds to normal post verification and may earn `PASS`.

#### Exact After Effects build pin

The pilot contract requires `record_and_pin_for_pilot_batch`, but the verifier previously allowed callers to omit the pinned exact build.

Fixed:

- missing exact build pin now blocks preflight with `AE_BUILD_PIN_REQUIRED`,
- mismatched build remains `BLOCKED`.

#### Malformed Reader error arrays

Reader evidence now requires the `errors` array to contain strings only.

### Verified fail-closed behavior

- stale evidence cannot pass,
- wrong run/request identity cannot pass,
- missing Reader capability cannot pass,
- wrong fixture state cannot execute,
- wrong fixture file cannot execute,
- wrong post fixture cannot pass,
- unknown assertion operators cannot pass,
- only three independent PASS runs produce VERIFIED.

---

## 3. Canonical Fixture System

### Verified

- one source of truth: `fixture_specs` in `pilot_10_skills.yaml`,
- disposable-only AE mutation boundary,
- canonical build followed by Reader read-back,
- project-file identity binding,
- post-save freshness requirement,
- state comparison before certification,
- SHA-256 binding,
- contract and required-state hashes,
- failed certification removes the untrusted canonical file,
- measured runs use copies rather than canonical files.

### Audit issue fixed: persistent run identity

Previously, run-ID reuse was rejected only while the disposable run directory still existed. Deleting the run copy could make the same run ID usable again.

Fixed:

- every successful fixture run-copy reservation creates a persistent local run-ID registry marker,
- deleting the disposable `.aep` copy does not delete the run-ID marker,
- the same run ID cannot be reused later.

This directly enforces the pilot's unique-run-ID contract.

### Remaining live gate

The ten real `.aep` files still need to be materialized and certified on the real Windows + After Effects 26.x machine.

---

## 4. UFO Execution Adapter

### Audit issues fixed

#### Duplicate implementations

The repository contained two lock implementations and two plan compilers with different contracts.

Fixed:

- one active lock: `ufo_adapter/upstream_lock.json`,
- one lock implementation: `ufo_adapter/lock.py`,
- one plan compiler: `ufo_adapter/plan.py`,
- obsolete duplicate lock/compiler files removed.

#### Stronger upstream provenance

The active lock now binds:

- pinned UFO commit,
- audited source-file set,
- exact Git blob SHA for every audited upstream file.

Local checkout validation checks both the commit and audited blobs.

#### UI-only plan enforcement

The active plan compiler now rejects measured steps that request prohibited routes such as:

- ExtendScript / JSX,
- shell or PowerShell,
- COM/application APIs,
- expressions,
- direct `.aep` mutation,
- absolute screen coordinates as the sole locator.

The authored measured steps remain verbatim. A separate task-level guard tells UFO to use visible UI interaction only.

#### Fixture loading boundary

A temporary implementation bound the UFO plan `object` to the `.aep` path, which could make opening the fixture part of measured execution.

Fixed:

- the plan remains bound to `AfterFX.exe`,
- fixture loading stays in preflight, before measured UFO actions,
- the runner still verifies the fixture path and SHA-256.

#### Run-specific fixture enforcement

The UFO runner now requires the supplied fixture to live in the run-specific workspace whose directory name is derived from that run ID.

This prevents pointing measured execution at the canonical fixture.

#### Persistent UFO run identity

Like the fixture system, UFO now reserves run IDs in a persistent local registry. Removing a run log directory does not make the run ID reusable.

### Remaining live gate

The adapter is repository-tested, but one real Follower Mode run against the pinned UFO checkout and After Effects UI is still required before runtime certification.

---

## Repository gate after audit

Passing workflow:

- AE Reader self-check
- Reader/contract alignment
- Verifier contract validation
- Verifier calibration
- Fixture specification validation
- UFO plan validation
- Unit tests

Final observed test result:

```text
Ran 91 tests
OK
```

## What is still intentionally unproven

These are not repository-code failures:

1. Reader behavior against the user's installed AE 26.x build.
2. Ten genuine certified `.aep` fixtures.
3. UFO's live ability to execute the pilot UI steps in AE.
4. The model/provider layer that will become Step 05.
5. Full end-to-end 30-run pilot orchestration.

Those require the live Windows lab and later project steps.
