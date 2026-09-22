import subprocess
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import wizard
from resolver import LinuxCNCInfo


class WizardBuildTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="wizard build ")
        self.addCleanup(self.directory.cleanup)
        self.manifest = Path(self.directory.name) / "configuration.yaml"
        self.manifest.write_text("metadata: {}\n")
        for target, value in (("platform.system", "Linux"), ("os.geteuid", 1000)):
            mock = patch("wizard." + target, return_value=value)
            mock.start()
            self.addCleanup(mock.stop)

    @patch("wizard.subprocess.run")
    @patch("wizard.yes_no", return_value=False)
    def test_decline_keeps_manifest_without_launching(self, prompt, run):
        self.assertEqual(wizard.offer_image_build(self.manifest), 0)
        run.assert_not_called()
        self.assertTrue(self.manifest.is_file())

    @patch("wizard.subprocess.run", return_value=subprocess.CompletedProcess([], 0))
    @patch("wizard.yes_no", return_value=True)
    def test_accept_uses_same_python_and_absolute_paths(self, prompt, run):
        self.assertEqual(wizard.offer_image_build(self.manifest), 0)
        command = run.call_args.args[0]
        self.assertEqual(command[:2], ["sudo", wizard.sys.executable])
        self.assertEqual(Path(command[2]), Path(wizard.__file__).resolve().with_name("image_builder.py"))
        self.assertEqual(command[3], str(self.manifest.resolve()))
        self.assertEqual(command[4:], ["--build-image", "--check-host"])

    @patch("wizard.os.geteuid", return_value=0)
    @patch("wizard.subprocess.run", return_value=subprocess.CompletedProcess([], 2))
    @patch("wizard.yes_no", return_value=True)
    def test_root_launch_and_failure_status(self, prompt, run, uid):
        self.assertEqual(wizard.offer_image_build(self.manifest), 2)
        self.assertEqual(run.call_args.args[0][0], wizard.sys.executable)
        self.assertTrue(self.manifest.is_file())

    @patch("wizard.platform.system", return_value="Windows")
    @patch("wizard.subprocess.run")
    @patch("wizard.yes_no")
    def test_other_hosts_only_save_configuration(self, prompt, run, system):
        self.assertEqual(wizard.offer_image_build(self.manifest), 0)
        prompt.assert_not_called()
        run.assert_not_called()

    @patch("wizard.subprocess.run", side_effect=FileNotFoundError("sudo unavailable"))
    @patch("wizard.yes_no", return_value=True)
    def test_launch_failure_preserves_configuration(self, prompt, run):
        self.assertEqual(wizard.offer_image_build(self.manifest), 1)
        self.assertTrue(self.manifest.is_file())

    @patch("wizard.yes_no", side_effect=EOFError)
    @patch("wizard.subprocess.run")
    def test_closed_input_does_not_launch(self, run, prompt):
        self.assertEqual(wizard.offer_image_build(self.manifest), 0)
        run.assert_not_called()

    def test_full_wizard_saves_manifest_before_launch(self):
        previous = Path.cwd()
        self.addCleanup(os.chdir, previous)
        os.chdir(self.directory.name)

        def build(command, **kwargs):
            manifest = Path(command[3])
            saved = wizard.yaml.safe_load(manifest.read_text())
            self.assertEqual(saved["metadata"]["name"], "integration")
            self.assertEqual(saved["hardware"]["linuxcnc"]["version"], "2.9.8")
            self.assertEqual(saved["core"], wizard.core_placeholder())
            self.assertEqual(saved["gui"], {"enabled": False, "provider": None})
            self.assertIn("password_hash", saved["system"]["user"])
            self.assertNotIn("password", saved["system"]["user"])
            self.assertEqual(manifest.stat().st_mode & 0o777, 0o600)
            return subprocess.CompletedProcess(command, 0)

        with patch("wizard.Resolver.latest_linuxcnc", return_value=LinuxCNCInfo("2.9.8", 2, 4)), \
             patch("wizard.ask_password_hash", return_value="$6$salt$" + "a" * 86), \
             patch("webgui_resolver.WebGUIResolver.resolve", side_effect=AssertionError("LCNC Suite must not be queried")), \
             patch("builtins.input", side_effect=["", "4", "", "integration", "y"]), \
             patch("wizard.subprocess.run", side_effect=build) as run:
            self.assertEqual(wizard.main(), 0)
            run.assert_called_once()
