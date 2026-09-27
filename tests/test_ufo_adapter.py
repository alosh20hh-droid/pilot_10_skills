import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ufo_adapter import (
    UFOExecutionError,
    UFOMeasuredRunner,
    compile_all_plans,
    compile_skill_plan,
    load_upstream_lock,
)
from verifier.contract import PilotContract


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = PilotContract.load(ROOT / "pilot_10_skills.yaml")


def make_fixture(root: Path, fixture_id: str):
    path = root / f"{fixture_id}.aep"
    payload = ("fixture:" + fixture_id).encode("utf-8")
    path.write_bytes(payload)
    return path, hashlib.sha256(payload).hexdigest()


class UFOPlanTests(unittest.TestCase):
    def test_all_ten_skills_compile_to_follower_plans(self):
        plans = compile_all_plans(CONTRACT)
        self.assertEqual(len(plans), 10)
        self.assertEqual(
            [plan.skill_id for plan in plans],
            list(CONTRACT.skills.keys()),
        )
        for plan in plans:
            payload = plan.to_dict()
            self.assertEqual(payload["object"], "AfterFX.exe")
            self.assertFalse(payload["close"])
            self.assertEqual(
                payload["steps"],
                CONTRACT.skill(plan.skill_id)["measured_ui_steps"],
            )

    def test_compiler_preserves_measured_steps_verbatim(self):
        skill = CONTRACT.skill("AE-PILOT-004")
        plan = compile_skill_plan(CONTRACT, "AE-PILOT-004")
        self.assertEqual(plan.to_dict()["steps"], skill["measured_ui_steps"])
        self.assertEqual(plan.to_dict()["task"], skill["goal"])

    def test_plan_hash_is_deterministic(self):
        first = compile_skill_plan(CONTRACT, "AE-PILOT-007")
        second = compile_skill_plan(CONTRACT, "AE-PILOT-007")
        self.assertEqual(first.sha256(), second.sha256())


class UFOLockTests(unittest.TestCase):
    def test_upstream_lock_is_follower_only(self):
        lock = load_upstream_lock()
        self.assertEqual(lock["repository"], "microsoft/UFO")
        self.assertEqual(
            lock["commit"],
            "e2a03126241c696fdaf9a669a271ca3fca6d9916",
        )
        self.assertEqual(lock["required_mode"], "follower")
        self.assertIn("batch_normal", lock["forbidden_modes"])

    def test_audited_controller_capabilities_are_declared(self):
        lock = load_upstream_lock()
        capabilities = set(lock["controller_capabilities_observed"])
        self.assertTrue({
            "semantic_control_click",
            "relative_coordinate_drag",
            "keyboard_input",
            "mouse_move",
            "scroll",
        }.issubset(capabilities))


