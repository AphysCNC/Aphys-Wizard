# aphys_wizard

A bridge between people and great CNC machines. Part one: how does one pre-configure LinuxCNC.

Say you are supposed to build and integrate ten new CNC machines based on LinuxCNC within a company's subnet 192.168.10.0/24, each having custom its own static IP, login credentials and a password, all needing the latest LinuxCNC version verified for use on a Raspberry Pi (4 or 5, Compute module or regular). No need to edit the network settings and more manually after each individual LinuxCNC install.

At this point, Wizard does not create the hal and ini configs for given mahcine, but has a structure inside its .yaml as a preparation for a potential future expansion.

Aphys Wizard takes care of that. Checks for the newest version, downloads the image, writes changes to it, and produces either an img or a compressed img.xz image ready to be flashed onto an SD / other memory via the Raspberry Pi Imager.

Internet connection required for downloading the image.

## Source release 1.0.1

Install Python 3.10 or newer and the dependencies in `requirements.txt` in a virtual
environment. See [release notes](RELEASE_NOTES.md) for validation and limitations.
Public source archives contain no prebuilt disk images or private build settings.
The files in `manifests/` are distribution metadata for public upstream images.

## Installation

`requirements.txt` installs Python libraries (`requests`, `packaging`, `PyYAML`)
and their dependencies. It does not install Python, create a virtual environment,
or supply operating-system tools. Create your own `.venv` on each machine; do not
copy one from another computer or operating system. The version constraints are
minimum versions, not a lockfile for an exactly reproducible Python environment.

### Linux host prerequisites

The following setup commands target Debian 13. On other distributions, install
equivalent packages using their package manager. Python 3.10 or newer is required.

For running the wizard and generating configuration:

```bash
sudo apt update
sudo apt install python3 python3-venv openssl ca-certificates
```

For building disk images on the same host, also install:

```bash
sudo apt install sudo util-linux mount coreutils xz-utils systemd
```

These commands assume your account already has sudo access. Otherwise, ask the
host administrator to install the packages and grant the required build access.

| Host dependency | Purpose |
| --- | --- |
| Python and `python3-venv` | Run the code and create the Python environment with pip. |
| `openssl` | Generate password hashes using `openssl passwd -6`; required by the wizard. |
| CA certificates and internet access | Install Python packages, resolve the official image, and download it. |
| `sudo` | Elevate the image builder; the wizard itself runs as your normal user. |
| `losetup`, `lsblk`, `mount`, `umount` | Attach, discover, mount and detach image partitions. |
| `systemctl` | Configure SSH services offline inside the image. |
| `chroot`, `xz` | Required by the current host check; image extraction/compression uses Python's standard library. |

The host must allow loop devices and filesystem mounts. A container without the
necessary device access and privileges cannot build images merely by installing
these packages. Keep enough free disk space for the downloaded archive, extracted
base image, a separate working image and the compressed result simultaneously.

Host tools and image contents are separate: the base image must already contain
OpenSSH server and `ssh.service` when SSH is enabled, and sudo when administrator
access is requested. Installing these packages on the host does not add them to
the image.

### Create the Python environment and run

Download and extract the source release, or clone the public repository. Open a
terminal in the directory containing `wizard.py` and `requirements.txt`, then run:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pip check
python wizard.py
```

Create the environment and install its packages as your normal user, without
sudo. In a new terminal, return to the project directory and run
`source .venv/bin/activate` again. Use `deactivate` to leave the environment.
Alternatively, `.venv/bin/python wizard.py` works without activation.

For configuration generation on Windows, install Python 3.10+ and an OpenSSL
executable supporting `passwd -6` on PATH. From PowerShell in the source directory:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe wizard.py
```

On macOS, use the Linux-style venv commands and install a compatible OpenSSL
executable on PATH. Disk image builds require Linux; transfer your generated YAML
to a Linux build host and create a separate venv there. Configuration files contain
password hashes and potentially private network settings; keep them out of Git
and public release attachments.

