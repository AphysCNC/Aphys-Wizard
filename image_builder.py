"""
Aphys Wizard — Image Builder

Builds an Aphys LinuxCNC image from a downloaded base image.

The builder is intentionally split into small operations so that
individual steps can be tested independently.

Current stage:
- download base image
- prepare build directory
- extract/prepare filesystem
- provide chroot execution infrastructure
- install packages
- configure system
- configure LinuxCNC
- configure WebGUI
- configure VPN
- pack final image

Some installation steps are intentionally placeholders until the
exact LinuxCNC Raspberry Pi image/package workflow is verified.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import urllib.request
import argparse
import re
from copy import deepcopy
from pathlib import Path

import yaml

try:
    from .accounts import AccountError, provision_user
    from .schema import ManifestError, validate_manifest
    from .base_image import BaseImageError, BaseImageManifest, BaseImageStore, linux_prerequisites
    from .mounts import ChrootMounts, MountError, MountedImage
except ImportError:  # Support ``python image_builder.py``.
    from accounts import AccountError, provision_user
    from schema import ManifestError, validate_manifest
    from base_image import BaseImageError, BaseImageManifest, BaseImageStore, linux_prerequisites
    from mounts import ChrootMounts, MountError, MountedImage


class ImageBuilderError(Exception):
    pass


class ImageBuilder:

    def __init__(
        self,
        work_dir: Path,
        clean_jobs: bool = False,
    ):

        self.work_dir = Path(work_dir)
        self.clean_jobs = clean_jobs

        self.download_dir = (
            self.work_dir / "downloads"
        )

        self.build_dir = (
            self.work_dir / "build"
        )

        self.output_dir = (
            self.work_dir / "output"
        )

        self.download_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.build_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.output_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

    # ---------------------------------------------------------
    # Download
    # ---------------------------------------------------------

    def download(
        self,
        url: str,
        filename: str | None = None,
    ) -> Path:

        if filename is None:
            filename = url.rstrip("/").split("/")[-1]

        destination = (
            self.download_dir / filename
        )

        print()
        print(f"Downloading: {url}")
        print(f"       -> {destination}")

        try:

            urllib.request.urlretrieve(
                url,
                destination,
            )

        except Exception as exc:

            raise ImageBuilderError(
                f"Failed to download {url}: {exc}"
            ) from exc

        return destination

    # ---------------------------------------------------------
    # Verify checksum
    # ---------------------------------------------------------

    def sha256(
        self,
        path: Path,
    ) -> str:

        digest = hashlib.sha256()

        with open(path, "rb") as file:

            for chunk in iter(
                lambda: file.read(1024 * 1024),
                b"",
            ):
                digest.update(chunk)

        return digest.hexdigest()

    def verify_sha256(
        self,
        path: Path,
        expected: str,
    ) -> bool:

        actual = self.sha256(path)

        if actual.lower() != expected.lower():

            raise ImageBuilderError(
                "SHA256 checksum mismatch:\n"
                f"Expected: {expected}\n"
                f"Actual:   {actual}"
            )

        return True

    # ---------------------------------------------------------
    # Build directory
    # ---------------------------------------------------------

    def prepare_build_directory(
        self,
        clean: bool = False,
    ) -> Path:

        if clean and self.build_dir.exists():

            shutil.rmtree(
                self.build_dir
            )

            self.build_dir.mkdir(
                parents=True
            )

        return self.build_dir

    # ---------------------------------------------------------
    # External commands
    # ---------------------------------------------------------

    def run(
        self,
        command: list[str],
        *,
        check: bool = True,
        cwd: Path | None = None,
    ):

        print()
        print("$", " ".join(command))

        return subprocess.run(
            command,
            cwd=cwd,
            check=check,
            text=True,
        )

    # ---------------------------------------------------------
    # Chroot
    # ---------------------------------------------------------

    def chroot(
        self,
        root: Path,
        command: list[str],
    ):

        root = Path(root)

        if not root.exists():

            raise ImageBuilderError(
                f"Chroot root does not exist: {root}"
            )

        #
        # Mount handling will be added here.
        #
        # Required virtual filesystems:
        #
        #   /dev
        #   /proc
        #   /sys
        #   /run
        #
        # We deliberately do not silently mount them yet.
        #

        return self.run(
            [
                "chroot",
                str(root),
                *command,
            ]
        )

    # ---------------------------------------------------------
    # Package installation
    # ---------------------------------------------------------

    def install_packages(
        self,
        root: Path,
        packages: list[str],
    ):

        if not packages:
            return

        command = [
            "apt-get",
            "update",
        ]

        self.chroot(
            root,
            command,
        )

        self.chroot(
            root,
            [
                "apt-get",
                "install",
                "-y",
                *packages,
            ],
        )

    # ---------------------------------------------------------
    # System configuration
    # ---------------------------------------------------------

    def configure_system(
        self,
        root: Path,
        username: str,
    ):

        print()
        print("Configuring system...")

        #
        # Actual user creation, sudo, SSH, network and VPN
        # configuration will be implemented here through the
        # dedicated configuration logic.
        #

        print(
            f"Target user: {username}"
        )

    # ---------------------------------------------------------
    # LinuxCNC
    # ---------------------------------------------------------

    def configure_linuxcnc(
        self,
        root: Path,
        version: str,
    ):

        print()
        print(
            f"Configuring LinuxCNC {version}..."
        )

        #
        # Do not hard-code package names or repositories here
        # until the exact Raspberry Pi LinuxCNC distribution
        # workflow is verified.
        #

    # ---------------------------------------------------------
    # WebGUI
    # ---------------------------------------------------------

    def configure_webgui(
        self,
        root: Path,
        provider: str,
    ):

        print()
        print(
            f"Configuring WebGUI: {provider}"
        )

        if provider == "lcnc-suite":

            print(
                "LCNC Suite selected."
            )

        elif provider == "qtplasmac":

            print(
                "QtPlasmaC fallback selected."
            )

        else:

            raise ImageBuilderError(
                f"Unknown WebGUI provider: {provider}"
            )

    # ---------------------------------------------------------
    # VPN
    # ---------------------------------------------------------

    def configure_vpn(
        self,
        root: Path,
        provider: str,
    ):

        print()
        print(
            f"Configuring VPN: {provider}"
        )

        #
        # VPN installation and enrollment are deliberately
        # separated. The builder can install the client into
        # the image, but device enrollment should not require
        # putting a permanent secret into the image.
        #

    # ---------------------------------------------------------
    # Final configuration
    # ---------------------------------------------------------

    def write_config(
        self,
        root: Path,
        config_text: str,
        filename: str = "aphys-build.conf",
    ):

        target = (
            Path(root)
            / "etc"
            / "aphys"
            / filename
        )

        target.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        target.write_text(
            config_text,
            encoding="utf-8",
        )

        return target

    # ---------------------------------------------------------
    # Packing
    # ---------------------------------------------------------

    def create_archive(
        self,
        source: Path,
        name: str,
    ) -> Path:

        source = Path(source)

        archive_base = (
            self.output_dir / name
        )

        print()
        print(
            f"Creating archive: {archive_base}.tar"
        )

        shutil.make_archive(
            str(archive_base),
            "tar",
            root_dir=source,
        )

        return archive_base.with_suffix(
            ".tar"
        )

    def build_manifest(self, manifest: dict, root: Path | None = None) -> Path:
        """Render a validated manifest into a fixture/root filesystem archive.

        This provides a useful, non-root build stage today. Image mounting and
        package installation can later feed the same rendered tree into a real
        Raspberry Pi base image.
        """
        manifest = validate_manifest(manifest)
        root = Path(root) if root else self.build_dir / "rootfs"
        root.mkdir(parents=True, exist_ok=True)
        config = self.render_manifest(manifest, root)
        return self.create_archive(root, config["metadata"]["name"])

    def render_manifest(self, manifest: dict, root: Path) -> dict:
        """Apply configuration files to a root filesystem without packaging it."""
        config = validate_manifest(manifest)
        root = Path(root)
        if not root.is_dir():
            raise ImageBuilderError(f"Target root filesystem does not exist: {root}")
        if config["gui"].get("enabled"):
            print("Notice: legacy GUI installation settings are not applied; using the base image interface.")
        public_config = deepcopy(config)
        public_config["system"]["user"].pop("password_hash", None)
        manifest_text = yaml.safe_dump(public_config, sort_keys=False, allow_unicode=True)
        self.write_config(root, manifest_text, "build.yaml")
        self._render_network(root, config["system"]["network"])
        self._render_ssh(root, bool(config["system"]["ssh"]["enabled"]))
        self._render_user(root, config["system"]["user"])
        self._render_product(root, config)
        return config

    def build_file(self, manifest_path: Path, root: Path | None = None) -> Path:
        try:
            manifest = yaml.safe_load(Path(manifest_path).read_text(encoding="utf-8"))
            return self.build_manifest(manifest, root)
        except (OSError, yaml.YAMLError, ManifestError) as exc:
            raise ImageBuilderError(f"Cannot build manifest: {exc}") from exc

    def image_plan(self, build_manifest: dict, base: BaseImageManifest) -> list[str]:
        config = validate_manifest(build_manifest)
        hardware = config["hardware"]
        if hardware["platform"] not in base.platforms:
            raise ImageBuilderError(f"Base image does not support {hardware['platform']}.")
        if hardware["architecture"] != base.architecture:
            raise ImageBuilderError("Build and base-image architectures do not match.")
        requested = str(hardware["linuxcnc"]["version"])
        if requested != base.linuxcnc_version:
            raise ImageBuilderError(
                f"Build requests LinuxCNC {requested}, but base image contains {base.linuxcnc_version}."
            )
        cached = self.download_dir / base.filename
        image = self.build_dir / "base-images" / f"{base.image_id}.img"
        return [
            f"download/cache {base.source_url} -> {cached}",
            f"verify {'SHA-256 ' + base.sha256 if base.sha256 else 'upstream MD5 ' + str(base.upstream_md5)}",
            f"extract xz -> {image}",
            "attach image partitions with a Linux loop device",
            "mount boot and root partitions inside the build job",
            "apply Aphys configuration and install pinned software",
            "validate, unmount, detach, checksum and compress .img.xz",
        ]

    def prepare_base_image(self, base: BaseImageManifest) -> Path:
        store = BaseImageStore(self.download_dir, self.build_dir)
        archive = store.acquire(base)
        return store.extract(archive, base.image_id, base.compression)

    def prepare_job_dir(self, name: str) -> Path:
        """Return a job directory, cleaning stale work for the same build name."""
        job_dir = self.build_dir / "jobs" / name
        if not job_dir.exists():
            job_dir.mkdir(parents=True, exist_ok=True)
            return job_dir
        if self.clean_jobs or any(job_dir.iterdir()):
            print(f"Cleaning stale job directory: {job_dir}")
            shutil.rmtree(job_dir)
            job_dir.mkdir(parents=True, exist_ok=True)
        return job_dir

    def build_disk_image(self, manifest: dict, base: BaseImageManifest) -> Path:
        """Create a configured, compressed disk image on a privileged Linux host."""
        config = validate_manifest(manifest)
        self.image_plan(config, base)
        name = config["metadata"]["name"]
        store = BaseImageStore(self.download_dir, self.build_dir)

        print("[1/7] Acquiring and verifying base image")
        pristine = self.prepare_base_image(base)

        print("[2/7] Creating working image copy")
        job_dir = self.prepare_job_dir(name)
        working = store.create_working_copy(pristine, job_dir, name)

        print("[3/7] Mounting image partitions")
        with self.mount_prepared_image(working, name) as mounted:
            if config["system"]["user"].get("sudo", False) and not (mounted.root_mount / "usr/bin/sudo").is_file():
                raise ImageBuilderError("Base image must contain sudo to grant administrator access.")
            print("[4/7] Applying Aphys configuration")
            self.render_manifest(config, mounted.root_mount)
            self._configure_ssh_service(mounted.root_mount, bool(config["system"]["ssh"]["enabled"]))

        print("[5/7] Validating and unmounting image")
        output = self.output_dir / f"{name}.img.xz"
        if output.exists():
            raise ImageBuilderError(f"Output already exists: {output}")

        print("[6/7] Compressing final image")
        result = store.compress(working, output)
        print("[7/7] Image build complete")
        return result

    def mount_prepared_image(self, image: Path, job_name: str) -> MountedImage:
        """Return a context manager for a prepared image's boot/root partitions."""
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", job_name):
            raise ImageBuilderError("job_name must be a single safe path component.")
        return MountedImage(image, self.build_dir / "mounts" / job_name)

    @staticmethod
    def _write(root: Path, relative: str, text: str, mode: int = 0o644) -> Path:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8", newline="\n")
        target.chmod(mode)
        return target

    def _render_network(self, root: Path, network: dict) -> None:
        lines = ["[connection]", "id=aphys-ethernet", "type=ethernet", "interface-name=eth0", "", "[ipv4]"]
        if network["mode"] == "dhcp":
            lines += ["method=auto"]
        else:
            lines += ["method=manual", f"addresses1={network['address']}{network['netmask']},{network['gateway']}"]
        lines += ["", "[ipv6]", "method=auto", ""]
        self._write(root, "etc/NetworkManager/system-connections/aphys-ethernet.nmconnection", "\n".join(lines), 0o600)

    def _render_ssh(self, root: Path, enabled: bool) -> None:
        config = "PasswordAuthentication yes\nPermitEmptyPasswords no\nPermitRootLogin no\nPubkeyAuthentication yes\n"
        self._write(root, "etc/ssh/sshd_config.d/aphys.conf", config)
        # Real disk builds also apply the service state to the mounted image.
        self._write(root, "etc/aphys/services.yaml", yaml.safe_dump({"ssh": enabled}))

    def _configure_ssh_service(self, root: Path, enabled: bool) -> None:
        """Configure the image's existing OpenSSH unit without starting host services."""
        if enabled and not (root / "usr/sbin/sshd").is_file():
            raise ImageBuilderError("SSH is enabled but the base image lacks OpenSSH server (usr/sbin/sshd).")
        units = ("ssh.service", "ssh.socket")
        for unit in units:
            present = any((root / folder / unit).is_file() for folder in
                          ("usr/lib/systemd/system", "lib/systemd/system"))
            if not present:
                if enabled and unit == "ssh.service":
                    raise ImageBuilderError("Base image must contain ssh.service to enable SSH.")
                continue
            actions = ("unmask", "enable") if enabled and unit == "ssh.service" else ("disable", "mask")
            for action in actions:
                result = subprocess.run(
                    ["systemctl", "--root", str(root), action, unit],
                    # SysV synchronization chroots into the ARM image. Native
                    # systemd enablement only needs offline filesystem edits.
                    env={**os.environ, "SYSTEMCTL_SKIP_SYSV": "1"},
                    capture_output=True, text=True,
                )
                if result.returncode:
                    raise ImageBuilderError(f"Cannot {action} {unit} in image: {result.stderr.strip()}")

    def _render_user(self, root: Path, user: dict) -> None:
        try:
            provision_user(root, user)
        except (AccountError, ValueError) as exc:
            raise ImageBuilderError(f"Cannot configure image user: {exc}") from exc
        text = yaml.safe_dump({"name": user["name"], "sudo": bool(user.get("sudo")), "provisioned": True}, sort_keys=False)
        self._write(root, "etc/aphys/user.yaml", text, 0o600)
        (root / "etc/aphys/first-boot-user.yaml").unlink(missing_ok=True)

    def _render_product(self, root: Path, config: dict) -> None:
        gui = config["gui"]
        state = {"linuxcnc": config["hardware"]["linuxcnc"], "gui": {"enabled": bool(gui["enabled"]), "provider": gui.get("provider")}}
        state["gui"] = {"enabled": False, "provider": None}
        state["core"] = {**deepcopy(config["core"]), "installed": False}
        self._write(root, "etc/aphys/product.yaml", yaml.safe_dump(state, sort_keys=False))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build an Aphys root-filesystem artifact")
    parser.add_argument("manifest", type=Path, help="resolved YAML manifest from wizard.py")
    parser.add_argument("--work-dir", type=Path, default=Path("image-work"))
    parser.add_argument("--root", type=Path, help="render into this root filesystem")
    parser.add_argument("--base-image", type=Path, help="pinned base-image manifest")
    parser.add_argument("--dry-run", action="store_true", help="validate and print the image-build plan")
    parser.add_argument("--prepare-image", action="store_true", help="download, verify and extract the base image")
    parser.add_argument("--build-image", action="store_true", help="build a configured, flashable .img.xz (Linux/root)")
    parser.add_argument("--clean", action="store_true", help="remove an abandoned working job before building")
    parser.add_argument("--check-host", action="store_true", help="show Linux image-building prerequisites")
    args = parser.parse_args(argv)
    try:
        manifest = validate_manifest(yaml.safe_load(args.manifest.read_text(encoding="utf-8")))
        builder = ImageBuilder(args.work_dir, clean_jobs=args.clean)
        if args.check_host:
            host = linux_prerequisites()
            print(yaml.safe_dump(host, sort_keys=False).strip())
            if args.build_image and not host["ready"]:
                raise ImageBuilderError(
                    "Host is not ready for --build-image; install the missing "
                    "commands and run as root."
                )
        base_path = args.base_image
        if base_path is None and isinstance(manifest, dict) and isinstance(manifest.get("build"), dict):
            selected = manifest["build"].get("base_image_manifest")
            if selected:
                base_path = Path(__file__).resolve().parent / "manifests" / str(selected)
        if base_path:
            base = BaseImageManifest.load(base_path)
        elif isinstance(manifest, dict) and isinstance(manifest.get("build"), dict) and manifest["build"].get("base_image_url"):
            build = manifest["build"]
            url = str(build["base_image_url"])
            base = BaseImageManifest(
                1, f"linuxcnc-{manifest['hardware']['linuxcnc']['version']}-official",
                url, Path(url).name, None, "zip", "arm64",
                ("Raspberry Pi 4", "Raspberry Pi 5"),
                str(manifest["hardware"]["linuxcnc"]["version"]), str(build["base_image_md5"]),
            )
        else:
            base = None
        if base:
            for number, step in enumerate(builder.image_plan(manifest, base), 1):
                print(f"{number}. {step}")
            if args.build_image and not args.dry_run:
                print(f"Image build complete: {builder.build_disk_image(manifest, base)}")
                return 0
            if args.prepare_image and not args.dry_run:
                print(f"Prepared base image: {builder.prepare_base_image(base)}")
                return 0
            if args.dry_run:
                return 0
        elif args.prepare_image or args.build_image or args.dry_run:
            raise ImageBuilderError("--base-image is required for image operations.")
        artifact = builder.build_manifest(manifest, args.root)
    except (OSError, yaml.YAMLError, ImageBuilderError, BaseImageError, MountError, ManifestError) as exc:
        parser.error(str(exc))
    print(f"Build complete: {artifact}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
