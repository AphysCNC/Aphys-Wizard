"""Pinned base-image acquisition and preparation."""

from __future__ import annotations

import hashlib
import lzma
import os
import platform
import re
import shutil
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

import yaml


class BaseImageError(RuntimeError):
    pass


class ProgressReporter:
    def __init__(self, enabled: bool = True):
        self.enabled = enabled

    def update(self, label: str, current: int, total: int | None = None) -> None:
        if not self.enabled:
            return

        if total:
            percent = min(100.0, current * 100 / total)
            message = f"\r{label}: {percent:6.2f}%"
        else:
            megabytes = current / (1024 * 1024)
            message = f"\r{label}: {megabytes:8.1f} MiB"

        print(message, end="", flush=True)

    def finish(self, label: str) -> None:
        if self.enabled:
            print(f"\r{label}: complete" + " " * 12)


@dataclass(frozen=True)
class BaseImageManifest:
    manifest_version: int
    image_id: str
    source_url: str
    filename: str
    sha256: str | None
    compression: str
    architecture: str
    platforms: tuple[str, ...]
    linuxcnc_version: str
    upstream_md5: str | None = None

    @classmethod
    def load(cls, path: Path) -> "BaseImageManifest":
        try:
            raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            raise BaseImageError(f"Cannot read base-image manifest: {exc}") from exc
        if not isinstance(raw, dict):
            raise BaseImageError("Base-image manifest must be a YAML mapping.")
        required = {
            "manifest_version", "image_id", "source_url", "filename", "sha256",
            "compression", "architecture", "platforms", "linuxcnc_version",
        }
        missing = sorted(required - raw.keys())
        if missing:
            raise BaseImageError(f"Base-image manifest is missing: {', '.join(missing)}")
        if raw["manifest_version"] != 1:
            raise BaseImageError("Only base-image manifest_version 1 is supported.")
        parsed = urllib.parse.urlparse(str(raw["source_url"]))
        if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
            raise BaseImageError("Base image source_url must be HTTPS.")
        checksum = str(raw["sha256"]).lower() if raw.get("sha256") else None
        if checksum and not re.fullmatch(r"[0-9a-f]{64}", checksum):
            raise BaseImageError("Base image sha256 must contain exactly 64 hexadecimal characters.")
        upstream_md5 = str(raw["upstream_md5"]).lower() if raw.get("upstream_md5") else None
        if upstream_md5 and not re.fullmatch(r"[0-9a-f]{32}", upstream_md5):
            raise BaseImageError("Base image upstream_md5 must contain exactly 32 hexadecimal characters.")
        if not checksum and not upstream_md5:
            raise BaseImageError("Base image requires an upstream checksum.")
        filename = str(raw["filename"])
        if Path(filename).name != filename:
            raise BaseImageError("Base image filename must not contain a path.")
        platforms = raw["platforms"]
        if not isinstance(platforms, list) or not platforms or not all(isinstance(x, str) for x in platforms):
            raise BaseImageError("Base image platforms must be a non-empty list of names.")
        if raw["compression"] not in {"xz", "zip"}:
            raise BaseImageError("Base image compression must be 'xz' or 'zip'.")
        if raw["architecture"] != "arm64":
            raise BaseImageError("Only arm64 base images are currently supported.")
        return cls(
            manifest_version=int(raw["manifest_version"]), image_id=str(raw["image_id"]),
            source_url=str(raw["source_url"]), filename=filename, sha256=checksum,
            compression=str(raw["compression"]), architecture="arm64", platforms=tuple(platforms),
            linuxcnc_version=str(raw["linuxcnc_version"]),
            upstream_md5=upstream_md5,
        )


