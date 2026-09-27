import json
import os
import shutil
import subprocess
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

import yaml

from ufo_lab import (
    UFOFollowerExecutor,
    UFOInstallation,
    UFOInstallationError,
    UFOReferenceLock,
    UFOWorkspaceManager,
    compile_all_plans,
    compile_skill_plan,
    write_compiled_plan,
)
from verifier.contract import PilotContract


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "pilot_10_skills.yaml"
LOCK_PATH = ROOT / "ufo_lab" / "UPSTREAM_UFO.lock.json"


def contract():
    return PilotContract.load(CONTRACT_PATH)


def reference_lock():
    return UFOReferenceLock.load(LOCK_PATH)


def _run_git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout.strip()


def make_fake_ufo_repo(root: Path) -> str:
    files = {
        "ufo/__init__.py": "",
        "ufo/__main__.py": r'''
import argparse
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--task", required=True)
parser.add_argument("--mode", required=True)
parser.add_argument("--plan", required=True)
parser.add_argument("--log-level")
args = parser.parse_args()

assert args.mode == "follower"
plan = Path(args.plan)
assert plan.is_file()
log_dir = Path("logs") / args.task
log_dir.mkdir(parents=True, exist_ok=True)
(log_dir / "execution.txt").write_text(plan.read_text(encoding="utf-8"), encoding="utf-8")
print("FAKE UFO FOLLOWER COMPLETED")
''',
        "ufo/ufo.py": '''
# structural reference tokens
"--mode"
"follower"
"--plan"
''',
        "ufo/module/sessions/plan_reader.py": '''
class PlanReader:
    def __init__(self):
        self.plan = {}
    def next_step(self):
        return None
    def get_steps(self):
        return self.plan.get("steps", [])
''',
        "ufo/module/sessions/session.py": '''
class FollowerSession:
    def __init__(self, plan_file):
        self.plan_reader = PlanReader(plan_file)
        self.context.set(ContextNames.MODE, "follower")
''',
        "ufo/module/session_pool.py": '''
def create(mode):
    if False:
        pass
    elif mode == "follower":
        return FollowerSession("x")
''',
        "ufo/automator/ui_control/controller.py": '''
def click_input(): pass
def click_on_coordinates(): pass
def drag_on_coordinates(): pass
def keyboard_input(): pass
def key_press(): pass
def scroll(): pass
def mouse_move(): pass
def type(): pass
''',
        "config/config_loader.py": '''
import os
ENV = os.getenv("UFO_ENV", "production")
def overlay(yaml_file, env):
    return f"{yaml_file.stem}_{env}.yaml"
''',
        "config/ufo/system.yaml": '''
CONTROL_BACKEND: ["uia"]
USE_MCP: true
MAX_ROUND: 1
MAX_STEP: 50
''',
    }

    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content.strip() + "\n", encoding="utf-8")

    _run_git(root, "init")
    _run_git(root, "config", "user.email", "pilot@example.invalid")
    _run_git(root, "config", "user.name", "Pilot Test")
    _run_git(root, "add", ".")
    _run_git(root, "commit", "-m", "fake ufo reference")
    return _run_git(root, "rev-parse", "HEAD")


def fake_lock(head: str) -> UFOReferenceLock:
    base = reference_lock()
    return replace(base, reference_commit=head)


class UFOPlanTests(unittest.TestCase):
    def test_all_ten_skills_compile_to_follower_plans(self):
        plans = compile_all_plans(contract())
        self.assertEqual(len(plans), 10)
        self.assertEqual([plan.skill_id for plan in plans], list(contract().skills.keys()))
        self.assertTrue(all(plan.steps for plan in plans))

    def test_plan_has_exact_follower_shape_and_ui_only_guard(self):
        plan = compile_skill_plan(contract(), "AE-PILOT-004")
        payload = plan.to_ufo_dict()
        self.assertEqual(set(payload), {"task", "steps", "object"})
        self.assertEqual(payload["object"], "Adobe After Effects")
        self.assertEqual(len(payload["steps"]), 3)
        for step in payload["steps"]:
            self.assertIn("Use only visible Adobe After Effects UI interactions", step)
            self.assertIn("Do not use scripts", step)

    def test_plan_hash_is_deterministic(self):
        first = compile_skill_plan(contract(), "AE-PILOT-007")
        second = compile_skill_plan(contract(), "AE-PILOT-007")
        self.assertEqual(first.plan_sha256, second.plan_sha256)

    def test_written_manifest_never_treats_ufo_finish_as_success(self):
        plan = compile_skill_plan(contract(), "AE-PILOT-002")
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "plan.json"
            result = write_compiled_plan(plan, output)
            manifest = json.loads(
                Path(result["manifest_path"]).read_text(encoding="utf-8")
            )
            self.assertTrue(manifest["ufo_finish_is_not_success"])
            self.assertEqual(
                manifest["success_oracle"],
                "external_deterministic_verifier",
            )


