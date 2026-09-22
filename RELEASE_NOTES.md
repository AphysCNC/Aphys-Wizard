# Aphys Wizard 1.0.0

Source release of the LinuxCNC image configuration wizard and offline image builder.

- Wizard configuration and optional image build handoff.
- Offline user/password provisioning, password-required sudo and hardware groups.
- SSH password/key authentication and offline OpenSSH service configuration.
- Base image interface retained; Aphys Core declarations are accepted but installation
  remains disabled and enabling it fails before image acquisition.
- Clean public source distribution without local profiles, generated configurations,
  disk images, virtual environments or internal development history.

Validation: 43 automated tests passed on the release source. A successful boot,
login and machine operation on a physical Raspberry Pi have not been verified
for this release. Core installation and managed GUI installation are not implemented.

The source archives are not bootable images. Generate a private build configuration
with the wizard and build an image on a suitable Linux host. The default account
password is `aphys`; choose your own password during configuration.
