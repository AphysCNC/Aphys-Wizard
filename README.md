# aphys_wizard

A bridge between people and great CNC machines. Part one: how does one pre-configure LinuxCNC.

Say you are supposed to build and integrate ten new CNC machines based on LinuxCNC within a company's subnet 192.168.10.0/24, each having custom its own static IP, login credentials and a password, all needing the latest LinuxCNC version verified for use on a Raspberry Pi (4 or 5, Compute module or regular). No need to edit the network settings and more manually after each individual LinuxCNC install.

At this point, Wizard does not create the hal and ini configs for given mahcine, but has a structure inside its .yaml as a preparation for a potential future expansion.

Aphys Wizard takes care of that. Checks for the newest version, downloads the image, writes changes to it, and produces either an img or a compressed img.xz image ready to be flashed onto an SD / other memory via the Raspberry Pi Imager.

Internet connection required for downloading the image.

## Source release 1.0.0

Install Python 3.10 or newer and the dependencies in `requirements.txt` in a virtual
environment. See [release notes](RELEASE_NOTES.md) for validation and limitations.
Public source archives contain no prebuilt disk images or private build settings.
The files in `manifests/` are distribution metadata for public upstream images.

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
python3 image_builder.py output/my-config.yaml
```

This writes a `.tar` under `image-work/output/`. To inspect the full image build
plan without downloading a base image:

```bash
python3 image_builder.py output/my-config.yaml --dry-run --check-host
```

On a Linux build worker, the first end-to-end image command is:

```bash
sudo python3 image_builder.py output/my-config.yaml \
  --build-image --check-host
```

This preserves the extracted base image, modifies a per-job copy, automatically
unmounts it, and produces `image-work/output/<name>.img.xz` plus a `.sha256`
file. Software installers and base-image-specific service validation are not yet
part of this command.

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
