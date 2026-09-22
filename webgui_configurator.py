from pathlib import Path
import secrets


class WebGUIConfigurator:

    def __init__(
        self,
        image_root: Path,
        username: str,
        ip_address: str | None = None,
        port: int = 8000,
    ):

        self.image_root = Path(image_root)
        self.username = username
        self.ip_address = ip_address
        self.port = port

    def generate_token(self) -> str:

        return secrets.token_urlsafe(32)

    def install_directory(self) -> Path:

        path = (
            self.image_root
            / "opt"
            / "aphys"
            / "lcnc-suite"
        )

        path.mkdir(
            parents=True,
            exist_ok=True,
        )

        return path

    def create_config(
        self,
        linuxcnc_ini: Path,
    ) -> dict:

        token = self.generate_token()

        allowed_origins = "*"

        if self.ip_address:
            allowed_origins = (
                f"http://"
                f"{self.ip_address}:"
                f"{self.port}"
            )

        config = {
            "WEBUI_HOST": "0.0.0.0",
            "WEBUI_PORT": str(self.port),
            "WEBUI_BROWSER": "1",
            "WEBUI_DEV": "0",
            "WEBUI_TOKEN": token,
            "WEBUI_ALLOWED_ORIGINS":
                allowed_origins,
        }

        self._write_ini_config(
            linuxcnc_ini,
            config,
        )

        return config

    def _write_ini_config(
        self,
        ini_path: Path,
        config: dict,
    ):

        text = ""

        if ini_path.exists():
            text = ini_path.read_text(
                encoding="utf-8"
            )

        if "[DISPLAY]" not in text:
            text += "\n[DISPLAY]\n"

        for key, value in config.items():

            if f"{key} =" not in text:

                text += (
                    f"{key} = {value}\n"
                )

        ini_path.write_text(
            text,
            encoding="utf-8",
        )