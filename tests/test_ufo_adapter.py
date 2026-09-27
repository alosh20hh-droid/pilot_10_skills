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
            with self.assertRaises(UFOExecutionError):
                runner.execute(
                    run_id="run-1",
                    plan=plan,
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
            prepared = runner.prepare_run(run_id="unique-run", plan=plan)
            self.assertTrue(prepared["plan_path"].is_file())
            payload = json.loads(
                prepared["plan_path"].read_text(encoding="utf-8")
            )
            self.assertEqual(payload["steps"], plan.to_dict()["steps"])
            with self.assertRaises(UFOExecutionError):
                runner.prepare_run(run_id="unique-run", plan=plan)

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