class UFOInstallationTests(unittest.TestCase):
    def test_reference_lock_is_pinned(self):
        lock = reference_lock()
        self.assertEqual(
            lock.reference_commit,
            "e2a03126241c696fdaf9a669a271ca3fca6d9916",
        )
        self.assertEqual(lock.execution_mode, "follower")
        self.assertEqual(lock.required_control_backend, ["uia"])
        self.assertFalse(lock.lab_policy["use_mcp"])

    def test_structural_and_git_provenance_check(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            head = make_fake_ufo_repo(root)
            installation = UFOInstallation(root, fake_lock(head))
            inspection = installation.inspect()
            self.assertTrue(inspection.structurally_compatible)
            self.assertTrue(inspection.exact_reference_commit)
            self.assertFalse(inspection.git_dirty)
            installation.require_launchable()

    def test_dirty_ufo_checkout_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            head = make_fake_ufo_repo(root)
            (root / "dirty.txt").write_text("dirty", encoding="utf-8")
            installation = UFOInstallation(root, fake_lock(head))
            with self.assertRaises(UFOInstallationError):
                installation.require_launchable()

    def test_compatible_fork_requires_explicit_override(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            head = make_fake_ufo_repo(root)
            installation = UFOInstallation(
                root,
                replace(fake_lock(head), reference_commit="0" * 40),
            )
            with self.assertRaises(UFOInstallationError):
                installation.require_launchable()
            inspection = installation.require_launchable(
                allow_compatible_fork=True,
            )
            self.assertTrue(inspection.structurally_compatible)
            self.assertFalse(inspection.exact_reference_commit)


class UFOWorkspaceTests(unittest.TestCase):
    def test_pilot_overlay_disables_non_ui_paths_and_expands_round_budget(self):
        overlay = UFOWorkspaceManager.pilot_overlay(plan_step_count=6)
        self.assertEqual(overlay["CONTROL_BACKEND"], ["uia"])
        self.assertFalse(overlay["USE_MCP"])
        self.assertFalse(overlay["MCP_FALLBACK_TO_UI"])
        self.assertFalse(overlay["EVA_SESSION"])
        self.assertEqual(overlay["SAVE_EXPERIENCE"], "always_not")
        self.assertEqual(overlay["MAX_ROUND"], 8)
        self.assertGreaterEqual(overlay["MAX_STEP"], 50)
        self.assertEqual(overlay["INPUT_TEXT_API"], "type_keys")

    def test_overlay_is_written_only_to_detached_worktree(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "ufo"
            root.mkdir()
            head = make_fake_ufo_repo(root)
            installation = UFOInstallation(root, fake_lock(head))
            manager = UFOWorkspaceManager(
                installation,
                base_dir=Path(temp) / "worktrees",
            )
            workspace = manager.create(plan_step_count=3)
            try:
                overlay = workspace.worktree_root / "config" / "ufo" / "system_pilot.yaml"
                self.assertTrue(overlay.is_file())
                self.assertFalse((root / "config" / "ufo" / "system_pilot.yaml").exists())
                parsed = yaml.safe_load(overlay.read_text(encoding="utf-8"))
                self.assertFalse(parsed["USE_MCP"])
                self.assertEqual(parsed["MAX_ROUND"], 5)
            finally:
                manager.remove(workspace.worktree_root)
            self.assertFalse(workspace.worktree_root.exists())
            self.assertFalse(_run_git(root, "status", "--porcelain"))


class UFOExecutorTests(unittest.TestCase):
    def test_executor_runs_follower_in_isolated_worktree_and_preserves_logs(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "ufo"
            root.mkdir()
            head = make_fake_ufo_repo(root)
            lock = fake_lock(head)
            installation = UFOInstallation(root, lock)
            artifacts = Path(temp) / "artifacts"

            executor = UFOFollowerExecutor(
                contract(),
                lock,
                installation,
                artifact_root=artifacts,
            )
            # Keep worktrees inside the test temp directory.
            executor.workspace_manager = UFOWorkspaceManager(
                installation,
                base_dir=Path(temp) / "worktrees",
            )

            record = executor.execute(
                skill_id="AE-PILOT-002",
                run_id="ufo-test-run-1",
                timeout=30,
            )
            self.assertTrue(record.process_exit_zero)
            self.assertFalse(record.timed_out)
            self.assertEqual(record.success_oracle, "external_deterministic_verifier")
            self.assertTrue(Path(record.stdout_path).is_file())
            self.assertTrue(Path(record.plan_path).is_file())
            self.assertTrue(Path(record.plan_manifest_path).is_file())
            self.assertIsNotNone(record.ufo_logs_path)
            self.assertTrue(
                (Path(record.ufo_logs_path) / "execution.txt").is_file()
            )
            execution_record = json.loads(
                (Path(record.stdout_path).parent / "execution.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertTrue(execution_record["ufo_finish_is_not_success"])
            self.assertEqual(execution_record["ufo_git_head"], head)
            self.assertFalse(_run_git(root, "status", "--porcelain"))

    def test_executor_rejects_run_id_reuse(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "ufo"
            root.mkdir()
            head = make_fake_ufo_repo(root)
            lock = fake_lock(head)
            installation = UFOInstallation(root, lock)
            executor = UFOFollowerExecutor(
                contract(),
                lock,
                installation,
                artifact_root=Path(temp) / "artifacts",
            )
            executor.workspace_manager = UFOWorkspaceManager(
                installation,
                base_dir=Path(temp) / "worktrees",
            )
            executor.execute(
                skill_id="AE-PILOT-001",
                run_id="same-run",
                timeout=30,
            )
            with self.assertRaises(Exception):
                executor.execute(
                    skill_id="AE-PILOT-001",
                    run_id="same-run",
                    timeout=30,
                )


if __name__ == "__main__":
    unittest.main()
