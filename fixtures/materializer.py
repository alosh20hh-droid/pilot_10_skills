"""End-to-end canonical fixture materialization and certification."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from ae_reader import AfterEffectsReadOnlyObserver
from verifier.contract import PilotContract

from .builder import FixtureBuilder
from .manager import FixtureRepository


class FixtureMaterializer:
    def __init__(
        self,
        contract: PilotContract,
        *,
        repository: Optional[FixtureRepository] = None,
        builder: Optional[FixtureBuilder] = None,
        reader: Optional[AfterEffectsReadOnlyObserver] = None,
        afterfx_path: Optional[str] = None,
    ) -> None:
        self.contract = contract
        self.repository = repository or FixtureRepository(contract)
        self.builder = builder or FixtureBuilder(
            contract,
            afterfx_path=afterfx_path,
        )
        self.reader = reader or AfterEffectsReadOnlyObserver(
            afterfx_path=afterfx_path,
        )

    def materialize_one(
        self,
        fixture_id: str,
        *,
        timeout: float = 30.0,
        acknowledge_disposable_project: bool = False,
    ) -> Dict[str, Any]:
        self.repository.ensure_layout()
        output = self.repository.canonical_path(fixture_id)

        if output.exists():
            raise RuntimeError(
                f"canonical fixture already exists: {output}. "
                "Delete it explicitly only when intentionally rebuilding."
            )

        try:
            build_result = self.builder.build(
                fixture_id,
                output,
                timeout=timeout,
                acknowledge_disposable_project=acknowledge_disposable_project,
            )

            certification_run_id = (
                f"fixture-cert-{fixture_id}-{int(time.time() * 1000)}"
            )
            evidence = self.reader.read_pilot_state(
                certification_run_id,
                timeout=max(10.0, timeout),
            )
            request_id = evidence.get("request_id")
            if not isinstance(request_id, str) or not request_id:
                raise RuntimeError("AE Reader certification response is missing request_id")

            # The reader is invoked only after the builder has confirmed the file
            # was saved. Bind certification freshness to the save boundary itself.
            save_boundary = build_result.get("saved_at")
            if not isinstance(save_boundary, (int, float)) or isinstance(save_boundary, bool):
                save_boundary = build_result["finished_at"]

            record = self.repository.certify(
                fixture_id,
                aep_path=output,
                evidence=evidence,
                expected_run_id=certification_run_id,
                expected_request_id=request_id,
                min_captured_at=float(save_boundary),
                builder_result=build_result,
            )

            return {
                "fixture_id": fixture_id,
                "status": "CERTIFIED",
                "canonical_path": str(output.resolve()),
                "sha256": record["sha256"],
                "size_bytes": record["size_bytes"],
                "reader_request_id": request_id,
                "certification_run_id": certification_run_id,
                "captured_at": evidence.get("captured_at"),
            }
        except Exception:
            # This call created the file from a previously absent path. If live
            # certification fails, keep no untrusted canonical binary behind.
            try:
                if output.exists():
                    output.unlink()
            finally:
                certification = self.repository.certification_path(fixture_id)
                if certification.exists():
                    certification.unlink()
            raise

    def materialize_all(
        self,
        *,
        timeout: float = 30.0,
        acknowledge_disposable_project: bool = False,
    ) -> List[Dict[str, Any]]:
        if not acknowledge_disposable_project:
            raise RuntimeError(
                "materialize_all refused without disposable-project acknowledgement"
            )

        results: List[Dict[str, Any]] = []
        self.repository.ensure_layout()
        for fixture_id in self.contract.fixtures:
            canonical = self.repository.canonical_path(fixture_id)
            if canonical.exists():
                try:
                    record = self.repository.verify_canonical(fixture_id)
                except Exception as exc:
                    raise RuntimeError(
                        f"{fixture_id} already has an uncertified or invalid canonical file; "
                        f"remove/reconcile it before resuming: {exc}"
                    ) from exc
                results.append({
                    "fixture_id": fixture_id,
                    "status": "CERTIFIED_EXISTING",
                    "canonical_path": str(canonical.resolve()),
                    "sha256": record["sha256"],
                    "size_bytes": record["size_bytes"],
                })
                continue

            results.append(
                self.materialize_one(
                    fixture_id,
                    timeout=timeout,
                    acknowledge_disposable_project=True,
                )
            )
        return results
