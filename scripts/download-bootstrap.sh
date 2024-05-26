#!/bin/bash
set -e

if [[ -z "$BOOTSTRAP_DIR" ]]; then
    BOOTSTRAP_DIR="$(dirname "$0")/../lib/bootstrap"
fi

mkdir -p "$BOOTSTRAP_DIR"
cd "$BOOTSTRAP_DIR"
url="https://github.com/twbs/bootstrap/archive/refs/tags/v5.3.3.tar.gz"
curl -fsL "$url" | tar xz --strip-components 1
echo '*' > .gitignore
