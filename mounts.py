"""Safe Linux loop-device and mount lifecycle for disk-image builds."""

from __future__ import annotations

import json
import os
import platform
import subprocess
import time
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence


class MountError(RuntimeError):
    pass


Runner = Callable[..., subprocess.CompletedProcess]


@dataclass(frozen=True)
class ImagePartitions:
    boot: Path
    root: Path


def select_partitions(lsblk_json: str) -> ImagePartitions:
    """Select the FAT boot and largest Linux root partition from lsblk JSON."""
    try:
        devices = json.loads(lsblk_json)["blockdevices"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise MountError("Could not parse lsblk partition information.") from exc

    partitions: list[dict] = []
    def collect(devices: list[dict]) -> None:
        for device in devices:
            if device.get("type") in (None, "part"):
                partitions.append(device)
            collect(device.get("children") or [])

    collect(devices)
    boot_candidates = [p for p in partitions if str(p.get("fstype", "")).lower() in {"vfat", "fat", "fat32"}]
    root_candidates = [p for p in partitions if str(p.get("fstype", "")).lower() in {"ext4", "ext3", "btrfs"}]
    if not boot_candidates or not root_candidates:
        detected = ", ".join(
            f"{p.get('path', '?')} ({p.get('fstype') or 'unknown filesystem'})"
            for p in partitions
        ) or "none"
        raise MountError(
            "Image must contain a FAT boot partition and a Linux root partition. "
            f"Detected partitions: {detected}."
        )
    boot = next((p for p in boot_candidates if str(p.get("partlabel", "")).lower() in {"boot", "bootfs"}), boot_candidates[0])
    root = max(root_candidates, key=lambda p: int(p.get("size") or 0))
    if not boot.get("path") or not root.get("path"):
        raise MountError("lsblk did not return usable partition device paths.")
    return ImagePartitions(Path(boot["path"]), Path(root["path"]))


def require_linux_mount_host() -> None:
    if platform.system() != "Linux":
        raise MountError("Disk images can only be mounted by this builder on Linux.")
    if os.geteuid() != 0:
        raise MountError("Mounting a disk image requires root privileges or an isolated privileged worker.")


class MountedImage(AbstractContextManager):
    """Attach and mount an image; always unmount and detach on exit."""

    def __init__(self, image: Path, mount_dir: Path, runner: Runner = subprocess.run):
        self.image = Path(image).resolve()
        self.mount_dir = Path(mount_dir).resolve()
        self.runner = runner
        self.loop_device: Path | None = None
        self.root_mount = self.mount_dir / "root"
        self.boot_mount: Path | None = None
        self._mounted: list[Path] = []

    def _run(self, command: Sequence[str], *, capture: bool = False) -> subprocess.CompletedProcess:
        try:
            return self.runner(list(command), check=True, text=True, capture_output=capture)
        except (OSError, subprocess.CalledProcessError) as exc:
            detail = getattr(exc, "stderr", None) or str(exc)
            raise MountError(f"Command failed ({' '.join(command)}): {detail}") from exc

    def __enter__(self) -> "MountedImage":
        require_linux_mount_host()
        if not self.image.is_file():
            raise MountError(f"Image does not exist: {self.image}")
        self.mount_dir.mkdir(parents=True, exist_ok=True)
        try:
            result = self._run(
                ["losetup", "--find", "--show", "--partscan", str(self.image)],
                capture=True,
            )
            output = result.stdout.strip()
            if not output.startswith("/dev/loop"):
                raise MountError(f"losetup returned an unexpected device: {output!r}")
            self.loop_device = Path(output)
            partitions = self._discover_partitions()
            self.root_mount.mkdir(parents=True, exist_ok=True)
            self._run(["mount", str(partitions.root), str(self.root_mount)])
            self._mounted.append(self.root_mount)

            firmware = self.root_mount / "boot" / "firmware"
            self.boot_mount = firmware if firmware.is_dir() else self.root_mount / "boot"
            self.boot_mount.mkdir(parents=True, exist_ok=True)
            self._run(["mount", str(partitions.boot), str(self.boot_mount)])
            self._mounted.append(self.boot_mount)
            return self
        except Exception:
            self._cleanup(suppress=True)
            raise

    def _discover_partitions(self) -> ImagePartitions:
        assert self.loop_device is not None
        last_error: MountError | None = None
        for _ in range(20):
            result = self._run(
                ["lsblk", "--json", "--tree", "--bytes", "--output", "PATH,TYPE,FSTYPE,PARTLABEL,SIZE", str(self.loop_device)],
                capture=True,
            )
            try:
                return select_partitions(result.stdout)
            except MountError as exc:
                last_error = exc
                time.sleep(0.1)
        raise last_error or MountError("No image partitions appeared.")

    def _cleanup(self, *, suppress: bool) -> None:
        errors: list[str] = []
        for target in reversed(self._mounted):
            try:
                self._run(["umount", str(target)])
            except MountError as exc:
                errors.append(str(exc))
        self._mounted.clear()
        if self.loop_device is not None:
            try:
                self._run(["losetup", "--detach", str(self.loop_device)])
            except MountError as exc:
                errors.append(str(exc))
            self.loop_device = None
        if errors and not suppress:
            raise MountError("Cleanup failed: " + "; ".join(errors))

    def __exit__(self, exc_type, exc, traceback) -> bool:
        self._cleanup(suppress=exc is not None)
        return False


class ChrootMounts(AbstractContextManager):
    """Bind the virtual filesystems required by package tools inside a chroot."""

    # /dev/pts is included recursively by the /dev rbind.
    SOURCES = ("/proc", "/sys", "/dev", "/run")

    def __init__(self, root: Path, runner: Runner = subprocess.run):
        self.root = Path(root).resolve()
        self.runner = runner
        self._mounted: list[Path] = []

    def __enter__(self) -> "ChrootMounts":
        require_linux_mount_host()
        try:
            for source in self.SOURCES:
                target = self.root / source.lstrip("/")
                target.mkdir(parents=True, exist_ok=True)
                command = ["mount", "--rbind" if source in {"/dev", "/sys"} else "--bind", source, str(target)]
                self.runner(command, check=True, text=True, capture_output=True)
                self.runner(["mount", "--make-rslave", str(target)], check=True, text=True, capture_output=True)
                self._mounted.append(target)
            return self
        except Exception as exc:
            self._cleanup()
            raise MountError(f"Could not prepare chroot mounts: {exc}") from exc

    def _cleanup(self) -> None:
        for target in reversed(self._mounted):
            self.runner(["umount", "--recursive", str(target)], check=False, text=True, capture_output=True)
        self._mounted.clear()

    def __exit__(self, exc_type, exc, traceback) -> bool:
        self._cleanup()
        return False
