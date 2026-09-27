"""Command-line utilities for validating and probing AE Reader v2."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .reader import AfterEffectsReadOnlyObserver
from .schema import READER_VERSION, SCHEMA_VERSION


def _print_json(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def _self_check(observer: AfterEffectsReadOnlyObserver) -> int:
    errors = []

    expected_files = [
        Path(__file__).resolve().parent / "scripts" / "read_state.jsx",
        Path(__file__).resolve().parent / "scripts" / "json2.jsx",
        Path(__file__).resolve().parent / "capabilities.json",
    ]
    for path in expected_files:
        if not path.is_file():
            errors.append("missing runtime file: " + str(path))

    manifest = observer.capability_manifest
    if manifest.reader_version != READER_VERSION:
        errors.append("reader version mismatch")
    if manifest.schema_version != SCHEMA_VERSION:
        errors.append("schema version mismatch")

    source_path = Path(__file__).resolve().parent / "scripts" / "read_state.jsx"
    if source_path.is_file():
        source = source_path.read_text(encoding="utf-8")
        forbidden = [
            ".setValue(",
            ".setValueAtTime(",
            ".setValuesAtTimes(",
            ".addProperty(",
            ".addComp(",
            ".duplicate(",
            ".moveBefore(",
            ".moveAfter(",
            "app.executeCommand(",
            "app.beginUndoGroup(",
        ]
        for token in forbidden:
            if token in source:
                errors.append("forbidden mutation token in read_state.jsx: " + token)

    result = {
        "reader_version": READER_VERSION,
        "schema_version": SCHEMA_VERSION,
        "manifest_capability_count": len(manifest.supported_capabilities),
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
    }
    _print_json(result)
    return 0 if not errors else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AE Reader v2 utility")
    parser.add_argument("--afterfx-path", default=None)
    parser.add_argument("--ipc-dir", default=None)

    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("manifest", help="Print the declared capability manifest")
    sub.add_parser("self-check", help="Validate local reader files and read-only boundary")

    probe = sub.add_parser("probe", help="Run one live read-only After Effects probe")
    probe.add_argument("--run-id", required=True)
    probe.add_argument("--timeout", type=float, default=10.0)
    probe.add_argument("--retain-failed-request", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    observer = AfterEffectsReadOnlyObserver(
        afterfx_path=args.afterfx_path,
        ipc_dir=args.ipc_dir,
        retain_failed_requests=getattr(args, "retain_failed_request", False),
    )

    if args.command == "manifest":
        _print_json(observer.capability_manifest.to_dict())
        return 0

    if args.command == "self-check":
        return _self_check(observer)

    if args.command == "probe":
        result = observer.read_pilot_state(
            run_id=args.run_id,
            timeout=args.timeout,
        )
        _print_json(result)
        return 0 if result["status"] == "OK" else 2

    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    sys.exit(main())
