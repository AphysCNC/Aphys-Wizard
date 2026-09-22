"""Provision local accounts in an offline Debian image, without ARM execution."""

import os
import re
import shutil
import subprocess
import time
import tempfile
from pathlib import Path


class AccountError(ValueError):
    pass


PASSWORD_HASH = re.compile(r"\$6\$(?:rounds=[0-9]+\$)?[./A-Za-z0-9]{1,16}\$[./A-Za-z0-9]{86}")
HARDWARE_GROUPS = {"audio", "video", "render", "input", "dialout", "plugdev", "netdev", "gpio", "spi", "i2c", "realtime"}


def hash_password(password: str) -> str:
    if not password or any(c in password for c in "\r\n\0"):
        raise AccountError("Password must be nonempty and contain no newline or NUL characters.")
    try:
        result = subprocess.run(
            ["openssl", "passwd", "-6", "-stdin"], input=password + "\n",
            text=True, encoding="utf-8", capture_output=True, check=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise AccountError("Cannot hash password. Install OpenSSL on the wizard/build host.") from exc
    value = result.stdout.strip()
    if not PASSWORD_HASH.fullmatch(value):
        raise AccountError("OpenSSL did not return a supported password hash.")
    return value


def _path(root: Path, relative: str) -> Path:
    path = root / relative
    # Do not let an image symlink redirect writes into the build host.
    for component in [path, *path.parents]:
        if component == root:
            break
        if component.is_symlink():
            raise AccountError(f"Refusing symlink in account path: {relative}")
    return path


def _read(root: Path, name: str, width: int, default: str) -> list[list[str]]:
    path = _path(root, "etc/" + name)
    text = path.read_text() if path.exists() else default
    rows = [line.split(":") for line in text.splitlines() if line]
    if any(len(row) != width for row in rows) or len({r[0] for r in rows}) != len(rows):
        raise AccountError(f"Invalid or duplicate entries in image /etc/{name}.")
    return rows


def _write(root: Path, relative: str, text: str, mode: int, gid: int = 0) -> None:
    path = _path(root, relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            os.fchmod(stream.fileno(), mode)
            if os.geteuid() == 0:
                os.fchown(stream.fileno(), 0, gid)
            stream.write(text)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def provision_user(root: Path, user: dict) -> None:
    root = Path(root).resolve()
    name = user["name"]
    if not re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", name) or name in {"root", "nobody"}:
        raise AccountError("Aphys requires a regular, non-root account name.")
    password_hash = user.get("password_hash") or hash_password("aphys")
    if not PASSWORD_HASH.fullmatch(password_hash):
        raise AccountError("Invalid SHA-512 password hash.")
    passwd = _read(root, "passwd", 7, "root:x:0:0:root:/root:/bin/bash\n")
    shadow = _read(root, "shadow", 9, "root:!:0:0:99999:7:::\n")
    groups = _read(root, "group", 4, "root:x:0:\n")
    gshadow = _read(root, "gshadow", 4, "root:!::\n")
    existing = next((r for r in passwd if r[0] == name), None)
    used_uids = {int(r[2]) for r in passwd}
    used_gids = {int(r[2]) for r in groups} | {int(r[3]) for r in passwd}
    if existing:
        uid, gid = int(existing[2]), int(existing[3])
        if not 1000 <= uid < 60000 or not 1000 <= gid < 60000 or existing[5] != f"/home/{name}":
            raise AccountError("Refusing to modify a system account or nonstandard home directory.")
        if sum(int(r[2]) == uid for r in passwd) != 1:
            raise AccountError("Refusing to modify a shared user ID.")
    else:
        uid = next(i for i in range(1000, 60000) if i not in used_uids)
        primary = next((r for r in groups if r[0] == name), None)
        if primary:
            gid = int(primary[2])
            if gid < 1000 or gid >= 60000:
                raise AccountError("Refusing to reuse a system group as the primary group.")
        else:
            gid = next(i for i in range(1000, 60000) if i not in used_gids)
            groups.append([name, "x", str(gid), ""])
        existing = [name, "x", str(uid), str(gid), "Aphys user", f"/home/{name}", "/bin/bash"]
        passwd.append(existing)
    existing[1], existing[6] = "x", "/bin/bash"
    shadow = [r for r in shadow if r[0] != name]
    shadow.append([name, password_hash, str(int(time.time() // 86400)), "0", "99999", "7", "", "", ""])
    for group in groups:
        members = [m for m in group[3].split(",") if m and m != name]
        if group[0] in HARDWARE_GROUPS or (group[0] == "sudo" and user.get("sudo", False)):
            members.append(name)
        # Preserve other memberships, except administrative groups when disabled.
        elif name in group[3].split(",") and group[0] not in {"sudo", "admin", "wheel"}:
            members.append(name)
        group[3] = ",".join(members)
        secret = next((r for r in gshadow if r[0] == group[0]), None)
        if secret is None:
            gshadow.append([group[0], "!", "", group[3]])
        else:
            secret[3] = group[3]
    home = _path(root, f"home/{name}")
    sudoers_path = _path(root, "etc/sudoers")
    sudoers = sudoers_path.read_text() if sudoers_path.exists() else "root ALL=(ALL:ALL) ALL\n"
    begin, end = f"# BEGIN APHYS USER {name}", f"# END APHYS USER {name}"
    sudoers = re.sub(re.escape(begin) + r"\n.*?" + re.escape(end) + r"\n?", "", sudoers, flags=re.S)
    rule = f"{name} ALL=(ALL:ALL) !ALL\n"
    if user.get("sudo", False):
        rule = (f"Defaults:{name} authenticate,!rootpw,!targetpw,!runaspw\n"
                f"{name} ALL=(ALL:ALL) PASSWD: ALL\n")
    # Last matching command rule wins, including any earlier NOPASSWD includes.
    sudoers = sudoers.rstrip() + f"\n\n{begin}\n{rule}{end}\n"
    shadow_gid = next((int(r[2]) for r in groups if r[0] == "shadow"), 0)
    for filename, rows, mode, owner_gid in (
        ("passwd", passwd, 0o644, 0), ("group", groups, 0o644, 0),
        ("shadow", shadow, 0o640, shadow_gid), ("gshadow", gshadow, 0o640, shadow_gid),
    ):
        _write(root, "etc/" + filename, "".join(":".join(r) + "\n" for r in rows), mode, owner_gid)
    _write(root, "etc/sudoers", sudoers, 0o440)
    if not home.exists():
        skeleton = _path(root, "etc/skel")
        if skeleton.is_dir():
            shutil.copytree(skeleton, home, symlinks=True)
        else:
            home.mkdir(parents=True)
    home.chmod(0o750)
    if os.geteuid() == 0:
        os.chown(home, uid, gid)
        for parent, directories, files in os.walk(home, followlinks=False):
            for child in directories + files:
                os.chown(Path(parent) / child, uid, gid, follow_symlinks=False)
