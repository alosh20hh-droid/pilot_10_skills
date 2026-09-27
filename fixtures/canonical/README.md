# Canonical After Effects fixtures

This directory is reserved for **live-certified** `.aep` binaries created by `python -m fixtures.cli materialize...`.

Do not hand-author or copy arbitrary project files here.

A file is usable by the pilot only when a matching certification record exists under `fixtures/certifications/` and `python -m fixtures.cli verify-canonical --fixture-id <ID>` passes.
