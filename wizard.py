from datetime import datetime, timezone
from pathlib import Path
import getpass
import ipaddress
import re
import os
import platform
import shlex
import subprocess
import sys
import yaml

from resolver import Resolver
from product import create_product_configuration, core_placeholder
from accounts import AccountError, hash_password


def ask(
    question: str,
    default: str | None = None,
) -> str:

    if default is not None:

        value = input(
            f"{question} [{default}]: "
        ).strip()

        return value or default

    return input(
        f"{question}: "
    ).strip()


def yes_no(
    question: str,
    default: bool = True,
) -> bool:

    suffix = "Y/n" if default else "y/N"

    value = input(
        f"{question} [{suffix}]: "
    ).strip().lower()

    if not value:
        return default

    return value in (
        "y",
        "yes",
    )


def select_hardware_model(default_index: int = 0) -> str:
    """
    Presents a numbered list of supported hardware models
    and returns the selected model name.
    """

    models = [
        "Raspberry Pi 4",
        "Raspberry Pi 5",
        "Raspberry Pi Compute Module 4",
        "Raspberry Pi Compute Module 5",
    ]

    print()
    print("Supported Raspberry Pi models:")

    for i, model in enumerate(models, 1):
        marker = " (default)" if i - 1 == default_index else ""
        print(f"  {i}. {model}{marker}")

    default_model = models[default_index]

    while True:

        try:

            selection = input(
                f"Select model [{default_index + 1}]: "
            ).strip()

            if not selection:
                return default_model

            choice = int(selection)

            if 1 <= choice <= len(models):
                return models[choice - 1]

            print(
                f"Please enter a number between 1 and {len(models)}"
            )

        except ValueError:

            print(
                "Invalid input. Please enter a number."
            )


def select_setup_mode() -> str:
    """
    Presents setup mode options: default Aphys configuration
    or custom setup for advanced users.
    Returns either 'default' or 'custom'.
    """

    print()
    print("Setup mode:")
    print("  1. Aphys Default (recommended for most users)")
    print("  2. Custom (for advanced configuration)")

    while True:

        try:

            selection = input(
                "Select setup mode [1]: "
            ).strip()

            if not selection:
                return "default"

            choice = int(selection)

            if choice == 1:
                return "default"
            elif choice == 2:
                return "custom"
            else:

                print("Please enter 1 or 2")

        except ValueError:

            print(
                "Invalid input. Please enter a number."
            )


def select_network_mode(custom: bool = False) -> tuple[str, str | None, str | None, str | None]:
    """
    Presents network mode options: dhcp or static.
    For static mode, also prompts for gateway and netmask.
    Returns tuple of (mode, ip_address, gateway, netmask).
    If custom=False, uses default dhcp without prompting.
    """

    if not custom:
        return ("dhcp", None, None, None)

    print()
    print("Network mode:")
    print("  1. DHCP")
    print("  2. Static IP")

    while True:

        try:

            selection = input(
                "Select network mode [1]: "
            ).strip()

            if not selection:
                return ("dhcp", None, None, None)

            choice = int(selection)

            if choice == 1:
                return ("dhcp", None, None, None)

            elif choice == 2:

                ip_address = ask(
                    "Static IP address"
                )

                ipaddress.ip_address(
                    ip_address
                )

                gateway = ask(
                    "Gateway IP address"
                )

                ipaddress.ip_address(
                    gateway
                )

                netmask = ask(
                    "Netmask (e.g., 255.255.255.0 or /24)"
                )

                return ("static", ip_address, gateway, netmask)

            else:

                print("Please enter 1 or 2")

        except ValueError:

            print(
                "Invalid input. Please enter a number."
            )

        except ipaddress.AddressValueError:

            print(
                "Invalid IP address. Please enter a valid IPv4 or IPv6 address."
            )


def parse_ram_input(input_str: str) -> float:
    """
    Parse RAM input accepting both comma and dot as decimal separators.
    Returns float value in GB.
    Raises ValueError if input is invalid.
    """

    # Replace comma with dot for consistent parsing
    normalized = input_str.strip().replace(",", ".")

    try:
        ram_gb = float(normalized)
        return ram_gb
    except ValueError:
        raise ValueError(
            f"Invalid RAM value: '{input_str}'. "
            "Please enter a number (e.g., 4, 4.0, or 4,0)."
        )


