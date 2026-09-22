import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml
from image_builder import ImageBuilder, main
from product import core_placeholder
from schema import ManifestError, validate_manifest


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.manifest = {
            "metadata": {"name": "core-test", "schema_version": "1.0", "created_at": "2026-09-21T00:00:00+00:00"},
            "hardware": {"platform": "Raspberry Pi 5", "architecture": "arm64",
                         "os": {"architecture": "arm64", "realtime": True}, "linuxcnc": {"version": "2.9.8"}},
            "system": {"user": {"name": "aphys"}, "network": {"mode": "dhcp"}, "ssh": {"enabled": True}},
            "gui": {"enabled": False, "provider": None},
        }

    def test_old_manifests_default_disabled_and_are_not_mutated(self):
        for provider in ("lcnc-suite", "qtplasmac"):
            self.manifest["gui"] = {"enabled": True, "provider": provider}
            self.assertEqual(validate_manifest(self.manifest)["core"], core_placeholder())
        self.assertNotIn("core", self.manifest)

    def test_invalid_core_fields(self):
        for core in (None, {"enabled": "false"}, {"enabled": True}, {"version": 1},
                     {"source": None}, {"source": {"type": "github"}},
                     {"source": {"type": []}}, {"source": {"location": 1}},
                     {"source": {"sha256": "bad"}}, {"control_lock": {"enabled": "yes"}}):
            with self.subTest(core=core), self.assertRaises(ManifestError):
                validate_manifest(dict(self.manifest, core=core))

    def test_local_and_url_declarations_preserved_without_fetch(self):
        for kind, location in (("local", "/tmp/core.deb"), ("url", "https://example.invalid/core.deb")):
            core = {"enabled": False, "version": "0.1.0", "source": {
                "type": kind, "location": location, "sha256": "a" * 64},
                "control_log": {"enabled": True}}
            self.assertEqual(validate_manifest(dict(self.manifest, core=core))["core"], core)

    def test_enabled_cli_fails_before_builder_creation(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / "build.yaml"
            manifest.write_text(yaml.safe_dump(dict(self.manifest, core={"enabled": True})))
            with patch("image_builder.ImageBuilder") as builder, contextlib.redirect_stderr(io.StringIO()) as error:
                with self.assertRaises(SystemExit):
                    main([str(manifest), "--build-image"])
                builder.assert_not_called()
                self.assertIn("Core installation is not implemented yet", error.getvalue())

    def test_enabled_api_does_not_create_root_or_acquire_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            builder = ImageBuilder(Path(tmp) / "work")
            root = Path(tmp) / "target"
            manifest = dict(self.manifest, core={"enabled": True})
            with self.assertRaises(ManifestError):
                builder.build_manifest(manifest, root)
            self.assertFalse(root.exists())
            with patch.object(builder, "prepare_base_image") as acquire:
                with self.assertRaises(ManifestError):
                    builder.build_disk_image(manifest, None)
                acquire.assert_not_called()

    def test_render_records_not_installed_and_warns_for_legacy_gui(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            builder = ImageBuilder(root / "work")
            for provider in ("lcnc-suite", "qtplasmac"):
                self.manifest["gui"] = {"enabled": True, "provider": provider}
                with patch.object(builder, "_render_user"), contextlib.redirect_stdout(io.StringIO()) as output:
                    builder.render_manifest(self.manifest, root)
                self.assertIn("not applied", output.getvalue())
                saved = yaml.safe_load((root / "etc/aphys/build.yaml").read_text())
                state = yaml.safe_load((root / "etc/aphys/product.yaml").read_text())
                self.assertEqual(saved["core"], core_placeholder())
                self.assertIs(state["core"]["installed"], False)
                self.assertEqual(state["gui"], {"enabled": False, "provider": None})
