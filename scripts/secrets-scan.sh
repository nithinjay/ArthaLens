#!/bin/sh
# Scan every file git would commit (tracked + untracked-but-not-ignored) for secrets.
# Files are streamed into the container, so no Docker file sharing is needed.
set -eu
cd "$(dirname "$0")/.."

git ls-files -z --cached --others --exclude-standard \
  | tar --null -cf - -T - \
  | docker run --rm -i --entrypoint sh ghcr.io/gitleaks/gitleaks:v8.30.1 -c \
      'mkdir -p /scan && tar -xf - -C /scan && gitleaks dir /scan --config /scan/.gitleaks.toml --redact --no-banner'
