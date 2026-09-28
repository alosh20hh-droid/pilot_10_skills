import copy
import json
import shutil
import tempfile
import time
import unittest
from pathlib import Path

from fixtures import (
    FixtureBuildError,
    FixtureBuilder,
    FixtureCertificationError,
    FixtureMaterializer,
    FixtureRepository,
    compile_all_fixture_plans,
    compile_fixture_plan,
    sha256_file,
)
from verifier.contract import PilotContract


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "pilot_10_skills.yaml"


def load_contract(path=CONTRACT_PATH):
    return PilotContract.load(path)


def synthetic_evidence(contract, fixture_id, project_path, *, run_id="cert-run", request_id="cert-request", captured_at=1000000000000.0):
    state = copy.deepcopy(contract.fixtures[fixture_id]["required_state"])
    project = state.setdefault("project", {})
    project["file_path"] = str(Path(project_path).resolve())
    return {
        "status": "OK",
        "request_id": request_id,
        "run_id": run_id,
        "captured_at": captured_at,
        "reader_version": contract.expected_reader_version(),
        "schema_version": contract.expected_reader_schema_version(),
        "capabilities": {
            "reader_version": contract.expected_reader_version(),
            "schema_version": contract.expected_reader_schema_version(),
            "supported_capabilities": list(
                contract.ae_reader_contract["known_capability_ids"]
            ),
        },
        "state": state,
        "errors": [],
        "application": {
            "name": "After Effects",
            "version": "26.0",
            "build_name": "test-build",
            "build_number": 1,
            "language": "en-US",
        },
    }



def synthetic_builder_result(fixture_id, path, *, version="26.0", language="en-US", saved_at=100.0):
    return {
        "status": "SAVED",
        "fixture_id": fixture_id,
        "output_path": str(Path(path).resolve()),
        "started_at": saved_at - 2,
        "finished_at": saved_at + 1,
        "saved_at": saved_at,
        "ae_version": version,
        "ae_build_name": "test-build",
        "ae_build_number": 1,
        "ae_language": language,
    }


class FixtureSpecTests(unittest.TestCase):
    def setUp(self):
        self.contract = load_contract()

    def test_all_ten_specs_compile(self):
        plans = compile_all_fixture_plans(self.contract)
        self.assertEqual(len(plans), 10)
        self.assertEqual(
            [plan.fixture_id for plan in plans],
            list(self.contract.fixtures.keys()),
        )

    def test_empty_project_fixture_is_explicit(self):
        plan = compile_fixture_plan(self.contract, "FX-001-EMPTY-PROJECT")
        state = plan.required_state
        self.assertEqual(state["project"]["composition_count"], 0)
        self.assertIsNone(state["active_comp"])
        self.assertEqual(state["layers"], [])

    def test_reorder_fixture_declares_final_layer_order(self):
        plan = compile_fixture_plan(self.contract, "FX-009-REORDER-READY")
        layers = plan.required_state["layers"]
        self.assertEqual(
            [(layer["index"], layer["name"]) for layer in layers],
            [(1, "PILOT_TEXT_COPY"), (2, "PILOT_TEXT")],
        )

    def test_effect_fixture_starts_without_effects(self):
        plan = compile_fixture_plan(self.contract, "FX-010-EFFECT-READY")
        self.assertEqual(plan.required_state["layers"][0]["effects"], [])

    def test_fixture_build_request_is_explicitly_disposable(self):
        plan = compile_fixture_plan(self.contract, "FX-004-POSITION-READY")
        request = plan.to_request(r"C:\fixture.aep")
        self.assertEqual(request["lab_mode"], "DISPOSABLE_FIXTURE_BUILD")
        self.assertEqual(request["fixture_id"], "FX-004-POSITION-READY")


class FixtureBuilderPythonTests(unittest.TestCase):
    def test_builder_requires_explicit_disposable_project_ack(self):
        builder = FixtureBuilder(load_contract())
        with self.assertRaises(FixtureBuildError):
            builder.build(
                "FX-001-EMPTY-PROJECT",
                "fixture.aep",
                acknowledge_disposable_project=False,
            )

    def test_builder_rejects_non_aep_output_before_launching_after_effects(self):
        builder = FixtureBuilder(load_contract())
        with self.assertRaises(FixtureBuildError):
            builder.build(
                "FX-001-EMPTY-PROJECT",
                "fixture.txt",
                acknowledge_disposable_project=True,
            )


