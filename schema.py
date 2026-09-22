"""Validation and normalization for Aphys build manifests."""

from __future__ import annotations

import ipaddress
import re
from copy import deepcopy
from datetime import datetime

try:
    from .product import core_placeholder
    from .accounts import PASSWORD_HASH
except ImportError:
    from product import core_placeholder
    from accounts import PASSWORD_HASH


class ManifestError(ValueError):
    pass


_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_USER = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")


def validate_manifest(value: object) -> dict:
    if not isinstance(value, dict):
        raise ManifestError("The manifest must be a YAML mapping.")

    data = deepcopy(value)
    core = data.setdefault("core", core_placeholder())
    if not isinstance(core, dict):
        raise ManifestError("core must be a mapping.")
    core.setdefault("enabled", False)
    core.setdefault("version", None)
    core.setdefault("source", core_placeholder()["source"])
    if not isinstance(core["enabled"], bool):
        raise ManifestError("core.enabled must be true or false.")
    if core["enabled"]:
        raise ManifestError("Core installation is not implemented yet; set core.enabled to false.")
    if core["version"] is not None and not isinstance(core["version"], str):
        raise ManifestError("core.version must be a string or null.")
    source = _mapping(core, "source", "core")
    for key in ("type", "location", "sha256"):
        source.setdefault(key, None)
        if source[key] is not None and not isinstance(source[key], str):
            raise ManifestError(f"core.source.{key} must be a string or null.")
    if source["type"] not in (None, "local", "url"):
        raise ManifestError("core.source.type must be local, url, or null.")
    if source["sha256"] is not None and not re.fullmatch(r"[0-9a-fA-F]{64}", source["sha256"]):
        raise ManifestError("core.source.sha256 must contain 64 hexadecimal characters or be null.")
    for key in ("control_lock", "control_log"):
        if key in core:
            settings = _mapping(core, key, "core")
            if not isinstance(settings.get("enabled"), bool):
                raise ManifestError(f"core.{key}.enabled must be true or false.")
    build = _mapping(data, "build") if "build" in data else None
    if build is not None:
        if build.get("profile") != "aphys-stable":
            raise ManifestError("Only the aphys-stable build profile is currently supported.")
        if build.get("update_policy") != "frozen":
            raise ManifestError("Stable builds must use the frozen update policy.")
        base_name = build.get("base_image_manifest")
        if base_name is not None and (not isinstance(base_name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*\.yaml", base_name)):
            raise ManifestError("build.base_image_manifest must be a safe YAML filename.")
        if not base_name:
            url = build.get("base_image_url")
            checksum = build.get("base_image_md5")
            if not isinstance(url, str) or not url.startswith("https://www.linuxcnc.org/iso/"):
                raise ManifestError("Dynamic base image must come from the official LinuxCNC ISO directory.")
            if not isinstance(checksum, str) or not re.fullmatch(r"[0-9a-fA-F]{32}", checksum):
                raise ManifestError("Dynamic base image requires LinuxCNC's published MD5.")
    metadata = _mapping(data, "metadata")
    name = metadata.get("name")
    if not isinstance(name, str) or not _NAME.fullmatch(name):
        raise ManifestError("metadata.name must be a filesystem-safe name (letters, digits, '.', '_' or '-').")
    if str(metadata.get("schema_version")) != "1.0":
        raise ManifestError("Only schema_version 1.0 is supported.")
    created_at = metadata.get("created_at")
    try:
        datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ManifestError("metadata.created_at must be an ISO-8601 timestamp.") from exc

    hardware = _mapping(data, "hardware")
    architecture = hardware.get("architecture")
    os_config = _mapping(hardware, "os", "hardware")
    if architecture != "arm64" or os_config.get("architecture") != architecture:
        raise ManifestError("The hardware and OS architectures must both be arm64.")
    if os_config.get("realtime") is not True:
        raise ManifestError("hardware.os.realtime must be true.")
    linuxcnc = _mapping(hardware, "linuxcnc", "hardware")
    if not linuxcnc.get("version") or str(linuxcnc["version"]).lower() == "latest":
        raise ManifestError("hardware.linuxcnc.version must be pinned.")

    system = _mapping(data, "system")
    user = _mapping(system, "user", "system")
    if not isinstance(user.get("name"), str) or not _USER.fullmatch(user["name"]):
        raise ManifestError("system.user.name is not a valid Linux username.")
    if user["name"] in {"root", "nobody"}:
        raise ManifestError("system.user.name must be a regular non-root account.")
    if "password" in user:
        raise ManifestError("Use system.user.password_hash, not a plaintext password.")
    if "password_hash" in user and (
        not isinstance(user["password_hash"], str) or not PASSWORD_HASH.fullmatch(user["password_hash"])
    ):
        raise ManifestError("system.user.password_hash must be a SHA-512 crypt hash.")
    if not isinstance(user.get("sudo", False), bool):
        raise ManifestError("system.user.sudo must be true or false.")

    network = _mapping(system, "network", "system")
    mode = network.get("mode")
    if mode not in {"dhcp", "static"}:
        raise ManifestError("system.network.mode must be 'dhcp' or 'static'.")
    if mode == "dhcp":
        network.update(address=None, gateway=None, netmask=None)
    else:
        try:
            address = ipaddress.ip_address(network.get("address"))
            gateway = ipaddress.ip_address(network.get("gateway"))
            prefix = _prefix(network.get("netmask"), address.version)
        except (ValueError, TypeError) as exc:
            raise ManifestError(f"Invalid static network configuration: {exc}") from exc
        if address.version != gateway.version:
            raise ManifestError("Static address and gateway must use the same IP version.")
        network["address"] = str(address)
        network["gateway"] = str(gateway)
        network["netmask"] = f"/{prefix}"

    gui = _mapping(data, "gui")
    if gui.get("enabled") and gui.get("provider") not in {"lcnc-suite", "qtplasmac"}:
        raise ManifestError("gui.provider must be 'lcnc-suite' or 'qtplasmac'.")
    return data


def _mapping(parent: dict, key: str, path: str = "") -> dict:
    value = parent.get(key)
    if not isinstance(value, dict):
        label = f"{path}.{key}" if path else key
        raise ManifestError(f"{label} must be a mapping.")
    return value


def _prefix(value: object, version: int) -> int:
    if isinstance(value, str) and value.startswith("/"):
        prefix = int(value[1:])
        maximum = 32 if version == 4 else 128
        if not 0 <= prefix <= maximum:
            raise ValueError("prefix length is out of range")
        return prefix
    if version != 4:
        raise ValueError("IPv6 netmask must use /prefix notation")
    return ipaddress.IPv4Network(f"0.0.0.0/{value}").prefixlen
