import copy
import unittest
from pathlib import Path

from verifier import (
    DeterministicVerifier,
    PilotContract,
    evaluate_assertions,
    resolve_path,
    run_calibration,
    run_pilot_calibration,
)


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "pilot_10_skills.yaml"
TEST_FIXTURE_PATH = r"C:\\pilot\\run\\fixture.aep"


def contract():
    return PilotContract.load(CONTRACT_PATH)


def good_environment():
    return {
        "operating_system": "Windows",
        "after_effects_process_running": True,
        "unknown_modal_dialog": False,
        "display_resolution": "1920x1080",
        "display_scaling_percent": 100,
        "ae_major_version": 26,
        "ae_language": "en-US",
        "workspace_id": "PILOT_WORKSPACE",
        "ae_build": "26.0-test",
        "fixture_path": TEST_FIXTURE_PATH,
    }


def evidence_for(state, *, run_id="run-1", request_id="request-1", captured_at=20.0, capabilities=None, status="OK", file_path=TEST_FIXTURE_PATH):
    c = contract()
    known = list(c.ae_reader_contract["known_capability_ids"])
    copied_state = copy.deepcopy(state)
    copied_state.setdefault("project", {})["file_path"] = file_path
    return {
        "status": status,
        "request_id": request_id,
        "run_id": run_id,
        "captured_at": captured_at,
        "reader_version": c.expected_reader_version(),
        "schema_version": c.expected_reader_schema_version(),
        "capabilities": {
            "reader_version": c.expected_reader_version(),
            "schema_version": c.expected_reader_schema_version(),
            "supported_capabilities": list(capabilities if capabilities is not None else known),
        },
        "state": copied_state,
        "errors": [],
    }


def fixture_state(skill_id):
    c = contract()
    return copy.deepcopy(c.fixture_for_skill(skill_id)["required_state"])


def rich_state():
    return {
        "project": {"composition_count": 1},
        "active_comp": {
            "name": "PILOT_COMP",
            "width": 1920,
            "height": 1080,
            "duration_seconds": 5,
            "frame_rate": 30,
            "current_time_seconds": 1,
            "current_time_frame": 30,
        },
        "layers": [
            {
                "id": 500,
                "index": 1,
                "name": "PILOT_TEXT",
                "type": "text",
                "source_text": "PILOT TEST",
                "in_seconds": 0,
                "out_seconds": 5,
                "transform": {
                    "position": {"x": 960, "y": 540},
                    "scale": {"x_percent": 125, "y_percent": 125},
                    "opacity_percent": 100,
                },
                "properties": {
                    "opacity": {
                        "keyframe_count": 2,
                        "keyframes": [
                            {"frame": 0, "time_seconds": 0, "value": 0},
                            {"frame": 30, "time_seconds": 1, "value": 100},
                        ],
                    }
                },
                "effects": [
                    {
                        "display_name": "Gaussian Blur",
                        "stable_id": "ADBE Gaussian Blur 2",
                        "enabled": True,
                        "properties": [
                            {
                                "display_name": "Blurriness",
                                "stable_id": "ADBE Gaussian Blur 2-0001",
                                "value": 25,
                            }
                        ],
                    }
                ],
            }
        ],
    }


class ContractTests(unittest.TestCase):
    def test_real_contract_loads(self):
        c = contract()
        self.assertEqual(len(c.skills), 10)
        self.assertEqual(len(c.fixtures), 10)
        self.assertEqual(c.required_repetitions, 3)
        self.assertEqual(c.validate(), [])