def ask_ram_with_validation(
    resolver: Resolver,
    linuxcnc: object,
) -> float:
    """
    Ask for RAM and validate against LinuxCNC requirements.
    Returns RAM in GB as float.
    Shows warnings if RAM doesn't meet recommendations.
    """

    while True:

        try:

            ram_str = ask(
                "RAM (GB) [Aphys Motion Default is 4 GB]",
                "4",
            )

            ram_gb = parse_ram_input(ram_str)

            if ram_gb <= 0:
                print(
                    "ERROR: RAM must be greater than 0 GB."
                )
                print()
                continue

            # Check against LinuxCNC requirements
            if ram_gb < linuxcnc.ram_min_gb:
                print()
                print(
                    f"ERROR: Selected RAM ({ram_gb} GB) is below "
                    f"LinuxCNC minimum ({linuxcnc.ram_min_gb} GB)."
                )
                print()
                continue

            if ram_gb < linuxcnc.gui_ram_recommended_gb:
                print()
                print(
                    f"WARNING: Selected RAM ({ram_gb} GB) is below "
                    f"recommended GUI RAM ({linuxcnc.gui_ram_recommended_gb} GB)."
                )
                print(
                    "GUI performance may be limited."
                )
                print()

            return ram_gb

        except ValueError as e:
            print(
                f"ERROR: {e}"
            )
            print()


def ask_configuration_name() -> str:
    while True:
        name = ask("Configuration name")
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", name):
            return name
        print("Use 1-64 letters, digits, dots, underscores or hyphens.")


def offer_image_build(manifest: Path) -> int:
    """Optionally build the saved manifest using this Python environment."""
    command = [
        sys.executable, str(Path(__file__).resolve().with_name("image_builder.py")),
        str(manifest.resolve()), "--build-image", "--check-host",
    ]
    if platform.system() != "Linux":
        print("Configuration saved. Build the disk image on a Linux host:")
        print(f"sudo python3 image_builder.py {shlex.quote(str(manifest))} --build-image --check-host")
        return 0
    if os.geteuid() != 0:
        command.insert(0, "sudo")
    try:
        if not yes_no("Build the disk image now?", default=False):
            print("Build later with:")
            print(shlex.join(command))
            return 0
        print("The builder may ask for your host sudo password.")
        print("Starting image builder...")
        result = subprocess.run(command, check=False)
    except EOFError:
        print("Configuration saved. Build later with:")
        print(shlex.join(command))
        return 0
    except KeyboardInterrupt:
        print("Build interrupted. Your saved configuration is retained.")
        return 130
    except OSError as exc:
        print(f"Could not start image builder: {exc}")
        print(f"Your configuration is saved at {manifest}.")
        return 1
    if result.returncode:
        print(f"Image build failed (exit {result.returncode}). Your configuration is saved at {manifest}.")
        print("Retry with:")
        print(shlex.join(command))
    return result.returncode


def ask_password_hash() -> str:
    while True:
        password = getpass.getpass("Account password (Enter for default 'aphys'): ")
        if not password:
            return hash_password("aphys")
        if password != getpass.getpass("Confirm account password: "):
            print("Passwords do not match. Please try again.")
            continue
        try:
            return hash_password(password)
        except AccountError as exc:
            print(str(exc))
            raise


