# Base-image manifests

Every buildable LinuxCNC image must have a reviewed YAML manifest containing
its exact HTTPS download URL and SHA-256 checksum. Do not commit guessed URLs,
mutable `latest` links, or placeholder checksums.

Copy `base-image.example.yaml` after verifying an upstream image, replace every
placeholder, then give the resulting file to `image_builder.py --base-image`.