class PathResolverTests(unittest.TestCase):
    def test_resolves_layer_and_effect_alias_paths(self):
        state = rich_state()
        resolved = resolve_path(
            state,
            "layer[name=PILOT_TEXT].effects[stable_id=stable_effect_id].property[display_name=Blurriness].value",
            {"stable_effect_id": "ADBE Gaussian Blur 2"},
        )
        self.assertTrue(resolved.ok)
        self.assertEqual(resolved.value, 25)

    def test_resolves_index_path(self):
        resolved = resolve_path(rich_state(), "layers[0].source_text")
        self.assertTrue(resolved.ok)
        self.assertEqual(resolved.value, "PILOT TEST")

    def test_duplicate_named_layer_is_ambiguous(self):
        state = rich_state()
        duplicate = copy.deepcopy(state["layers"][0])
        duplicate["id"] = 501
        duplicate["index"] = 2
        state["layers"].append(duplicate)
        resolved = resolve_path(state, "layer[name=PILOT_TEXT].index")
        self.assertFalse(resolved.ok)
        self.assertEqual(resolved.error_code, "AMBIGUOUS_PATH")


class AssertionTests(unittest.TestCase):
    def test_all_pilot_operators(self):
        state = rich_state()
        assertions = [
            {"path": "active_comp.name", "op": "eq", "value": "PILOT_COMP"},
            {"path": "layer[name=PILOT_TEXT].transform.position.x", "op": "approx", "value": 960, "tolerance": 0.01},
            {"path": "layers", "op": "count_eq", "value": 1},
            {"path": "layers", "op": "contains_layer", "name": "PILOT_TEXT", "type": "text", "source_text": "PILOT TEST"},
            {"path": "layers", "op": "not_contains_layer_name", "value": "NOPE"},
            {"path": "layers", "op": "count_layer_name", "name": "PILOT_TEXT", "value": 1},
            {"path": "layer[name=PILOT_TEXT].properties.opacity.keyframes", "op": "contains_keyframe", "frame": 30, "value": 100, "value_tolerance": 0.001},
            {"path": "layer[name=PILOT_TEXT].effects", "op": "contains_effect_stable_id", "runtime_key": "stable_effect_id"},
        ]
        result = evaluate_assertions(
            state,
            assertions,
            runtime={"stable_effect_id": "ADBE Gaussian Blur 2"},
            comparison_policy=contract().comparison_policy,
        )
        self.assertTrue(result.passed)
        self.assertFalse(result.contract_error)
        self.assertTrue(all(item.passed for item in result.results))

    def test_unknown_operator_fails_closed(self):
        result = evaluate_assertions(
            rich_state(),
            [{"path": "project.composition_count", "op": "magic", "value": 1}],
        )
        self.assertFalse(result.passed)
        self.assertTrue(result.contract_error)
        self.assertEqual(result.results[0].error_code, "UNKNOWN_ASSERTION_OPERATOR")

    def test_missing_path_does_not_pass(self):
        result = evaluate_assertions(
            rich_state(),
            [{"path": "active_comp.does_not_exist", "op": "eq", "value": 1}],
        )
        self.assertFalse(result.passed)
        self.assertEqual(result.results[0].error_code, "PATH_NOT_FOUND")


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.contract = contract()
        self.verifier = DeterministicVerifier(self.contract)

    def test_valid_preflight_passes(self):
        state = fixture_state("AE-PILOT-004")
        evidence = evidence_for(state, captured_at=20)
        decision = self.verifier.verify_preflight(
            skill_id="AE-PILOT-004",
            evidence=evidence,
            expected_run_id="run-1",
            expected_request_id="request-1",
            run_started_at=10,
            environment=good_environment(),
            expected_ae_build="26.0-test",
        )
        self.assertTrue(decision.can_execute)
        self.assertIsNone(decision.run_status)
        self.assertTrue(decision.assertion_results.passed)


    def test_missing_pre_request_id_blocks(self):
        decision = self.verifier.verify_preflight(
            skill_id="AE-PILOT-004",
            evidence=evidence_for(fixture_state("AE-PILOT-004"), captured_at=20),
            expected_run_id="run-1",
            expected_request_id=None,
            run_started_at=10,
            environment=good_environment(),
            expected_ae_build="26.0-test",
        )
        self.assertFalse(decision.can_execute)
        self.assertEqual(decision.run_status, "BLOCKED")
        self.assertEqual(decision.reason_code, "REQUEST_ID_REQUIRED")

    def test_empty_run_id_blocks(self):
        decision = self.verifier.verify_preflight(
            skill_id="AE-PILOT-004",
            evidence=evidence_for(fixture_state("AE-PILOT-004"), captured_at=20),
            expected_run_id="",
            expected_request_id="request-1",
            run_started_at=10,
            environment=good_environment(),
            expected_ae_build="26.0-test",
        )
        self.assertFalse(decision.can_execute)
        self.assertEqual(decision.reason_code, "RUN_ID_REQUIRED")

    def test_reader_not_ok_blocks_preflight(self):
        decision = self.verifier.verify_preflight(
            skill_id="AE-PILOT-004",
            evidence=evidence_for(
                fixture_state("AE-PILOT-004"),
                captured_at=20,
                status="INVALID_RESPONSE",
            ),
            expected_run_id="run-1",
            expected_request_id="request-1",
            run_started_at=10,
            environment=good_environment(),
            expected_ae_build="26.0-test",
        )
        self.assertFalse(decision.can_execute)
        self.assertEqual(decision.reason_code, "READER_NOT_OK")

    def test_missing_capability_blocks_before_execution(self):
        state = fixture_state("AE-PILOT-004")
        evidence = evidence_for(
            state,
            capabilities=["layer.identity"],
            captured_at=20,
        )
        decision = self.verifier.verify_preflight(
            skill_id="AE-PILOT-004",
            evidence=evidence,
            expected_run_id="run-1",
            expected_request_id="request-1",
            run_started_at=10,
            environment=good_environment(),
            expected_ae_build="26.0-test",
        )
        self.assertFalse(decision.can_execute)
        self.assertEqual(decision.run_status, "BLOCKED")
        self.assertEqual(decision.reason_code, "READER_CAPABILITY_MISSING")

    def test_missing_operating_system_evidence_blocks(self):
        environment = good_environment()
        environment.pop("operating_system")
        decision = self.verifier.verify_preflight(
            skill_id="AE-PILOT-004",
            evidence=evidence_for(fixture_state("AE-PILOT-004"), captured_at=20),
            expected_run_id="run-1",
            expected_request_id="request-1",
            run_started_at=10,
            environment=environment,
            expected_ae_build="26.0-test",
        )
        self.assertFalse(decision.can_execute)
        self.assertEqual(decision.reason_code, "ENVIRONMENT_MISMATCH")

    def test_missing_modal_dialog_evidence_blocks(self):
        environment = good_environment()
        environment.pop("unknown_modal_dialog")
        decision = self.verifier.verify_preflight(
            skill_id="AE-PILOT-004",
            evidence=evidence_for(fixture_state("AE-PILOT-004"), captured_at=20),
            expected_run_id="run-1",
            expected_request_id="request-1",
            run_started_at=10,
            environment=environment,
            expected_ae_build="26.0-test",
        )
        self.assertFalse(decision.can_execute)
        self.assertEqual(decision.reason_code, "ENVIRONMENT_MISSING")

    def test_reader_ok_with_errors_is_rejected(self):
        evidence = evidence_for(fixture_state("AE-PILOT-004"), captured_at=20)
        evidence["errors"] = ["contradictory reader error"]
        decision = self.verifier.verify_preflight(
            skill_id="AE-PILOT-004",
            evidence=evidence,
            expected_run_id="run-1",
            expected_request_id="request-1",
            run_started_at=10,
            environment=good_environment(),
            expected_ae_build="26.0-test",
        )
        self.assertFalse(decision.can_execute)
        self.assertEqual(decision.reason_code, "CONTRADICTORY_EVIDENCE")

    def test_fixture_file_identity_mismatch_blocks(self):
        decision = self.verifier.verify_preflight(
            skill_id="AE-PILOT-004",
            evidence=evidence_for(
                fixture_state("AE-PILOT-004"),
                captured_at=20,
                file_path=r"C:\\pilot\\run\\wrong.aep",
            ),
            expected_run_id="run-1",
            expected_request_id="request-1",
            run_started_at=10,
            environment=good_environment(),
            expected_ae_build="26.0-test",
        )
        self.assertFalse(decision.can_execute)
        self.assertEqual(decision.reason_code, "FIXTURE_IDENTITY_MISMATCH")

    def test_missing_expected_fixture_path_blocks(self):
        environment = good_environment()
        environment.pop("fixture_path")
        decision = self.verifier.verify_preflight(
            skill_id="AE-PILOT-004",
            evidence=evidence_for(fixture_state("AE-PILOT-004"), captured_at=20),
            expected_run_id="run-1",
            expected_request_id="request-1",
            run_started_at=10,
            environment=environment,
            expected_ae_build="26.0-test",
        )
        self.assertFalse(decision.can_execute)
        self.assertEqual(decision.reason_code, "FIXTURE_IDENTITY_REQUIRED")

    def test_environment_mismatch_blocks(self):
        environment = good_environment()
        environment["display_scaling_percent"] = 125
        decision = self.verifier.verify_preflight(
            skill_id="AE-PILOT-004",
            evidence=evidence_for(fixture_state("AE-PILOT-004"), captured_at=20),
            expected_run_id="run-1",
            expected_request_id="request-1",
            run_started_at=10,
            environment=environment,
            expected_ae_build="26.0-test",
        )
        self.assertFalse(decision.can_execute)
        self.assertEqual(decision.run_status, "BLOCKED")
        self.assertEqual(decision.reason_code, "ENVIRONMENT_MISMATCH")

    def test_stale_pre_evidence_blocks(self):
        decision = self.verifier.verify_preflight(
            skill_id="AE-PILOT-004",
            evidence=evidence_for(fixture_state("AE-PILOT-004"), captured_at=5),
            expected_run_id="run-1",
            expected_request_id="request-1",
            run_started_at=10,
            environment=good_environment(),
            expected_ae_build="26.0-test",
        )
        self.assertFalse(decision.can_execute)
        self.assertEqual(decision.reason_code, "STALE_EVIDENCE")

    def test_fixture_mismatch_blocks(self):
        state = fixture_state("AE-PILOT-004")
        state["layers"][0]["transform"]["position"]["x"] = 999
        decision = self.verifier.verify_preflight(
            skill_id="AE-PILOT-004",
            evidence=evidence_for(state, captured_at=20),
            expected_run_id="run-1",
            expected_request_id="request-1",
            run_started_at=10,
            environment=good_environment(),
            expected_ae_build="26.0-test",
        )
        self.assertFalse(decision.can_execute)
        self.assertEqual(decision.reason_code, "FIXTURE_STATE_MISMATCH")


    def test_empty_project_preflight_for_skill_1_passes(self):
        state = fixture_state("AE-PILOT-001")
        decision = self.verifier.verify_preflight(
            skill_id="AE-PILOT-001",
            evidence=evidence_for(state, captured_at=20),
            expected_run_id="run-1",
            expected_request_id="request-1",
            run_started_at=10,
            environment=good_environment(),
            expected_ae_build="26.0-test",
        )
        self.assertTrue(decision.can_execute)

    def test_missing_pinned_build_blocks(self):
        decision = self.verifier.verify_preflight(
            skill_id="AE-PILOT-004",
            evidence=evidence_for(fixture_state("AE-PILOT-004"), captured_at=20),
            expected_run_id="run-1",
            expected_request_id="request-1",
            run_started_at=10,
            environment=good_environment(),
        )
        self.assertFalse(decision.can_execute)
        self.assertEqual(decision.reason_code, "AE_BUILD_PIN_REQUIRED")

    def test_pinned_build_mismatch_blocks(self):
        decision = self.verifier.verify_preflight(
            skill_id="AE-PILOT-004",
            evidence=evidence_for(fixture_state("AE-PILOT-004"), captured_at=20),
            expected_run_id="run-1",
            expected_request_id="request-1",
            run_started_at=10,
            environment=good_environment(),
            expected_ae_build="26.0-other-build",
        )
        self.assertFalse(decision.can_execute)
        self.assertEqual(decision.reason_code, "ENVIRONMENT_MISMATCH")

    def test_skill_10_requires_runtime_calibration(self):
        decision = self.verifier.verify_preflight(
            skill_id="AE-PILOT-010",
            evidence=evidence_for(fixture_state("AE-PILOT-010"), captured_at=20),
            expected_run_id="run-1",
            expected_request_id="request-1",
            run_started_at=10,
            environment=good_environment(),
            expected_ae_build="26.0-test",
        )
        self.assertFalse(decision.can_execute)
        self.assertEqual(decision.reason_code, "RUNTIME_CALIBRATION_MISSING")

    def test_skill_10_calibration_unlocks_preflight(self):
        decision = self.verifier.verify_preflight(
            skill_id="AE-PILOT-010",
            evidence=evidence_for(fixture_state("AE-PILOT-010"), captured_at=20),
            expected_run_id="run-1",
            expected_request_id="request-1",
            run_started_at=10,
            environment=good_environment(),
            runtime={"stable_effect_id": "ADBE Gaussian Blur 2"},
        )
        self.assertTrue(decision.can_execute)