class BaseImageStore:
    def __init__(self, download_dir: Path, build_dir: Path, progress: bool = True):
        self.download_dir = Path(download_dir)
        self.build_dir = Path(build_dir)
        self.progress = ProgressReporter(progress)
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self.build_dir.mkdir(parents=True, exist_ok=True)

    def _copy_stream(self, source, destination, label: str, total: int | None = None) -> None:
        copied = 0
        while True:
            chunk = source.read(4 * 1024 * 1024)
            if not chunk:
                break
            destination.write(chunk)
            copied += len(chunk)
            self.progress.update(label, copied, total)
        self.progress.finish(label)

    @staticmethod
    def _digest(path: Path, algorithm: str) -> str:
        digest = hashlib.new(algorithm)
        with Path(path).open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @classmethod
    def sha256(cls, path: Path) -> str:
        return cls._digest(path, "sha256")

    @classmethod
    def md5(cls, path: Path) -> str:
        # MD5 is checked only as upstream provenance; SHA-256 remains mandatory.
        return cls._digest(path, "md5")

    def _verify(self, path: Path, manifest: BaseImageManifest) -> bool:
        if manifest.sha256 and self.sha256(path) != manifest.sha256:
            return False
        return not manifest.upstream_md5 or self.md5(path) == manifest.upstream_md5

    def acquire(self, manifest: BaseImageManifest) -> Path:
        destination = self.download_dir / manifest.filename
        if destination.exists():
            if self._verify(destination, manifest):
                return destination
            raise BaseImageError(f"Cached base image has the wrong checksum: {destination}")
        partial = destination.with_name(destination.name + ".part")
        try:
            with urllib.request.urlopen(manifest.source_url, timeout=60) as response, partial.open("wb") as output:
                total = response.headers.get("Content-Length")
                self._copy_stream(
                    response,
                    output,
                    "Downloading",
                    int(total) if total else None,
                )
            print("Verifying downloaded image...")
            if not self._verify(partial, manifest):
                raise BaseImageError("Downloaded base image failed checksum verification.")
            os.replace(partial, destination)
            destination.with_name(destination.name + ".sha256").write_text(
                f"{self.sha256(destination)}  {destination.name}\n", encoding="ascii"
            )
        except Exception as exc:
            partial.unlink(missing_ok=True)
            if isinstance(exc, BaseImageError):
                raise
            raise BaseImageError(f"Base-image download failed: {exc}") from exc
        return destination

    def extract(self, source: Path, image_id: str, compression: str = "xz") -> Path:
        pristine_dir = self.build_dir / "base-images"
        pristine_dir.mkdir(parents=True, exist_ok=True)
        destination = pristine_dir / f"{image_id}.img"
        if destination.exists():
            return destination
        partial = destination.with_name(destination.name + ".part")
        try:
            if compression == "xz":
                with lzma.open(source, "rb") as compressed, partial.open("wb") as output:
                    self._copy_stream(compressed, output, "Extracting")
            elif compression == "zip":
                self._extract_zip_image(source, partial)
            else:
                raise BaseImageError(f"Unsupported compression: {compression}")
            os.replace(partial, destination)
        except (OSError, lzma.LZMAError, zipfile.BadZipFile) as exc:
            partial.unlink(missing_ok=True)
            raise BaseImageError(f"Cannot extract base image: {exc}") from exc
        return destination

    @staticmethod
    def _extract_zip_image(source: Path, destination: Path) -> None:
        with zipfile.ZipFile(source) as archive:
            images = [item for item in archive.infolist() if not item.is_dir() and item.filename.lower().endswith(".img")]
            if len(images) != 1:
                raise BaseImageError("ZIP base image must contain exactly one .img file.")
            member = images[0]
            if Path(member.filename).name != member.filename:
                raise BaseImageError("ZIP image member must not be nested in a directory.")
            with archive.open(member) as compressed, destination.open("wb") as output:
                shutil.copyfileobj(compressed, output, length=4 * 1024 * 1024)

    def create_working_copy(self, pristine: Path, job_dir: Path, name: str) -> Path:
        """Create the mutable image copy; the extracted cache remains untouched."""
        job_dir = Path(job_dir)
        job_dir.mkdir(parents=True, exist_ok=True)
        destination = job_dir / f"{name}.img"
        if destination.exists():
            raise BaseImageError(f"Working image already exists: {destination}")
        with pristine.open("rb") as source, destination.open("wb") as output:
            self._copy_stream(source, output, "Copying image", pristine.stat().st_size)
        shutil.copystat(pristine, destination)
        return destination

    def compress(self, image: Path, output: Path) -> Path:
        """Compress an image atomically and write an adjacent SHA-256 file."""
        output = Path(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        partial = output.with_name(output.name + ".part")
        try:
            with Path(image).open("rb") as source, lzma.open(partial, "wb", preset=6) as compressed:
                self._copy_stream(source, compressed, "Compressing", Path(image).stat().st_size)
            os.replace(partial, output)
            print("Verifying compressed image...")
            checksum = self.sha256(output)
            output.with_name(output.name + ".sha256").write_text(
                f"{checksum}  {output.name}\n", encoding="ascii"
            )
        except (OSError, lzma.LZMAError) as exc:
            partial.unlink(missing_ok=True)
            raise BaseImageError(f"Cannot compress final image: {exc}") from exc
        return output


def linux_prerequisites() -> dict[str, object]:
    commands = ("losetup", "lsblk", "mount", "umount", "chroot", "xz")
    missing = [command for command in commands if shutil.which(command) is None]
    is_linux = platform.system() == "Linux"
    is_root = hasattr(os, "geteuid") and os.geteuid() == 0
    return {
        "system": platform.system(),
        "is_linux": is_linux,
        "is_root": is_root,
        "missing_commands": missing,
        "ready": is_linux and is_root and not missing,
    }
