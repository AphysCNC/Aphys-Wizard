import hashlib
import lzma
import tempfile
import unittest
import zipfile
from pathlib import Path

import yaml

from base_image import BaseImageError, BaseImageManifest, BaseImageStore
from image_builder import ImageBuilder, ImageBuilderError


class BaseImageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def test_load_rejects_unpinned_manifest(self):
        path = self.root / "base.yaml"
        path.write_text(yaml.safe_dump({
            "manifest_version": 1, "image_id": "test", "source_url": "http://example/image.xz",
            "filename": "image.xz", "sha256": "not-a-checksum", "compression": "xz",
            "architecture": "arm64", "platforms": ["Raspberry Pi 5"], "linuxcnc_version": "2.9.4",
        }), encoding="utf-8")
        with self.assertRaises(BaseImageError):
            BaseImageManifest.load(path)

    def test_extract_xz_image(self):
        source = self.root / "fixture.img.xz"
        payload = b"disk-image-fixture" * 100
        source.write_bytes(lzma.compress(payload))
        store = BaseImageStore(self.root / "downloads", self.root / "build")
        output = store.extract(source, "fixture")
        self.assertEqual(output.read_bytes(), payload)

    def test_compress_writes_verifiable_checksum(self):
        image = self.root / "configured.img"
        image.write_bytes(b"configured-disk-image" * 100)
        output = self.root / "output" / "configured.img.xz"
        store = BaseImageStore(self.root / "downloads", self.root / "build")
        store.compress(image, output)
        self.assertEqual(lzma.decompress(output.read_bytes()), image.read_bytes())
        checksum_line = output.with_name(output.name + ".sha256").read_text(encoding="ascii")
        self.assertEqual(checksum_line, f"{store.sha256(output)}  {output.name}\n")

    def test_extract_zip_image(self):
        source = self.root / "fixture.zip"
        payload = b"zip-disk-image" * 100
        with zipfile.ZipFile(source, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("fixture.img", payload)
        store = BaseImageStore(self.root / "downloads", self.root / "build")
        output = store.extract(source, "zip-fixture", "zip")
        self.assertEqual(output.read_bytes(), payload)

    def test_acquire_reuses_verified_cache(self):
        downloads = self.root / "downloads"
        downloads.mkdir()
        payload = b"cached-image"
        (downloads / "image.img.xz").write_bytes(payload)
        manifest = BaseImageManifest(1, "fixture", "https://example.invalid/image.img.xz",
            "image.img.xz", hashlib.sha256(payload).hexdigest(), "xz", "arm64",
            ("Raspberry Pi 5",), "2.9.4")
        store = BaseImageStore(downloads, self.root / "build")
        self.assertEqual(store.acquire(manifest).read_bytes(), payload)

    def test_plan_rejects_linuxcnc_mismatch(self):
        manifest = {
            "metadata": {"name": "demo", "schema_version": "1.0", "created_at": "2026-09-04T12:00:00+00:00"},
            "hardware": {"platform": "Raspberry Pi 5", "architecture": "arm64",
                "os": {"architecture": "arm64", "realtime": True}, "linuxcnc": {"version": "2.9.4"}},
            "system": {"user": {"name": "aphys"}, "network": {"mode": "dhcp"}, "ssh": {"enabled": True}},
            "gui": {"enabled": True, "provider": "lcnc-suite"},
        }
        base = BaseImageManifest(1, "fixture", "https://example.invalid/image.img.xz",
            "image.img.xz", "0" * 64, "xz", "arm64", ("Raspberry Pi 5",), "2.9.3")
        with self.assertRaises(ImageBuilderError):
            ImageBuilder(self.root / "work").image_plan(manifest, base)

    def test_plan_uses_base_image_cache_path(self):
        manifest = {
            "metadata": {"name": "demo", "schema_version": "1.0", "created_at": "2026-09-04T12:00:00+00:00"},
            "hardware": {"platform": "Raspberry Pi 5", "architecture": "arm64",
                "os": {"architecture": "arm64", "realtime": True}, "linuxcnc": {"version": "2.9.3"}},
            "system": {"user": {"name": "aphys"}, "network": {"mode": "dhcp"}, "ssh": {"enabled": True}},
            "gui": {"enabled": True, "provider": "lcnc-suite"},
        }
        base = BaseImageManifest(1, "fixture", "https://example.invalid/image.img.xz",
            "image.img.xz", "0" * 64, "xz", "arm64", ("Raspberry Pi 5",), "2.9.3")
        steps = ImageBuilder(self.root / "work").image_plan(manifest, base)
        self.assertIn(str((self.root / "work" / "build" / "base-images" / "fixture.img").resolve()), "\n".join(steps))

    def test_prepare_job_dir_cleans_stale_work(self):
        builder = ImageBuilder(self.root / "work")
        stale_dir = self.root / "work" / "build" / "jobs" / "demo"
        stale_dir.mkdir(parents=True)
        (stale_dir / "demo.img").write_bytes(b"stale")
        job_dir = builder.prepare_job_dir("demo")
        self.assertEqual(job_dir, stale_dir)
        self.assertFalse((stale_dir / "demo.img").exists())


if __name__ == "__main__":
    unittest.main()
