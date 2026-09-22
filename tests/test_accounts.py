import ctypes
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from accounts import AccountError, hash_password, provision_user
from image_builder import ImageBuilder
from schema import ManifestError, validate_manifest
from wizard import ask_password_hash


class AccountTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.password_hash = hash_password("test password")

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        (self.root / "etc/skel").mkdir(parents=True)
        (self.root / "etc/skel/.bashrc").write_text("# skeleton\n")
        (self.root / "etc/passwd").write_text("root:x:0:0:root:/root:/bin/bash\npi:x:1000:1000::/home/pi:/bin/bash\n")
        (self.root / "etc/group").write_text("root:x:0:\npi:x:1000:\nshadow:x:42:\nsudo:x:27:pi\ndialout:x:20:pi\ndisk:x:6:\n")
        (self.root / "etc/sudoers").write_text("root ALL=(ALL:ALL) ALL\n%sudo ALL=(ALL:ALL) NOPASSWD: ALL\n")
        self.user = {"name": "aphys", "sudo": True, "password_hash": self.password_hash}
        self.manifest = {
            "metadata": {"name": "account-test", "schema_version": "1.0", "created_at": "2026-09-20T12:00:00+00:00"},
            "hardware": {"platform": "Raspberry Pi 5", "architecture": "arm64",
                         "os": {"architecture": "arm64", "realtime": True}, "linuxcnc": {"version": "2.9.8"}},
            "system": {"user": dict(self.user), "network": {"mode": "dhcp"}, "ssh": {"enabled": True}},
            "gui": {"enabled": True, "provider": "lcnc-suite"},
        }

    def test_hash_authenticates_with_system_crypt(self):
        crypt = ctypes.CDLL("libcrypt.so.1").crypt
        crypt.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
        crypt.restype = ctypes.c_char_p
        self.assertEqual(crypt(b"test password", self.password_hash.encode()).decode(), self.password_hash)
        self.assertNotEqual(crypt(b"wrong", self.password_hash.encode()).decode(), self.password_hash)
        self.assertNotEqual(hash_password("test password"), self.password_hash)

    def test_account_password_groups_home_and_sudo(self):
        provision_user(self.root, self.user)
        passwd = (self.root / "etc/passwd").read_text()
        self.assertIn("aphys:x:1001:1001:Aphys user:/home/aphys:/bin/bash", passwd)
        self.assertIn("pi:x:1000:1000", passwd)
        self.assertIn("aphys:" + self.password_hash + ":", (self.root / "etc/shadow").read_text())
        self.assertEqual(stat.S_IMODE((self.root / "etc/shadow").stat().st_mode), 0o640)
        self.assertEqual(stat.S_IMODE((self.root / "etc/sudoers").stat().st_mode), 0o440)
        self.assertEqual(stat.S_IMODE((self.root / "home/aphys").stat().st_mode), 0o750)
        self.assertTrue((self.root / "home/aphys/.bashrc").is_file())
        self.assertIn("dialout:x:20:pi,aphys", (self.root / "etc/group").read_text())
        self.assertIn("disk:x:6:\n", (self.root / "etc/group").read_text())
        self.assertIn("sudo:!::pi,aphys", (self.root / "etc/gshadow").read_text())
        policy = (self.root / "etc/sudoers").read_text()
        self.assertGreater(policy.index("aphys ALL=(ALL:ALL) PASSWD: ALL"), policy.index("NOPASSWD"))
        result = subprocess.run(["/usr/sbin/visudo", "-cf", str(self.root / "etc/sudoers")], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_repeat_updates_password_and_revokes_sudo(self):
        provision_user(self.root, self.user)
        replacement = hash_password("replacement")
        provision_user(self.root, dict(self.user, sudo=False, password_hash=replacement))
        self.assertEqual(sum(line.startswith("aphys:") for line in (self.root / "etc/passwd").read_text().splitlines()), 1)
        self.assertIn("aphys:" + replacement, (self.root / "etc/shadow").read_text())
        self.assertIn("sudo:x:27:pi\n", (self.root / "etc/group").read_text())
        policy = (self.root / "etc/sudoers").read_text()
        self.assertIn("aphys ALL=(ALL:ALL) !ALL", policy)
        self.assertNotIn("aphys ALL=(ALL:ALL) PASSWD", policy)

    def test_refuses_system_account_and_symlink_home(self):
        with self.assertRaises(AccountError):
            provision_user(self.root, dict(self.user, name="root"))
        (self.root / "home").mkdir()
        (self.root / "home/aphys").symlink_to(self.root / "etc", target_is_directory=True)
        before = (self.root / "etc/passwd").read_text()
        with self.assertRaises(AccountError):
            provision_user(self.root, self.user)
        self.assertEqual((self.root / "etc/passwd").read_text(), before)

    def test_render_applies_account_without_leaking_hash_to_metadata(self):
        manifest = self.manifest
        manifest["system"]["user"] = self.user
        ImageBuilder(self.root / "work").render_manifest(manifest, self.root)
        self.assertIn(self.password_hash, (self.root / "etc/shadow").read_text())
        for metadata in (self.root / "etc/aphys").glob("*.yaml"):
            self.assertNotIn(self.password_hash, metadata.read_text())
        self.assertTrue(yaml.safe_load((self.root / "etc/aphys/user.yaml").read_text())["provisioned"])
        for value in ("root", "nobody"):
            manifest["system"]["user"]["name"] = value
            with self.assertRaises(ManifestError):
                validate_manifest(manifest)

    def test_wizard_default_and_password_confirmation(self):
        with patch("wizard.getpass.getpass", return_value=""), patch("wizard.hash_password", return_value="hash") as hashed:
            self.assertEqual(ask_password_hash(), "hash")
            hashed.assert_called_once_with("aphys")
        with patch("wizard.getpass.getpass", side_effect=["first", "mismatch", "custom", "custom"]), patch("wizard.hash_password", return_value="hash") as hashed:
            self.assertEqual(ask_password_hash(), "hash")
            hashed.assert_called_once_with("custom")

    def test_hash_rejects_empty_and_multiline_passwords(self):
        for value in ("", "one\ntwo", "one\0two"):
            with self.assertRaises(AccountError):
                hash_password(value)

    def test_privileged_build_assigns_target_ownership_without_following_links(self):
        (self.root / "etc/skel/link").symlink_to("/etc/passwd")
        with patch("accounts.os.geteuid", return_value=0), patch("accounts.os.fchown") as file_owner, patch("accounts.os.chown") as owner:
            provision_user(self.root, self.user)
        self.assertEqual([call.args[1:] for call in file_owner.call_args_list], [(0, 0), (0, 0), (0, 42), (0, 42), (0, 0)])
        owner.assert_any_call(self.root / "home/aphys", 1001, 1001)
        owner.assert_any_call(self.root / "home/aphys/link", 1001, 1001, follow_symlinks=False)

    def test_legacy_manifest_uses_default_password(self):
        with patch("accounts.hash_password", return_value=self.password_hash) as hashed:
            provision_user(self.root, {"name": "aphys", "sudo": True})
        hashed.assert_called_once_with("aphys")

    def test_validation_rejects_plaintext_invalid_hash_and_non_boolean_sudo(self):
        for invalid in ({"password": "secret"}, {"password_hash": "bad"}, {"sudo": "false"}):
            manifest = self.manifest
            manifest["system"]["user"] = dict(self.user, **invalid)
            with self.assertRaises(ManifestError):
                validate_manifest(manifest)
