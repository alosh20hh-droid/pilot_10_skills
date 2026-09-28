"""Cross-check pilot_10_skills.yaml against the AE Reader v2 manifest."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from .schema import READER_VERSION, SCHEMA_VERSION


CAPABILITY_PATTERN = re.compile(
    r'^\s*-\s+"((?:application|project|composition|layer|property|effect)\.[A-Za-z0-9_.-]+)"\s*)


def check_contract(root: Path | None = None) -> list[str]:
    root = root or Path(__file__).resolve().parents[1]
    pilot_path = root / "pilot_10_skills.yaml"
    manifest_path = root / "ae_reader" / "capabilities.json"

    errors: list[str] = []

    try:
        pilot_text = pilot_path.read_text(encoding="utf-8")
    except OSError as exc:
        return [f"unable to read pilot contract: {exc}"]

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [f"unable to read capability manifest: {exc}"]

    reader_match = re.search(r'^\s*expected_reader_version:\s*"([^"]+)"\s*$', pilot_text, re.MULTILINE)
    schema_match = re.search(r'^\s*expected_schema_version:\s*(\d+)\s*$', pilot_text, re.MULTILINE)

    if not reader_match:
        errors.append("pilot is missing expected_reader_version")
    elif reader_match.group(1) != READER_VERSION:
        errors.append(
            f"pilot expects reader {reader_match.group(1)} but code is {READER_VERSION}"
        )

    if not schema_match:
        errors.append("pilot is missing expected_schema_version")
    elif int(schema_match.group(1)) != SCHEMA_VERSION:
        errors.append(
            f"pilot expects schema {schema_match.group(1)} but code is {SCHEMA_VERSION}"
        )

    if manifest.get("reader_version") != READER_VERSION:
        errors.append("capability manifest reader_version does not match code")
    if manifest.get("schema_version") != SCHEMA_VERSION:
        errors.append("capability manifest schema_version does not match code")

    supported = set(manifest.get("supported_capabilities") or [])
    referenced = set()

    for line in pilot_text.splitlines():
        match = CAPABILITY_PATTERN.match(line)
        if match:
            referenced.add(match.group(1))

    missing = sorted(referenced - supported)
    if missing:
        errors.append("pilot references undeclared reader capabilities: " + ", ".join(missing))

    if not referenced:
        errors.append("no reader capabilities were discovered in pilot contract")

    return errors


def main() -> int:
    errors = check_contract()
    result = {
        "status": "PASS" if not errors else "FAIL",
        "reader_version": READER_VERSION,
        "schema_version": SCHEMA_VERSION,
        "errors": errors,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())

)


def check_contract(root: Path | None = None) -> list[str]:
    root = root or Path(__file__).resolve().parents[1]
    pilot_path = root / "pilot_10_skills.yaml"
    manifest_path = root / "ae_reader" / "capabilities.json"

    errors: list[str] = []

    try:
        pilot_text = pilot_path.read_text(encoding="utf-8")
    except OSError as exc:
        return [f"unable to read pilot contract: {exc}"]

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [f"unable to read capability manifest: {exc}"]

    reader_match = re.search(r'^\s*expected_reader_version:\s*"([^"]+)"\s*$', pilot_text, re.MULTILINE)
    schema_match = re.search(r'^\s*expected_schema_version:\s*(\d+)\s*$', pilot_text, re.MULTILINE)

    if not reader_match:
        errors.append("pilot is missing expected_reader_version")
    elif reader_match.group(1) != READER_VERSION:
        errors.append(
            f"pilot expects reader {reader_match.group(1)} but code is {READER_VERSION}"
        )

    if not schema_match:
        errors.append("pilot is missing expected_schema_version")
    elif int(schema_match.group(1)) != SCHEMA_VERSION:
        errors.append(
            f"pilot expects schema {schema_match.group(1)} but code is {SCHEMA_VERSION}"
        )

    if manifest.get("reader_version") != READER_VERSION:
        errors.append("capability manifest reader_version does not match code")
    if manifest.get("schema_version") != SCHEMA_VERSION:
        errors.append("capability manifest schema_version does not match code")

    supported = set(manifest.get("supported_capabilities") or [])
    referenced = set()

    for line in pilot_text.splitlines():
        match = CAPABILITY_PATTERN.match(line)
        if match:
            referenced.add(match.group(1))

    missing = sorted(referenced - supported)
    if missing:
        errors.append("pilot references undeclared reader capabilities: " + ", ".join(missing))

    if not referenced:
        errors.append("no reader capabilities were discovered in pilot contract")

    return errors


def main() -> int:
    errors = check_contract()
    result = {
        "status": "PASS" if not errors else "FAIL",
        "reader_version": READER_VERSION,
        "schema_version": SCHEMA_VERSION,
        "errors": errors,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
