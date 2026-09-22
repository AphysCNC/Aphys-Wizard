import tempfile
import os
import shutil
import unittest
from pathlib import Path
from unittest.mock import patch

from image_builder import ImageBuilder, ImageBuilderError


class SSHTests(unittest.TestCase):
    def test_missing_server_fails_enabled_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            builder = ImageBuilder(Path(tmp) / "work")
            with self.assertRaisesRegex(ImageBuilderError, "lacks OpenSSH"):
                builder._configure_ssh_service(Path(tmp), True)

    def test_service_configuration_targets_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "usr/sbin").mkdir(parents=True)
            (root / "usr/sbin/sshd").touch()
            (root / "usr/lib/systemd/system").mkdir(parents=True)
            for unit in ("ssh.service", "ssh.socket"):
                (root / "usr/lib/systemd/system" / unit).touch()
            builder = ImageBuilder(root / "work")
            with patch("image_builder.subprocess.run") as run:
                run.return_value.returncode = 0
                builder._configure_ssh_service(root, True)
                self.assertEqual([call.args[0] for call in run.call_args_list], [
                    ["systemctl", "--root", str(root), action, unit]
                    for action, unit in [("unmask", "ssh.service"), ("enable", "ssh.service"),
                                         ("disable", "ssh.socket"), ("mask", "ssh.socket")]])
                run.reset_mock()
                builder._configure_ssh_service(root, False)
                self.assertEqual([call.args[0][-2:] for call in run.call_args_list],
                                 [[a, u] for u in ("ssh.service", "ssh.socket") for a in ("disable", "mask")])
            builder._render_ssh(root, True)
            policy = (root / "etc/ssh/sshd_config.d/aphys.conf").read_text()
            self.assertIn("PasswordAuthentication yes", policy)
            self.assertIn("PermitRootLogin no", policy)
            self.assertIn("PermitEmptyPasswords no", policy)

    @unittest.skipUnless(shutil.which("systemctl"), "systemctl required")
    def test_real_systemctl_skips_foreign_image_sysv_helper(self):
        with tempfile.TemporaryDirectory(prefix="ssh image ") as tmp:
            root = Path(tmp)
            (root / "usr/sbin").mkdir(parents=True)
            (root / "usr/sbin/sshd").touch()
            units = root / "usr/lib/systemd/system"
            units.mkdir(parents=True)
            (units / "ssh.service").write_text(
                "[Service]\nExecStart=/usr/sbin/sshd -D\n"
                "[Install]\nWantedBy=multi-user.target\n")
            (root / "etc/init.d").mkdir(parents=True)
            (root / "etc/init.d/ssh").write_text("#!/bin/sh\nexit 1\n")
            # No executable shell or update-rc.d exists inside this image.
            builder = ImageBuilder(root / "work")
            link = root / "etc/systemd/system/multi-user.target.wants/ssh.service"
            builder._configure_ssh_service(root, True)
            self.assertTrue(link.is_symlink())
            self.assertEqual(os.readlink(link), "/usr/lib/systemd/system/ssh.service")
            builder._configure_ssh_service(root, False)
            self.assertFalse(link.is_symlink())
            self.assertEqual(os.readlink(root / "etc/systemd/system/ssh.service"), "/dev/null")
            builder._configure_ssh_service(root, True)
            self.assertTrue(link.is_symlink())