class UFORunnerTests(unittest.TestCase):
    def test_command_is_follower_mode_only(self):
        with tempfile.TemporaryDirectory() as temp:
            runner = UFOMeasuredRunner(
                temp,
                output_root=Path(temp) / "runs",
            )
            command = runner.build_command(
                "pilot/task",
                Path(temp) / "plan.json",
            )
            self.assertIn("--mode", command)
            index = command.index("--mode")
            self.assertEqual(command[index + 1], "follower")
            self.assertNotIn("batch_normal", command)
            self.assertNotIn("operator", command)

    def test_execution_requires_explicit_arm(self):
        with tempfile.TemporaryDirectory() as temp:
            runner = UFOMeasuredRunner(
                temp,
                output_root=Path(temp) / "runs",
            )
            plan = compile_skill_plan(CONTRACT, "AE-PILOT-001")
            fixture, fixture_hash = make_fixture(
                Path(temp),
                plan.fixture_id,
            )
            with self.assertRaises(UFOExecutionError):
                runner.execute(
                    run_id="run-1",
                    plan=plan,
                    fixture_path=fixture,
                    fixture_sha256=fixture_hash,
                    arm_measured_execution=False,
                )

    def test_prepare_run_writes_plan_and_rejects_run_id_reuse(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            runner = UFOMeasuredRunner(
                root,
                output_root=root / "runs",
            )
            plan = compile_skill_plan(CONTRACT, "AE-PILOT-003")
            fixture, fixture_hash = make_fixture(root, plan.fixture_id)
            prepared = runner.prepare_run(
                run_id="unique-run",
                plan=plan,
                fixture_path=fixture,
                fixture_sha256=fixture_hash,
            )
            self.assertTrue(prepared["plan_path"].is_file())
            payload = json.loads(
                prepared["plan_path"].read_text(encoding="utf-8")
            )
            self.assertEqual(payload["steps"], plan.to_dict()["steps"])
            self.assertEqual(payload["object"], str(fixture.resolve()))
            bound_plan = plan.bind_object(str(fixture.resolve()))
            self.assertEqual(prepared["plan_sha256"], bound_plan.sha256())
            with self.assertRaises(UFOExecutionError):
                runner.prepare_run(
                    run_id="unique-run",
                    plan=plan,
                    fixture_path=fixture,
                    fixture_sha256=fixture_hash,
                )

    def test_command_preview_does_not_consume_run_id(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            runner = UFOMeasuredRunner(
                root,
                output_root=root / "runs",
            )
            plan = compile_skill_plan(CONTRACT, "AE-PILOT-004")
            fixture, fixture_hash = make_fixture(root, plan.fixture_id)
            preview = runner.preview_command(
                run_id="preview-run-1",
                plan=plan,
                fixture_path=fixture,
                fixture_sha256=fixture_hash,
            )
            self.assertFalse((root / "runs").exists())
            self.assertEqual(
                preview["plan_sha256"],
                plan.bind_object(str(fixture.resolve())).sha256(),
            )
            prepared = runner.prepare_run(
                run_id="preview-run-1",
                plan=plan,
                fixture_path=fixture,
                fixture_sha256=fixture_hash,
            )
            self.assertTrue(prepared["plan_path"].is_file())

    def test_unsafe_run_id_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            runner = UFOMeasuredRunner(
                temp,
                output_root=Path(temp) / "runs",
            )
            plan = compile_skill_plan(CONTRACT, "AE-PILOT-004")
            fixture, fixture_hash = make_fixture(Path(temp), plan.fixture_id)
            with self.assertRaises(UFOExecutionError):
                runner.prepare_run(
                    run_id="../unsafe",
                    plan=plan,
                    fixture_path=fixture,
                    fixture_sha256=fixture_hash,
                )

    def test_wrong_fixture_hash_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            runner = UFOMeasuredRunner(root, output_root=root / "runs")
            plan = compile_skill_plan(CONTRACT, "AE-PILOT-004")
            fixture, _ = make_fixture(root, plan.fixture_id)
            with self.assertRaises(UFOExecutionError):
                runner.prepare_run(
                    run_id="run-hash-check",
                    plan=plan,
                    fixture_path=fixture,
                    fixture_sha256="0" * 64,
                )

    def test_wrong_fixture_filename_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            runner = UFOMeasuredRunner(root, output_root=root / "runs")
            plan = compile_skill_plan(CONTRACT, "AE-PILOT-004")
            wrong = root / "wrong.aep"
            wrong.write_bytes(b"fixture")
            wrong_hash = hashlib.sha256(b"fixture").hexdigest()
            with self.assertRaises(UFOExecutionError):
                runner.prepare_run(
                    run_id="run-name-check",
                    plan=plan,
                    fixture_path=wrong,
                    fixture_sha256=wrong_hash,
                )

    @mock.patch("ufo_adapter.runner.platform.system", return_value="Linux")
    def test_non_windows_execution_environment_is_rejected(self, _mock_system):
        with tempfile.TemporaryDirectory() as temp:
            runner = UFOMeasuredRunner(temp)
            with self.assertRaises(UFOExecutionError):
                runner.validate_environment()

    def test_plan_file_contains_no_hidden_execution_fields(self):
        plan = compile_skill_plan(CONTRACT, "AE-PILOT-010").to_dict()
        self.assertEqual(set(plan.keys()), {"task", "steps", "object", "close"})


if __name__ == "__main__":
    unittest.main()