class PostVerificationTests(unittest.TestCase):
    def setUp(self):
        self.contract = contract()
        self.verifier = DeterministicVerifier(self.contract)
        self.preflight = self.verifier.verify_preflight(
            skill_id="AE-PILOT-004",
            evidence=evidence_for(fixture_state("AE-PILOT-004"), request_id="pre-1", captured_at=20),
            expected_run_id="run-1",
            expected_request_id="pre-1",
            run_started_at=10,
            environment=good_environment(),
            expected_ae_build="26.0-test",
        )
        self.assertTrue(self.preflight.can_execute)

    def test_correct_post_state_passes(self):
        state = fixture_state("AE-PILOT-004")
        state["layers"][0]["transform"]["position"] = {"x": 960, "y": 540}
        decision = self.verifier.verify_post(
            skill_id="AE-PILOT-004",
            preflight=self.preflight,
            execution_completed=True,
            evidence=evidence_for(state, request_id="post-1", captured_at=40),
            expected_run_id="run-1",
            expected_request_id="post-1",
            last_action_at=30,
        )
        self.assertEqual(decision.run_status, "PASS")


    def test_missing_post_request_id_is_inconclusive(self):
        state = fixture_state("AE-PILOT-004")
        state["layers"][0]["transform"]["position"] = {"x": 960, "y": 540}
        decision = self.verifier.verify_post(
            skill_id="AE-PILOT-004",
            preflight=self.preflight,
            execution_completed=True,
            evidence=evidence_for(state, request_id="post-1", captured_at=40),
            expected_run_id="run-1",
            expected_request_id=None,
            last_action_at=30,
        )
        self.assertEqual(decision.run_status, "INCONCLUSIVE")
        self.assertEqual(decision.reason_code, "REQUEST_ID_REQUIRED")

    def test_reader_not_ok_after_execution_is_inconclusive(self):
        state = fixture_state("AE-PILOT-004")
        decision = self.verifier.verify_post(
            skill_id="AE-PILOT-004",
            preflight=self.preflight,
            execution_completed=True,
            evidence=evidence_for(
                state,
                request_id="post-1",
                captured_at=40,
                status="INVALID_RESPONSE",
            ),
            expected_run_id="run-1",
            expected_request_id="post-1",
            last_action_at=30,
        )
        self.assertEqual(decision.run_status, "INCONCLUSIVE")
        self.assertEqual(decision.reason_code, "READER_NOT_OK")

    def test_post_state_from_different_fixture_is_inconclusive(self):
        state = fixture_state("AE-PILOT-004")
        state["layers"][0]["transform"]["position"] = {"x": 960, "y": 540}
        decision = self.verifier.verify_post(
            skill_id="AE-PILOT-004",
            preflight=self.preflight,
            execution_completed=True,
            evidence=evidence_for(
                state,
                request_id="post-1",
                captured_at=40,
                file_path=r"C:\\pilot\\run\\different.aep",
            ),
            expected_run_id="run-1",
            expected_request_id="post-1",
            last_action_at=30,
        )
        self.assertEqual(decision.run_status, "INCONCLUSIVE")
        self.assertEqual(
            decision.reason_code,
            "POST_FIXTURE_IDENTITY_MISMATCH",
        )

    def test_ui_change_evidence_does_not_override_completed_verified_run(self):
        state = fixture_state("AE-PILOT-004")
        state["layers"][0]["transform"]["position"] = {"x": 960, "y": 540}
        decision = self.verifier.verify_post(
            skill_id="AE-PILOT-004",
            preflight=self.preflight,
            execution_completed=True,
            evidence=evidence_for(
                state,
                request_id="post-1",
                captured_at=40,
            ),
            expected_run_id="run-1",
            expected_request_id="post-1",
            last_action_at=30,
            ui_change_evidence={
                "route_changed": True,
                "capability_still_exists": True,
                "evidence": "route changed but execution still completed",
            },
        )
        self.assertEqual(decision.run_status, "PASS")

    def test_wrong_post_state_is_verification_failed(self):
        state = fixture_state("AE-PILOT-004")
        decision = self.verifier.verify_post(
            skill_id="AE-PILOT-004",
            preflight=self.preflight,
            execution_completed=True,
            evidence=evidence_for(state, request_id="post-1", captured_at=40),
            expected_run_id="run-1",
            expected_request_id="post-1",
            last_action_at=30,
        )
        self.assertEqual(decision.run_status, "VERIFICATION_FAILED")

    def test_stale_post_state_is_inconclusive(self):
        state = fixture_state("AE-PILOT-004")
        state["layers"][0]["transform"]["position"] = {"x": 960, "y": 540}
        decision = self.verifier.verify_post(
            skill_id="AE-PILOT-004",
            preflight=self.preflight,
            execution_completed=True,
            evidence=evidence_for(state, request_id="post-1", captured_at=29),
            expected_run_id="run-1",
            expected_request_id="post-1",
            last_action_at=30,
        )
        self.assertEqual(decision.run_status, "INCONCLUSIVE")
        self.assertEqual(decision.reason_code, "STALE_EVIDENCE")


    def test_duplicate_capabilities_are_rejected_as_inconclusive(self):
        state = fixture_state("AE-PILOT-004")
        evidence = evidence_for(state, request_id="post-1", captured_at=40)
        evidence["capabilities"]["supported_capabilities"].append(
            evidence["capabilities"]["supported_capabilities"][0]
        )
        decision = self.verifier.verify_post(
            skill_id="AE-PILOT-004",
            preflight=self.preflight,
            execution_completed=True,
            evidence=evidence,
            expected_run_id="run-1",
            expected_request_id="post-1",
            last_action_at=30,
        )
        self.assertEqual(decision.run_status, "INCONCLUSIVE")
        self.assertEqual(decision.reason_code, "MALFORMED_EVIDENCE")

    def test_missing_post_evidence_is_inconclusive(self):
        decision = self.verifier.verify_post(
            skill_id="AE-PILOT-004",
            preflight=self.preflight,
            execution_completed=True,
            evidence=None,
            expected_run_id="run-1",
            expected_request_id="post-1",
            last_action_at=30,
        )
        self.assertEqual(decision.run_status, "INCONCLUSIVE")

    def test_incomplete_execution_is_execution_failed(self):
        decision = self.verifier.verify_post(
            skill_id="AE-PILOT-004",
            preflight=self.preflight,
            execution_completed=False,
            evidence=None,
            expected_run_id="run-1",
            expected_request_id=None,
            last_action_at=30,
        )
        self.assertEqual(decision.run_status, "EXECUTION_FAILED")

    def test_ui_changed_requires_explicit_evidence(self):
        decision = self.verifier.verify_post(
            skill_id="AE-PILOT-004",
            preflight=self.preflight,
            execution_completed=False,
            evidence=None,
            expected_run_id="run-1",
            expected_request_id=None,
            last_action_at=30,
            ui_change_evidence={
                "route_changed": True,
                "capability_still_exists": True,
                "evidence": "independent UIA observation",
            },
        )
        self.assertEqual(decision.run_status, "UI_CHANGED")


