#!/bin/bash
set -e

version=5.3.3

if [[ -z "$BOOTSTRAP_DIR" ]]; then
    BOOTSTRAP_DIR="$(dirname "$0")/../lib/bootstrap"
fi

url="https://github.com/twbs/bootstrap/archive/refs/tags/v$version.tar.gz"
mkdir -p "$BOOTSTRAP_DIR"
cd "$BOOTSTRAP_DIR"
curl -fsL "$url" | tar xz --strip-components 1
echo '*' > .gitignore