class FixtureBuilderSourceTests(unittest.TestCase):
    def test_builder_has_hard_disposable_project_guard(self):
        source = (ROOT / "fixtures" / "scripts" / "build_fixture.jsx").read_text(
            encoding="utf-8"
        )
        self.assertIn('request.lab_mode === "DISPOSABLE_FIXTURE_BUILD"', source)
        self.assertIn("CloseOptions.DO_NOT_SAVE_CHANGES", source)
        self.assertIn("app.project.save(outputFile)", source)

    def test_builder_creates_layers_bottom_to_top_then_validates_order(self):
        source = (ROOT / "fixtures" / "scripts" / "build_fixture.jsx").read_text(
            encoding="utf-8"
        )
        self.assertIn("for (var i = layers.length - 1; i >= 0; i--)", source)
        self.assertIn("Validate final top-to-bottom order", source)

    def test_builder_publishes_result_atomically(self):
        source = (ROOT / "fixtures" / "scripts" / "build_fixture.jsx").read_text(
            encoding="utf-8"
        )
        self.assertIn('new File(path + ".tmp")', source)
        self.assertIn("temporary.rename(finalFile.name)", source)

    def test_builder_refuses_measured_keyframes_and_effects(self):
        source = (ROOT / "fixtures" / "scripts" / "build_fixture.jsx").read_text(
            encoding="utf-8"
        )
        self.assertIn("refuses to pre-create measured opacity keyframes", source)
        self.assertIn("refuses to pre-install measured effects", source)


class FixtureRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        shutil.copy2(CONTRACT_PATH, self.root / "pilot_10_skills.yaml")
        self.contract = load_contract(self.root / "pilot_10_skills.yaml")
        self.repository = FixtureRepository(self.contract, repo_root=self.root)
        self.repository.ensure_layout()

    def tearDown(self):
        self.temp.cleanup()

    def _certify(self, fixture_id="FX-004-POSITION-READY"):
        path = self.repository.canonical_path(fixture_id)
        path.write_bytes(b"FAKE-AEP-BINARY\x00" + fixture_id.encode("utf-8"))
        evidence = synthetic_evidence(self.contract, fixture_id, path)
        record = self.repository.certify(
            fixture_id,
            aep_path=path,
            evidence=evidence,
            expected_run_id="cert-run",
            expected_request_id="cert-request",
            min_captured_at=10,
            builder_result=synthetic_builder_result(fixture_id, path),
        )
        return path, record

    def test_certification_binds_hash_contract_and_reader_state(self):
        path, record = self._certify()
        self.assertEqual(record["status"], "CERTIFIED")
        self.assertEqual(record["sha256"], sha256_file(path))
        verified = self.repository.verify_canonical("FX-004-POSITION-READY")
        self.assertEqual(verified["sha256"], record["sha256"])

    def test_missing_project_identity_capability_is_rejected(self):
        fixture_id = "FX-004-POSITION-READY"
        path = self.repository.canonical_path(fixture_id)
        path.write_bytes(b"FAKE")
        evidence = synthetic_evidence(self.contract, fixture_id, path)
        evidence["capabilities"]["supported_capabilities"] = [
            item
            for item in evidence["capabilities"]["supported_capabilities"]
            if item != "project.file_identity"
        ]
        with self.assertRaises(FixtureCertificationError):
            self.repository.certify(
                fixture_id,
                aep_path=path,
                evidence=evidence,
                expected_run_id="cert-run",
                expected_request_id="cert-request",
                min_captured_at=10,
            )

    def test_wrong_project_file_identity_is_rejected(self):
        fixture_id = "FX-004-POSITION-READY"
        path = self.repository.canonical_path(fixture_id)
        path.write_bytes(b"FAKE")
        evidence = synthetic_evidence(
            self.contract,
            fixture_id,
            self.root / "different.aep",
        )
        with self.assertRaises(FixtureCertificationError):
            self.repository.certify(
                fixture_id,
                aep_path=path,
                evidence=evidence,
                expected_run_id="cert-run",
                expected_request_id="cert-request",
                min_captured_at=10,
            )

    def test_state_mismatch_is_rejected(self):
        fixture_id = "FX-004-POSITION-READY"
        path = self.repository.canonical_path(fixture_id)
        path.write_bytes(b"FAKE")
        evidence = synthetic_evidence(self.contract, fixture_id, path)
        evidence["state"]["layers"][0]["transform"]["position"]["x"] = 999
        with self.assertRaises(FixtureCertificationError):
            self.repository.certify(
                fixture_id,
                aep_path=path,
                evidence=evidence,
                expected_run_id="cert-run",
                expected_request_id="cert-request",
                min_captured_at=10,
            )


    def test_certification_requires_builder_metadata(self):
        fixture_id = "FX-004-POSITION-READY"
        path = self.repository.canonical_path(fixture_id)
        path.write_bytes(b"FAKE")
        evidence = synthetic_evidence(self.contract, fixture_id, path)
        with self.assertRaises(FixtureCertificationError):
            self.repository.certify(
                fixture_id,
                aep_path=path,
                evidence=evidence,
                expected_run_id="cert-run",
                expected_request_id="cert-request",
                min_captured_at=10,
                builder_result=None,
            )

    def test_wrong_builder_ae_major_is_rejected(self):
        fixture_id = "FX-004-POSITION-READY"
        path = self.repository.canonical_path(fixture_id)
        path.write_bytes(b"FAKE")
        evidence = synthetic_evidence(self.contract, fixture_id, path)
        with self.assertRaises(FixtureCertificationError):
            self.repository.certify(
                fixture_id,
                aep_path=path,
                evidence=evidence,
                expected_run_id="cert-run",
                expected_request_id="cert-request",
                min_captured_at=10,
                builder_result=synthetic_builder_result(
                    fixture_id, path, version="25.6"
                ),
            )


    def test_build_number_mismatch_is_rejected(self):
        fixture_id = "FX-004-POSITION-READY"
        path = self.repository.canonical_path(fixture_id)
        path.write_bytes(b"FAKE")
        evidence = synthetic_evidence(self.contract, fixture_id, path)
        evidence["application"]["build_number"] = 2
        with self.assertRaises(FixtureCertificationError):
            self.repository.certify(
                fixture_id,
                aep_path=path,
                evidence=evidence,
                expected_run_id="cert-run",
                expected_request_id="cert-request",
                min_captured_at=10,
                builder_result=synthetic_builder_result(fixture_id, path),
            )

    def test_build_name_mismatch_is_rejected(self):
        fixture_id = "FX-004-POSITION-READY"
        path = self.repository.canonical_path(fixture_id)
        path.write_bytes(b"FAKE")
        evidence = synthetic_evidence(self.contract, fixture_id, path)
        evidence["application"]["build_name"] = "other-build"
        with self.assertRaises(FixtureCertificationError):
            self.repository.certify(
                fixture_id,
                aep_path=path,
                evidence=evidence,
                expected_run_id="cert-run",
                expected_request_id="cert-request",
                min_captured_at=10,
                builder_result=synthetic_builder_result(fixture_id, path),
            )

    def test_wrong_reader_language_is_rejected(self):
        fixture_id = "FX-004-POSITION-READY"
        path = self.repository.canonical_path(fixture_id)
        path.write_bytes(b"FAKE")
        evidence = synthetic_evidence(self.contract, fixture_id, path)
        evidence["application"]["language"] = "de-DE"
        with self.assertRaises(FixtureCertificationError):
            self.repository.certify(
                fixture_id,
                aep_path=path,
                evidence=evidence,
                expected_run_id="cert-run",
                expected_request_id="cert-request",
                min_captured_at=10,
                builder_result=synthetic_builder_result(fixture_id, path),
            )

    def test_locale_separator_variation_is_accepted(self):
        fixture_id = "FX-004-POSITION-READY"
        path = self.repository.canonical_path(fixture_id)
        path.write_bytes(b"FAKE")
        evidence = synthetic_evidence(self.contract, fixture_id, path)
        evidence["application"]["language"] = "en_US"
        record = self.repository.certify(
            fixture_id,
            aep_path=path,
            evidence=evidence,
            expected_run_id="cert-run",
            expected_request_id="cert-request",
            min_captured_at=10,
            builder_result=synthetic_builder_result(
                fixture_id, path, language="en_US"
            ),
        )
        self.assertEqual(record["status"], "CERTIFIED")

    def test_tampered_canonical_file_is_rejected(self):
        path, _ = self._certify()
        path.write_bytes(path.read_bytes() + b"TAMPER")
        with self.assertRaises(FixtureCertificationError):
            self.repository.verify_canonical("FX-004-POSITION-READY")

    def test_contract_change_invalidates_certification(self):
        self._certify()
        contract_file = self.root / "pilot_10_skills.yaml"
        contract_file.write_text(
            contract_file.read_text(encoding="utf-8") + "\n# changed after certification\n",
            encoding="utf-8",
        )
        with self.assertRaises(FixtureCertificationError):
            self.repository.verify_canonical("FX-004-POSITION-READY")

    def test_fresh_run_copy_preserves_certified_hash_and_forbids_run_id_reuse(self):
        _, record = self._certify()
        copied = self.repository.create_run_copy(
            "FX-004-POSITION-READY",
            "run-unique-1",
        )
        self.assertTrue(Path(copied["path"]).is_file())
        self.assertEqual(copied["copy_sha256"], record["sha256"])
        with self.assertRaises(FixtureCertificationError):
            self.repository.create_run_copy(
                "FX-004-POSITION-READY",
                "run-unique-1",
            )

    def test_run_id_remains_reserved_after_disposable_copy_cleanup(self):
        self._certify()
        self.repository.create_run_copy(
            "FX-004-POSITION-READY",
            "run-persistent-id",
        )
        self.repository.remove_run_copy("run-persistent-id")
        with self.assertRaises(FixtureCertificationError):
            self.repository.create_run_copy(
                "FX-004-POSITION-READY",
                "run-persistent-id",
            )

    def test_uncertified_fixture_cannot_be_copied(self):
        with self.assertRaises(FixtureCertificationError):
            self.repository.create_run_copy(
                "FX-005-SCALE-READY",
                "run-1",
            )

    def test_status_reports_all_ten_fixtures(self):
        self._certify()
        status = self.repository.status()
        self.assertEqual(len(status), 10)
        self.assertEqual(
            status["FX-004-POSITION-READY"]["status"],
            "CERTIFIED",
        )
        self.assertEqual(
            status["FX-005-SCALE-READY"]["status"],
            "NOT_CERTIFIED",
        )