def main():

    print()
    print("=" * 60)
    print("APHYS WIZARD")
    print("=" * 60)
    print()

    resolver = Resolver()

    # Hardware

    model = select_hardware_model(
        default_index=1  # Default to "Raspberry Pi 5" (index 1)
    )

    # Resolve LinuxCNC early to validate RAM requirements
    print()
    print("Resolving LinuxCNC...")

    linuxcnc = resolver.latest_linuxcnc()

    # Ask for RAM with validation against LinuxCNC requirements
    print()
    ram = ask_ram_with_validation(
        resolver,
        linuxcnc,
    )

    # Setup mode selection (after RAM to provide context)
    setup_mode = select_setup_mode()

    print()
    if setup_mode == "default":
        print("Using Aphys Default configuration...")
    else:
        print("Using Custom configuration...")

    hardware = resolver.resolve_hardware(
        model,
        int(ram),  # Convert to int for resolver
    )

    print()
    print("Hardware detected:")
    print(
        f"  Model: {hardware.model}"
    )
    print(
        f"  Architecture: {hardware.architecture}"
    )
    print(
        f"  RAM: {hardware.ram_gb} GB"
    )

    if hardware.ethernet_connections is not None:
        print(
            f"  Ethernet connections: {hardware.ethernet_connections}"
        )

    if hardware.model == "Raspberry Pi 4":
        print(
            "  NOTE: Raspberry Pi 4 supports a single Ethernet connection."
        )

    # LinuxCNC Compatibility Check

    print()
    print("Compatibility check")
    print("-" * 60)

    compatibility = resolver.check_linuxcnc(
        hardware,
        linuxcnc,
    )

    print(
        f"LinuxCNC version: "
        f"{linuxcnc.version}"
    )
    print(f"Image status: {linuxcnc.discovery_status}")
    if linuxcnc.image_url:
        print(f"Image source: {linuxcnc.image_url}")

    print(
        f"LinuxCNC RAM minimum: "
        f"{linuxcnc.ram_min_gb} GB"
    )

    print(
        f"GUI RAM recommended: "
        f"{linuxcnc.gui_ram_recommended_gb} GB"
    )

    # System

    print()
    print("System configuration")
    print("-" * 60)

    default_user = "aphys"

    if setup_mode == "default":
        username = default_user
        network_mode, ip_address, gateway, netmask = select_network_mode(custom=False)

        print(
            f"Using Aphys defaults:"
        )
        print(
            f"  Username: {username}"
        )
        print(
            f"  Network: {network_mode}"
        )

    else:

        custom_user = yes_no(
            "Use default username 'aphys'?",
            True,
        )

        if custom_user:
            username = default_user

        else:

            username = ask(
                "Username"
            )


        network_mode, ip_address, gateway, netmask = select_network_mode(custom=True)

    password_hash = ask_password_hash()

    product = create_product_configuration()

    print()
    print("Aphys software stack")
    print("-" * 60)
    print("Aphys Core: not installed yet. Using the base image’s LinuxCNC interface.")

    print(
        f"SSH: "
        f"{'enabled' if product.ssh_enabled else 'disabled'}"
    )

    print(
        f"User sudo access: "
        f"{'enabled' if product.sudo_user else 'disabled'}"
    )

    print(
        f"Realtime kernel: "
        f"{'required' if product.realtime_required else 'optional'}"
    )

    # Configuration name

    configuration_name = ask_configuration_name()

    # YAML

    created_at = (
        datetime.now(
            timezone.utc
        )
        .isoformat()
    )

    configuration = {

        "build": {
            "profile": linuxcnc.build_profile,
            "base_image_manifest": linuxcnc.base_image_manifest,
            "base_image_url": linuxcnc.image_url,
            "base_image_md5": linuxcnc.image_md5,
            "update_policy": "frozen",
        },

        "metadata": {
            "name": configuration_name,
            "config_version": "1.0",
            "schema_version": "1.0",
            "created_at": created_at,
        },

        "hardware": {
            "platform": hardware.model,
            "architecture": hardware.architecture,
            "ram_gb": hardware.ram_gb,
            "ethernet_connections": hardware.ethernet_connections,
            "os": {
                "distribution": "Debian",
                "architecture": "arm64",
                "realtime": True,
            },
            "linuxcnc": {
                "version": linuxcnc.version,
            },
        },

        "system": {

            "user": {
                "name": username,
                "password_hash": password_hash,
                "sudo": True,
            },

            "network": {
                "mode": network_mode,
                "address": ip_address,
                "gateway": gateway,
                "netmask": netmask,
            },

            "ssh": {
                "enabled": True,
            },
        },

        "machine": {

            "profile": "default",

            "axes": {
                "x": {},
                "y": {},
                "z": {},
            },

            "motion": {
                "controller": "Aphys Motion",
            },
        },

        "core": core_placeholder(),
        "gui": {"enabled": False, "provider": None},
    }

    output_dir = Path("output")

    output_dir.mkdir(
        exist_ok=True
    )

    filename = (
        f"{configuration_name}_"
        f"linuxcnc-{linuxcnc.version}_"
        f"arm64_"
        f"rt.yaml"
    )

    output = (
        output_dir / filename
    )

    # The build manifest contains a password hash; keep it private from creation.
    with os.fdopen(os.open(output, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), 0o600), "w", encoding="utf-8") as stream:
        if hasattr(os, "fchmod"):
            os.fchmod(stream.fileno(), 0o600)
        stream.write(yaml.safe_dump(
            configuration,
            sort_keys=False,
            allow_unicode=True,
        ))

    print()
    print("=" * 60)
    print("CONFIGURATION CREATED")
    print("=" * 60)
    print()
    print(output)
    print()
    print("Wizard finished.")
    return offer_image_build(output)


if __name__ == "__main__":
    raise SystemExit(main())