class AggregateTests(unittest.TestCase):
    def setUp(self):
        self.verifier = DeterministicVerifier(contract())

    def test_three_passes_verify_skill(self):
        result = self.verifier.aggregate_skill(["PASS", "PASS", "PASS"])
        self.assertEqual(result.skill_status, "VERIFIED")

    def test_completed_failure_is_not_verified(self):
        result = self.verifier.aggregate_skill(["PASS", "PASS", "VERIFICATION_FAILED"])
        self.assertEqual(result.skill_status, "NOT_VERIFIED")

    def test_ambiguous_run_needs_review(self):
        result = self.verifier.aggregate_skill(["PASS", "PASS", "INCONCLUSIVE"])
        self.assertEqual(result.skill_status, "NEEDS_REVIEW")

    def test_too_few_runs_needs_review(self):
        result = self.verifier.aggregate_skill(["PASS"])
        self.assertEqual(result.skill_status, "NEEDS_REVIEW")


class CalibrationTests(unittest.TestCase):
    def test_software_self_calibration_behaves_exactly_but_does_not_satisfy_pilot_gate(self):
        result = run_calibration(contract())
        self.assertTrue(result["passed"])
        self.assertFalse(result["satisfies_pilot_gate"])
        self.assertEqual(result["controls"]["CAL-POSITIVE"]["actual"], "PASS")
        self.assertEqual(result["controls"]["CAL-NEGATIVE"]["actual"], "VERIFICATION_FAILED")
        self.assertEqual(result["controls"]["CAL-STALE"]["actual"], "INCONCLUSIVE")

    def test_pilot_calibration_with_fresh_canonical_fixture_evidence_satisfies_gate(self):
        c = contract()
        state = fixture_state("AE-PILOT-002")
        evidence = evidence_for(
            state,
            run_id="cal-live-run",
            request_id="cal-live-request",
            captured_at=20,
        )
        result = run_pilot_calibration(
            c,
            evidence=evidence,
            fixture_id="FX-002-COMP-EMPTY",
            expected_run_id="cal-live-run",
            expected_request_id="cal-live-request",
            min_captured_at=10,
        )
        self.assertTrue(result["passed"])
        self.assertTrue(result["satisfies_pilot_gate"])
        self.assertEqual(result["controls"]["CAL-POSITIVE"]["actual"], "PASS")
        self.assertEqual(result["controls"]["CAL-NEGATIVE"]["actual"], "VERIFICATION_FAILED")
        self.assertEqual(result["controls"]["CAL-STALE"]["actual"], "INCONCLUSIVE")

    def test_pilot_calibration_rejects_stale_canonical_evidence(self):
        c = contract()
        evidence = evidence_for(
            fixture_state("AE-PILOT-002"),
            run_id="cal-live-run",
            request_id="cal-live-request",
            captured_at=5,
        )
        result = run_pilot_calibration(
            c,
            evidence=evidence,
            fixture_id="FX-002-COMP-EMPTY",
            expected_run_id="cal-live-run",
            expected_request_id="cal-live-request",
            min_captured_at=10,
        )
        self.assertFalse(result["passed"])
        self.assertFalse(result["satisfies_pilot_gate"])


if __name__ == "__main__":
    unittest.main()
