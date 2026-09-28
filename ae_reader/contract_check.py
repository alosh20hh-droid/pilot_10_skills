"""Cross-check pilot_10_skills.yaml against the AE Reader capability manifest."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import yaml

from .schema import READER_VERSION, SCHEMA_VERSION


def _load_yaml(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError, UnicodeError) as exc:
        return None, f"unable to load pilot contract: {exc}"
    if not isinstance(value, dict):
        return None, "pilot contract root must be an object"
    return value, None


def _load_manifest(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError) as exc:
        return None, f"unable to load capability manifest: {exc}"
    if not isinstance(value, dict):
        return None, "capability manifest root must be an object"
    return value, None


def check_contract(root: Path | None = None) -> list[str]:
    root = root or Path(__file__).resolve().parents[1]
    pilot_path = root / "pilot_10_skills.yaml"
    manifest_path = root / "ae_reader" / "capabilities.json"

    errors: list[str] = []

    pilot, pilot_error = _load_yaml(pilot_path)
    if pilot_error:
        return [pilot_error]
    manifest, manifest_error = _load_manifest(manifest_path)
    if manifest_error:
        return [manifest_error]

    assert pilot is not None
    assert manifest is not None

    reader_contract = pilot.get("ae_reader_contract")
    if not isinstance(reader_contract, dict):
        return ["pilot is missing ae_reader_contract"]

    expected_reader = reader_contract.get("expected_reader_version")
    expected_schema = reader_contract.get("expected_schema_version")

    if expected_reader != READER_VERSION:
        errors.append(
            f"pilot expects reader {expected_reader!r} but code is {READER_VERSION!r}"
        )
    if expected_schema != SCHEMA_VERSION:
        errors.append(
            f"pilot expects schema {expected_schema!r} but code is {SCHEMA_VERSION!r}"
        )

    if manifest.get("reader_version") != READER_VERSION:
        errors.append("capability manifest reader_version does not match code")
    if manifest.get("schema_version") != SCHEMA_VERSION:
        errors.append("capability manifest schema_version does not match code")

    supported_raw = manifest.get("supported_capabilities")
    if not isinstance(supported_raw, list) or not all(
        isinstance(item, str) and item for item in supported_raw
    ):
        errors.append("capability manifest supported_capabilities is invalid")
        supported: set[str] = set()
    else:
        supported = set(supported_raw)
        if len(supported) != len(supported_raw):
            errors.append("capability manifest contains duplicate capability ids")

    known_raw = reader_contract.get("known_capability_ids")
    if not isinstance(known_raw, list) or not all(
        isinstance(item, str) and item for item in known_raw
    ):
        errors.append("ae_reader_contract.known_capability_ids is invalid")
        known: set[str] = set()
    else:
        known = set(known_raw)
        if len(known) != len(known_raw):
            errors.append("ae_reader_contract.known_capability_ids contains duplicates")

    referenced = set(known)
    skills = pilot.get("skills")
    if not isinstance(skills, list):
        errors.append("pilot skills must be a list")
    else:
        for skill in skills:
            if not isinstance(skill, dict):
                errors.append("pilot contains a non-object skill")
                continue
            for field in (
                "required_reader_capabilities",
                "preferred_reader_capabilities",
            ):
                values = skill.get(field) or []
                if not isinstance(values, list) or not all(
                    isinstance(item, str) and item for item in values
                ):
                    errors.append(
                        f"{skill.get('id', '<unknown>')} has invalid {field}"
                    )
                    continue
                referenced.update(values)

    missing_from_manifest = sorted(referenced - supported)
    if missing_from_manifest:
        errors.append(
            "pilot references capabilities absent from Reader manifest: "
            + ", ".join(missing_from_manifest)
        )

    if not referenced:
        errors.append("pilot does not declare any AE Reader capabilities")

    required_system = {
        "application.version",
        "application.language",
        "project.file_identity",
    }
    missing_system = sorted(required_system - known)
    if missing_system:
        errors.append(
            "ae_reader_contract omits required system capabilities: "
            + ", ".join(missing_system)
        )

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
