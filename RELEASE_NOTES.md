# Aphys Wizard 1.0.1

Documentation update for installing and running the source release. Application
code is unchanged from 1.0.0.

- Step-by-step virtual environment creation and dependency installation.
- Debian host packages, Windows/macOS configuration setup, and Linux build requirements.
- Explicit virtual environment interpreter when building with sudo.
- Host versus image dependencies, limitations of --check-host, and troubleshooting.

Validation: Bash examples passed shell syntax checks; 43 automated source tests
passed. Physical Raspberry Pi boot, login and machine operation remain unverified.
Core installation and managed GUI installation are not implemented.

Source archives contain no bootable images, private configurations or virtual
environments. Generate your own configuration and build on a suitable Linux host.