Background: [Python's pip/venv installation guide](https://packaging.python.org/en/latest/guides/installing-using-pip-and-virtual-environments/)
and [Debian's python3-venv package](https://packages.debian.org/trixie/python3-venv).

## Run the working builder stage

Run `python3 wizard.py` in your Python environment. After saving the configuration,
the wizard asks **Build the disk image now? [y/N]** on Linux. Answer `y` to run
the image builder immediately. It uses the same Python interpreter and requests
sudo for the build if needed; run the wizard itself as your normal user. Build
progress appears in the same terminal. The result is
`image-work/output/<name>.img.xz` with an adjacent `.sha256` file.

Answer `n` (or press Enter) to save without building; the wizard prints the exact
command to build later. A failed build retains the YAML and returns a nonzero
exit status. On other operating systems, transfer the saved manifest to a Linux
build host. The working directory determines the `output` and `image-work`
locations. The launch does not enable `--clean` or overwrite an existing final image.

For a configuration-only root filesystem archive (not a bootable image):

```bash
.venv/bin/python image_builder.py output/my-config.yaml
```

This writes a `.tar` under `image-work/output/`. To inspect the full image build
plan without downloading a base image:

```bash
.venv/bin/python image_builder.py output/my-config.yaml --dry-run --check-host
```

On a Linux build worker, the first end-to-end image command is:

```bash
sudo .venv/bin/python image_builder.py output/my-config.yaml \
  --build-image --check-host
```

This preserves the extracted base image, modifies a per-job copy, automatically
unmounts it, and produces `image-work/output/<name>.img.xz` plus a `.sha256`
file. Software installers and base-image-specific service validation are not yet
part of this command.

Replace `output/my-config.yaml` with the actual filename printed by the wizard.
Run these commands from the project directory. Use the explicit venv Python path
with sudo: `sudo python3` may select the system Python and fail to find packages
installed in `.venv`. Accepting the build prompt in the wizard already preserves
its Python interpreter when requesting sudo.

### Host checks and troubleshooting

`--check-host` requires a manifest argument and prints the Linux/root status and
availability of `losetup`, `lsblk`, `mount`, `umount`, `chroot` and `xz`. A dry run
as your normal user can report `ready: false` because `is_root` is false; the actual
disk build requires elevation. The check does not currently verify OpenSSL,
`systemctl`, loop-device permissions, disk space or the contents of the base image.
Even `ready: true` is not a guarantee that a build or the resulting image will work.

| Symptom | What to check |
| --- | --- |
| `venv` / `ensurepip` unavailable | Install `python3-venv` for the selected interpreter, then create the environment again. |
| `No module named yaml` or `requests` | Install requirements with `.venv/bin/python -m pip install -r requirements.txt` and run with that same Python. |
| Imports fail only when building with sudo | Use `sudo .venv/bin/python ...`, not `sudo python3 ...`. |
| Password hashing fails | Check that `openssl` is on PATH and supports `passwd -6`. |
| Host check lists missing commands | Install the corresponding system packages above. |
| Loop-device or mount permission errors | Check root privileges and host/container device access. |
| SSH or sudo missing in the base image | Use a base image supplying the required server/unit or sudo binary; host packages do not satisfy this. |

Wizard manifests use the frozen `aphys-stable` profile: the official Pi 4/5
image and LinuxCNC 2.9.8. The matching pinned base-image manifest is selected
automatically. Updating LinuxCNC is intentionally outside image construction;
it will be handled by a separately versioned updater with validation and rollback.

At wizard startup the resolver reads LinuxCNC's official Downloads page and
extracts the version and published MD5 from its Raspberry Pi 4/5 image URL.
That official entry is the source of truth. A matching Aphys manifest is reused
as a checksum cache when available; otherwise the builder verifies the upstream
MD5 and records its own SHA-256 after downloading the new image.

## Account and permissions

The wizard asks for an account password in both Default and Custom setup. Enter
accepts the default `aphys`; custom passwords require confirmation. OpenSSL must
be installed on the wizard host. The saved manifest contains a salted SHA-512
crypt `system.user.password_hash`, never the entered password, and is saved with
mode `0600`. Existing manifests without a hash use the default password `aphys`.

The builder provisions the account directly in the offline image's passwd,
shadow, group and gshadow databases. It creates `/home/<name>` from `/etc/skel`,
uses Bash, assigns available regular UID/GID values (preserving existing regular
accounts), and sets home ownership and mode `0750`. Shadow files are root-owned
with mode `0640` and the image's shadow group. The account is ready at first boot;
there is no deferred account-creation service. A non-root fixture render writes
the same records but cannot apply target UID/GID ownership; disk builds run as root.

`sudo: true` grants password-required sudo, using the account password even if
the base image previously had a matching NOPASSWD rule. `sudo: false` removes
administrative group memberships and explicitly denies sudo for this account.
The managed rule is placed at the end of `/etc/sudoers`, mode `0440`. Disk builds
requiring sudo fail if the base image does not already contain it.

Hardware memberships are added only for groups present in the image: audio,
video, render, input, dialout, plugdev, netdev, gpio, spi, i2c and realtime.
No broad disk or Docker access is added. Kernel/device configuration and LinuxCNC
realtime limits remain those of the base image.

The image's `/etc/aphys/build.yaml` omits the password hash; `/etc/aphys/user.yaml`
records that the user was provisioned. The credential is stored in `/etc/shadow`.
SSH permits password and key authentication; real disk builds enable the existing
OpenSSH service. The base image must supply the server.

## Aphys Core preparation

Wizard no longer queries or selects LCNC Suite, or automatically falls back to
QtPlasmaC. It preserves the base image's LinuxCNC interface and desktop.
The retained WebGUI helper modules are not part of the active wizard flow.

Generated manifests contain:

```yaml
core:
  enabled: false
  version: null
  source:
    type: null
    location: null
    sha256: null
gui:
  enabled: false
  provider: null
```

`gui.enabled: false` disables Wizard-managed GUI installation, not the base desktop.
Run `wizard.py` to generate a private build manifest. Local profiles and generated
configuration are intentionally excluded from the public source release.

Core installation is not implemented. Enabling it fails before acquisition or
image changes. Null source fields are placeholders, never download targets.
Future sources may be `local` (a release artifact on the build host) or `url`
(an HTTPS release download from Forgejo, GitHub, or another host), with a pinned
version and SHA-256. Package format, authentication, installation and graphical
startup remain deferred until Core has a release. Control-lock and control-log
settings are also future declarations, not active features.

Older manifests without Core default to disabled. Legacy GUI settings are accepted
with an explicit notice during rendering, but are not applied. The sanitized
`/etc/aphys/build.yaml` preserves the requested configuration; `product.yaml`
records Core as `installed: false` and managed GUI installation as disabled.
