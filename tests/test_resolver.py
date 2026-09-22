import unittest
from unittest.mock import Mock, patch

from resolver import Resolver, STABLE_BASE_IMAGE_MANIFEST, STABLE_LINUXCNC_VERSION


class ResolverTests(unittest.TestCase):
    def test_stable_stack_is_pinned_and_offline(self):
        result = Resolver().stable_linuxcnc()
        self.assertEqual(result.version, STABLE_LINUXCNC_VERSION)
        self.assertEqual(result.base_image_manifest, STABLE_BASE_IMAGE_MANIFEST)
        self.assertEqual(result.build_profile, "aphys-stable")

    @patch("resolver.requests.get")
    def test_discovers_official_pi_image_link(self, get):
        response = Mock()
        response.text = '''<html><a href="https://www.linuxcnc.org/iso/image_2026-01-21-raspios-lcnc-2.9.8-trixie-arm64.zip">Raspberry Pi 4/5 SD Card Image</a> (MD5SUM 705b7f3c2f7b385f6cb094d05e01070e)</html>'''
        response.raise_for_status.return_value = None
        get.return_value = response
        version, url, checksum = Resolver().discover_raspberry_pi_image()
        self.assertEqual(version, "2.9.8")
        self.assertTrue(url.endswith("2.9.8-trixie-arm64.zip"))
        self.assertEqual(checksum, "705b7f3c2f7b385f6cb094d05e01070e")

    @patch("resolver.requests.get")
    def test_accepts_changed_official_image_without_local_manifest(self, get):
        response = Mock()
        response.text = '''<a href="https://www.linuxcnc.org/iso/image_2027-01-01-raspios-lcnc-2.9.11-trixie-arm64.zip">Raspberry Pi 4/5 SD Card Image</a> (MD5SUM 11111111111111111111111111111111)'''
        response.raise_for_status.return_value = None
        get.return_value = response
        result = Resolver().resolve_current_linuxcnc()
        self.assertEqual(result.version, "2.9.11")
        self.assertIsNone(result.base_image_manifest)
        self.assertEqual(result.discovery_status, "official-source")


if __name__ == "__main__":
    unittest.main()
