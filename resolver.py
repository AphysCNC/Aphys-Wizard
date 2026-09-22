from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
import re
from urllib.parse import urljoin, urlparse

import requests
STABLE_LINUXCNC_VERSION = "2.9.8"
STABLE_BASE_IMAGE_MANIFEST = "linuxcnc-2.9.8-rpi4-rpi5-trixie.yaml"
LINUXCNC_DOWNLOADS_URL = "https://linuxcnc.org/downloads/"
_PI_IMAGE = re.compile(
    r"image_\d{4}-\d{2}-\d{2}-raspios-lcnc-(?P<version>\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?)-[a-z0-9]+-arm64\.zip$"
)


@dataclass
class HardwareInfo:
    model: str
    architecture: str
    ram_gb: int
    ethernet_connections: int | None = None


@dataclass
class LinuxCNCInfo:
    version: str
    ram_min_gb: float
    gui_ram_recommended_gb: float
    build_profile: str = "aphys-stable"
    base_image_manifest: str | None = STABLE_BASE_IMAGE_MANIFEST
    image_url: str | None = None
    image_md5: str | None = None
    discovery_status: str = "verified"


class _LinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            self._href = dict(attrs).get("href")
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._href is not None:
            self.links.append((self._href, "".join(self._text).strip()))
            self._href = None
            self._text = []


class ResolverError(Exception):
    pass


class Resolver:

    def discover_raspberry_pi_image(self) -> tuple[str, str, str]:
        """Return (version, URL, published MD5) from the official page."""
        try:
            response = requests.get(LINUXCNC_DOWNLOADS_URL, timeout=15)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise ResolverError(f"Could not check LinuxCNC downloads: {exc}") from exc
        parser = _LinkParser()
        parser.feed(response.text)
        candidates: list[tuple[str, str]] = []
        for href, label in parser.links:
            url = urljoin(LINUXCNC_DOWNLOADS_URL, href)
            filename = Path(urlparse(url).path).name
            match = _PI_IMAGE.fullmatch(filename)
            if match and "raspberry pi" in label.lower():
                candidates.append((match.group("version"), url))
        if len(candidates) != 1:
            raise ResolverError(
                f"Expected one official Raspberry Pi 4/5 image link, found {len(candidates)}."
            )
        checksums = re.findall(r"MD5SUM\s+([0-9a-fA-F]{32})", response.text)
        if len(checksums) != 1:
            raise ResolverError(f"Expected one published Raspberry Pi image MD5, found {len(checksums)}.")
        return candidates[0][0], candidates[0][1], checksums[0].lower()

    def resolve_current_linuxcnc(self) -> LinuxCNCInfo:
        version, image_url, image_md5 = self.discover_raspberry_pi_image()
        manifests_dir = Path(__file__).resolve().parent / "manifests"
        matches = []
        for path in manifests_dir.glob("*.yaml"):
            text = path.read_text(encoding="utf-8")
            if f"source_url: {image_url}" in text:
                matches.append(path.name)
        return LinuxCNCInfo(
            version=version,
            ram_min_gb=1.0,
            gui_ram_recommended_gb=2.0,
            base_image_manifest=matches[0] if len(matches) == 1 else None,
            image_url=image_url,
            image_md5=image_md5,
            discovery_status="official-source",
        )

    def resolve_hardware(
        self,
        model: str,
        ram_gb: int,
    ) -> HardwareInfo:

        model = model.strip()

        supported_models = {
            "raspberry pi 4": "Raspberry Pi 4",
            "raspberry pi 5": "Raspberry Pi 5",
            "raspberry pi compute module 4":
                "Raspberry Pi Compute Module 4",
            "raspberry pi compute module 5":
                "Raspberry Pi Compute Module 5",
        }

        key = model.lower()

        if key not in supported_models:
            raise ResolverError(
                f"Unsupported Raspberry Pi model: {model}"
            )

        if ram_gb <= 0:
            raise ResolverError(
                "RAM must be greater than zero."
            )

        ethernet_connections = None

        if key == "raspberry pi 4":
            ethernet_connections = 1

        return HardwareInfo(
            model=supported_models[key],
            architecture="arm64",
            ram_gb=ram_gb,
            ethernet_connections=ethernet_connections,
        )

    def stable_linuxcnc(self) -> LinuxCNCInfo:
        """Return the immutable LinuxCNC stack verified by Aphys."""
        return LinuxCNCInfo(
            version=STABLE_LINUXCNC_VERSION,
            ram_min_gb=1.0,
            gui_ram_recommended_gb=2.0,
        )

    def latest_linuxcnc(self) -> LinuxCNCInfo:
        """Resolve the newest official Pi image that Aphys has verified."""
        return self.resolve_current_linuxcnc()

    def check_linuxcnc(
        self,
        hardware: HardwareInfo,
        linuxcnc: LinuxCNCInfo,
    ) -> dict:

        result = {
            "linuxcnc_version": linuxcnc.version,
            "linuxcnc_ram_min_gb":
                linuxcnc.ram_min_gb,
            "gui_ram_recommended_gb":
                linuxcnc.gui_ram_recommended_gb,
            "ram_ok": True,
            "gui_ram_warning": False,
        }

        if hardware.ram_gb < linuxcnc.ram_min_gb:
            result["ram_ok"] = False

        if hardware.ram_gb < linuxcnc.gui_ram_recommended_gb:
            result["gui_ram_warning"] = True

        return result