class _FakeBuilder:
    def __init__(self):
        self.last_output = None

    def build(self, fixture_id, output_path, *, timeout, acknowledge_disposable_project):
        if not acknowledge_disposable_project:
            raise FixtureBuildError("ack required")
        self.last_output = Path(output_path).resolve()
        self.last_output.parent.mkdir(parents=True, exist_ok=True)
        self.last_output.write_bytes(b"FAKE-MATERIALIZED-AEP")
        return {
            "status": "SAVED",
            "fixture_id": fixture_id,
            "output_path": str(self.last_output),
            "started_at": 10.0,
            "finished_at": 11.0,
            "saved_at": 10.5,
            "ae_version": "26.0",
            "ae_build_name": "test-build",
            "ae_build_number": 1,
            "ae_language": "en-US",
        }


class _FakeReader:
    def __init__(self, contract, fixture_id, path_provider):
        self.contract = contract
        self.fixture_id = fixture_id
        self.path_provider = path_provider

    def read_pilot_state(self, run_id, timeout=10.0):
        return synthetic_evidence(
            self.contract,
            self.fixture_id,
            self.path_provider(),
            run_id=run_id,
            request_id="reader-cert-request",
            captured_at=20.0,
        )


class FixtureMaterializerTests(unittest.TestCase):
    def test_materializer_builds_reads_and_certifies_one_fixture(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            shutil.copy2(CONTRACT_PATH, root / "pilot_10_skills.yaml")
            contract = load_contract(root / "pilot_10_skills.yaml")
            repository = FixtureRepository(contract, repo_root=root)
            builder = _FakeBuilder()
            reader = _FakeReader(
                contract,
                "FX-002-COMP-EMPTY",
                lambda: repository.canonical_path("FX-002-COMP-EMPTY"),
            )
            materializer = FixtureMaterializer(
                contract,
                repository=repository,
                builder=builder,
                reader=reader,
            )
            result = materializer.materialize_one(
                "FX-002-COMP-EMPTY",
                acknowledge_disposable_project=True,
            )
            self.assertEqual(result["status"], "CERTIFIED")
            repository.verify_canonical("FX-002-COMP-EMPTY")


    def test_materializer_rejects_reader_evidence_older_than_save_boundary(self):
        class LateSaveBuilder(_FakeBuilder):
            def build(self, fixture_id, output_path, *, timeout, acknowledge_disposable_project):
                result = super().build(
                    fixture_id,
                    output_path,
                    timeout=timeout,
                    acknowledge_disposable_project=acknowledge_disposable_project,
                )
                result["saved_at"] = 30.0
                result["finished_at"] = 31.0
                return result

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            shutil.copy2(CONTRACT_PATH, root / "pilot_10_skills.yaml")
            contract = load_contract(root / "pilot_10_skills.yaml")
            repository = FixtureRepository(contract, repo_root=root)
            builder = LateSaveBuilder()
            reader = _FakeReader(
                contract,
                "FX-002-COMP-EMPTY",
                lambda: repository.canonical_path("FX-002-COMP-EMPTY"),
            )
            materializer = FixtureMaterializer(
                contract,
                repository=repository,
                builder=builder,
                reader=reader,
            )
            with self.assertRaises(FixtureCertificationError):
                materializer.materialize_one(
                    "FX-002-COMP-EMPTY",
                    acknowledge_disposable_project=True,
                )
            self.assertFalse(
                repository.canonical_path("FX-002-COMP-EMPTY").exists(),
                "failed certification must not leave an untrusted canonical .aep",
            )
            self.assertFalse(
                repository.certification_path("FX-002-COMP-EMPTY").exists(),
                "failed certification must not leave a certification record",
            )


if __name__ == "__main__":
    unittest.main()
