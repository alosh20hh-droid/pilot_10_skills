import hashlib
import json
import tempfile
import subprocess
import unittest
from pathlib import Path
from unittest import mock

from ufo_adapter import (
    UFOExecutionError,
    UFOMeasuredRunner,
    UFOWorkspaceManager,
    compile_all_plans,
    compile_skill_plan,
    load_upstream_lock,
)
from verifier.contract import PilotContract


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = PilotContract.load(ROOT / "pilot_10_skills.yaml")


def make_fake_git_ufo(root: Path):
    files = {
        "config/ufo/system.yaml": "MAX_ROUND: 1\nCONTROL_BACKEND: [uia]\n",
        "config/ufo/mcp.yaml": (
            "HostAgent:\n"
            "  default:\n"
            "    action:\n"
            "      - namespace: CommandLineExecutor\n"
            "        type: local\n"
            "AppAgent:\n"
            "  default:\n"
            "    action:\n"
            "      - namespace: CommandLineExecutor\n"
            "        type: local\n"
        ),
        "ufo/__main__.py": "# fake\n",
    }
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    subprocess.run(["git", "-C", str(root), "init"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "pilot@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "Pilot Test"], check=True)
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-m", "fake"], check=True, capture_output=True)
    head = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return head


def make_fixture(root: Path, fixture_id: str, run_id: str = "run-1"):
    run_key = hashlib.sha256(run_id.encode("utf-8")).hexdigest()
    directory = root / run_key
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{fixture_id}.aep"
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
        self.assertIn(skill["goal"], plan.to_dict()["task"])
        self.assertIn("visible UI interactions only", plan.to_dict()["task"])

    def test_compiler_rejects_hidden_script_route(self):
        import copy
        bad = copy.deepcopy(CONTRACT.raw)
        bad["skills"][0]["measured_ui_steps"] = [
            "Use ExtendScript to create the composition."
        ]
        with tempfile.TemporaryDirectory() as temp:
            import yaml
            path = Path(temp) / "bad.yaml"
            path.write_text(yaml.safe_dump(bad, sort_keys=False), encoding="utf-8")
            bad_contract = PilotContract.load(path)
            with self.assertRaises(Exception):
                compile_skill_plan(bad_contract, bad_contract.raw["skills"][0]["id"])

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
        self.assertIn("config/config_loader.py", lock["required_files"])
        self.assertIn("ufo/module/basic.py", lock["required_files"])
        self.assertIn("config/ufo/mcp.yaml", lock["required_files"])
        self.assertIn("ufo/client/computer.py", lock["required_files"])
        self.assertIn("ufo/module/dispatcher.py", lock["required_files"])
        self.assertFalse(lock["execution_overlay"]["required_settings"]["USE_APIS"])
        self.assertFalse(lock["execution_overlay"]["required_settings"]["USE_MCP"])
        self.assertEqual(lock["execution_overlay"]["environment"], "test")
        self.assertEqual(lock["execution_overlay"]["file"], "config/ufo/system_test.yaml")
        self.assertEqual(
            lock["execution_route_policy"]["allowed_action_namespaces"],
            ["HostUIExecutor", "AppUIExecutor"],
        )
        self.assertIn(
            "CommandLineExecutor",
            lock["execution_route_policy"]["forbidden_namespaces"],
        )

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


class UFOWorkspaceTests(unittest.TestCase):
    def test_overlay_forces_ui_only_execution_and_enough_follower_rounds(self):
        overlay = UFOWorkspaceManager.build_overlay(4)
        self.assertEqual(overlay["CONTROL_BACKEND"], ["uia"])
        self.assertFalse(overlay["USE_APIS"])
        self.assertFalse(overlay["USE_MCP"])
        self.assertFalse(overlay["MCP_FALLBACK_TO_UI"])
        self.assertFalse(overlay["EVA_SESSION"])
        self.assertEqual(overlay["SAVE_EXPERIENCE"], "always_not")
        self.assertEqual(overlay["MAX_ROUND"], 6)
        self.assertGreaterEqual(overlay["MAX_STEP"], 50)

    def test_mcp_policy_exposes_only_ui_collection_and_ui_actions(self):
        policy = UFOWorkspaceManager.build_ui_only_mcp_policy()
        self.assertEqual(set(policy), {"HostAgent", "AppAgent"})

        host = policy["HostAgent"]["default"]
        app = policy["AppAgent"]["default"]
        self.assertEqual(
            [item["namespace"] for item in host["data_collection"]],
            ["UICollector"],
        )
        self.assertEqual(
            [item["namespace"] for item in host["action"]],
            ["HostUIExecutor"],
        )
        self.assertEqual(
            [item["namespace"] for item in app["data_collection"]],
            ["UICollector"],
        )
        self.assertEqual(
            [item["namespace"] for item in app["action"]],
            ["AppUIExecutor"],
        )
        serialized = json.dumps(policy)
        for forbidden in (
            "CommandLineExecutor",
            "WordCOMExecutor",
            "ExcelCOMExecutor",
            "PowerPointCOMExecutor",
            "BashExecutor",
            "HardwareExecutor",
        ):
            self.assertNotIn(forbidden, serialized)

    def test_overlay_is_written_only_to_detached_worktree(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "ufo"
            root.mkdir()
            head = make_fake_git_ufo(root)
            manager = UFOWorkspaceManager(
                root,
                base_dir=Path(temp) / "worktrees",
            )
            workspace = manager.create(
                commit=head,
                measured_step_count=3,
            )
            try:
                overlay_path = Path(workspace.overlay_path)
                self.assertTrue(overlay_path.is_file())
                self.assertFalse(
                    (root / "config" / "ufo" / "system_test.yaml").exists()
                )
                import yaml
                overlay = yaml.safe_load(overlay_path.read_text(encoding="utf-8"))
                self.assertFalse(overlay["USE_APIS"])
                self.assertFalse(overlay["USE_MCP"])
                self.assertEqual(overlay["MAX_ROUND"], 5)

                mcp_path = Path(workspace.mcp_policy_path)
                self.assertTrue(mcp_path.is_file())
                safe_mcp = yaml.safe_load(mcp_path.read_text(encoding="utf-8"))
                safe_text = json.dumps(safe_mcp)
                self.assertIn("HostUIExecutor", safe_text)
                self.assertIn("AppUIExecutor", safe_text)
                self.assertNotIn("CommandLineExecutor", safe_text)

                original_mcp = (root / "config" / "ufo" / "mcp.yaml").read_text(
                    encoding="utf-8"
                )
                self.assertIn("CommandLineExecutor", original_mcp)
            finally:
                manager.remove(workspace.worktree_root)

            self.assertFalse(Path(workspace.worktree_root).exists())
            status = subprocess.run(
                ["git", "-C", str(root), "status", "--porcelain"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            self.assertEqual(status, "")


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


    def test_execution_rejects_non_finite_or_non_positive_timeout(self):
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
            for timeout in (0, -1, float("nan"), float("inf")):
                with self.assertRaises(UFOExecutionError):
                    runner.execute(
                        run_id="run-timeout",
                        plan=plan,
                        fixture_path=fixture,
                        fixture_sha256=fixture_hash,
                        arm_measured_execution=True,
                        timeout=timeout,
                    )

    def test_prepare_run_writes_plan_and_rejects_run_id_reuse(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            runner = UFOMeasuredRunner(
                root,
                output_root=root / "runs",
            )
            plan = compile_skill_plan(CONTRACT, "AE-PILOT-003")
            fixture, fixture_hash = make_fixture(
                root, plan.fixture_id, "unique-run"
            )
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
            self.assertEqual(payload["object"], "AfterFX.exe")
            self.assertEqual(prepared["plan_sha256"], plan.sha256())
            with self.assertRaises(UFOExecutionError):
                runner.prepare_run(
                    run_id="unique-run",
                    plan=plan,
                    fixture_path=fixture,
                    fixture_sha256=fixture_hash,
                )

    def test_run_id_remains_reserved_even_if_run_directory_is_deleted(self):
        import shutil
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            runner = UFOMeasuredRunner(
                root,
                output_root=root / "runs",
                run_registry_root=root / "registry",
            )
            plan = compile_skill_plan(CONTRACT, "AE-PILOT-003")
            fixture, fixture_hash = make_fixture(
                root, plan.fixture_id, "persistent-ufo-run"
            )
            prepared = runner.prepare_run(
                run_id="persistent-ufo-run",
                plan=plan,
                fixture_path=fixture,
                fixture_sha256=fixture_hash,
            )
            shutil.rmtree(prepared["run_dir"])
            with self.assertRaises(UFOExecutionError):
                runner.prepare_run(
                    run_id="persistent-ufo-run",
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
            fixture, fixture_hash = make_fixture(
                root, plan.fixture_id, "preview-run-1"
            )
            preview = runner.preview_command(
                run_id="preview-run-1",
                plan=plan,
                fixture_path=fixture,
                fixture_sha256=fixture_hash,
            )
            self.assertFalse((root / "runs").exists())
            self.assertEqual(preview["plan_sha256"], plan.sha256())
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
            fixture, _ = make_fixture(
                root, plan.fixture_id, "run-hash-check"
            )
            with self.assertRaises(UFOExecutionError):
                runner.prepare_run(
                    run_id="run-hash-check",
                    plan=plan,
                    fixture_path=fixture,
                    fixture_sha256="0" * 64,
                )

    def test_canonical_or_non_run_workspace_fixture_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            runner = UFOMeasuredRunner(root, output_root=root / "runs")
            plan = compile_skill_plan(CONTRACT, "AE-PILOT-004")
            canonical_dir = root / "fixtures" / "canonical"
            canonical_dir.mkdir(parents=True)
            fixture = canonical_dir / f"{plan.fixture_id}.aep"
            payload = b"fixture"
            fixture.write_bytes(payload)
            fixture_hash = hashlib.sha256(payload).hexdigest()
            with self.assertRaises(UFOExecutionError):
                runner.prepare_run(
                    run_id="run-canonical-check",
                    plan=plan,
                    fixture_path=fixture,
                    fixture_sha256=fixture_hash,
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
