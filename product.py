from dataclasses import dataclass


@dataclass
class ProductConfiguration:

    webgui_enabled: bool
    webgui_provider: str | None

    ssh_enabled: bool
    sudo_user: bool

    vpn_enabled: bool
    vpn_provider: str

    realtime_required: bool


def core_placeholder() -> dict:
    """Return independent defaults for the future external Core release."""
    return {"enabled": False, "version": None,
            "source": {"type": None, "location": None, "sha256": None}}


def create_product_configuration() -> ProductConfiguration:
    return ProductConfiguration(
        webgui_enabled=False,
        webgui_provider=None,

        ssh_enabled=True,
        sudo_user=True,

        vpn_enabled=True,
        vpn_provider="tailscale",

        realtime_required=True,
    )
