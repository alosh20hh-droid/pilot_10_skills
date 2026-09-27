# AE Reader audit: local AE-R1 vs Adobe Agent Skills

Audit date: 2026-09-27

External reference pinned for this audit:

- Repository: `aedev-tools/adobe-agent-skills`
- Commit: `00f131ee5481cd597e6f63f997d92c6fe26586a0`
- Relevant files:
  - `skills/after-effects/scripts/active-state.jsx`
  - `skills/after-effects/scripts/project-overview.jsx`
  - `skills/after-effects/scripts/comp-detail.jsx`
  - `skills/after-effects/scripts/layer-detail.jsx`
  - `skills/after-effects/scripts/lib/utils.jsx`
  - `skills/after-effects/scripts/lib/json2.jsx`
  - rules for ExtendScript, layers, keyframes, effects, and compositions

The external project is Apache-2.0 licensed. Its bundled `json2.jsx` is public-domain code. This repository vendors only the public-domain JSON parser; the AE Reader implementation remains purpose-built for this pilot.

## Executive finding

The original local AE-R1 reader had the stronger verification architecture, while Adobe Agent Skills had broader After Effects state coverage.

The correct design is therefore not to replace AE-R1. AE-R1 remains the transport, freshness, identity, and fail-closed foundation, and selected read-only ideas from Adobe Agent Skills are incorporated into AE Reader v2.

## Comparison

| Area | Original local AE-R1 | Adobe Agent Skills query scripts | AE Reader v2 |
|---|---|---|---|
| Windows execution | Yes, via `AfterFX.exe -r` | No; runner is macOS/JXA | Yes |
| Request isolation | Per request directory | Shared `/tmp` files | Per run + per request directory |
| Request identity | request/session/lesson/step | None | request + run; legacy IDs retained |
| Freshness check | Yes | No | Yes, fail-closed |
| Typed Python schema | Yes | No | Yes, schema v2 |
| Capability manifest | No | No | Yes, single-source JSON manifest |
| All layers | No, selected layers only | Yes | Yes |
| Layer persistent ID | No | No | Yes when AE exposes `layer.id` |
| Layer index/order | Yes for selected layers | Yes | Yes for all layers |
| Source text | No | Yes | Yes |
| Position | Yes | Yes | Yes, including separated dimensions |
| Scale | Yes | Yes | Yes |
| Opacity | Yes | Yes | Yes |
| Keyframe count | Yes | Yes | Yes |
| Keyframe time | Seconds | Seconds | Seconds + frame number |
| Keyframe values | Yes | Yes | Yes |
| Layer in/out/start timing | No | Yes | Yes |
| Effects list | No | Yes | Yes |
| Effect stable identity | No | `matchName` | `matchName` |
| Effect property identity | No | `matchName` | `matchName` |
| Effect property value | No | Yes | Yes, JSON-safe values |
| Masks / deep arbitrary properties | No | Yes | Not included in pilot v2 scope |
| Project mutation APIs in reader | None | Query scripts are read-only, repo also contains action scripts | None |
| JSON compatibility for ES3 | Assumed host `JSON.parse` | Bundled json2 | Bundled public-domain json2 |
| Pilot-schema adapter | No | No | Yes, `to_pilot_state()` |

## Important defects found in the original AE-R1

1. It exported only `selected_layers`, so it could not prove creation, duplication, or layer ordering.
2. It had no source-text field.
3. It had no layer timing fields.
4. It had no effects or effect-property data.
5. It did not expose persistent `layer.id`.
6. Keyframe time was seconds-only; the pilot needs exact frame verification.
7. It had no capability manifest.
8. `read_state.jsx` depended on `JSON.parse` without bundling an ES3 JSON implementation.
9. Its output schema did not map directly to the machine-readable assertions in `pilot_10_skills.yaml`.

## Useful patterns taken from the external reference

The following ideas were validated against the external code and then reimplemented for this reader:

- Read the entire active composition, not only selected layers.
- Use After Effects `matchName` identifiers for stable property/effect identity.
- Read text through `ADBE Text Properties` / `ADBE Text Document`.
- Read effect trees recursively.
- Read keyframe count, time, and value.
- Keep display names for diagnostics while using stable IDs for verification.
- Bundle a JSON polyfill for ExtendScript ES3.

## Deliberately not copied

- The macOS-only `runner.sh`.
- The shared `/tmp/ae-assistant-result.json` IPC model.
- Any action/mutation script.
- The agent workflow or automatic code generation layer.
- Broad project-audit features unrelated to the 10-skill verification pilot.

## AE Reader v2 contract

Version: `2.0.0`

Schema: `2`

Single source of declared capabilities:

`ae_reader/capabilities.json`

Every live response must carry the same manifest. Python rejects a response when:

- request ID differs,
- run ID differs,
- legacy identity differs when supplied,
- capture time predates the request,
- schema/reader version differs,
- capability manifest differs,
- JSON or typed state is malformed.

No failed or ambiguous response may be interpreted as success.

## Read-only boundary

`ae_reader/scripts/read_state.jsx` is permitted to:

- inspect the application/project/composition/layers/properties,
- read local request/config files,
- write the response file.

It is not permitted to call project mutation operations such as property setters, effect insertion, layer duplication/reordering, command execution, or undo-group mutation flows.

A static unit test guards this boundary.

## What still requires a real Windows + After Effects 26.x probe

Repository-level implementation can prove schema, identity checks, safety invariants, and deterministic mapping. It cannot prove the installed application's runtime behavior without launching the user's actual After Effects build.

The final live gate must confirm:

1. `AfterFX.exe -r` executes the copied request-local script.
2. `app.isoLanguage`, `layer.id`, text access, and effect property access behave as expected on the installed 26.x build.
3. A Gaussian Blur applied through the UI is reported with a stable effect `matchName` and a readable Blurriness property.
4. Separated Position dimensions are represented correctly.
5. Freshness timestamps remain monotonic enough for the request check.

Until that live probe is run, the implementation is code-complete but not runtime-certified.
