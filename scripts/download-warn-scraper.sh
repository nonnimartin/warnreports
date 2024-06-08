#!/bin/bash
set -e

version=1.2.73

if [[ -z "$WARN_SCRAPER_DIR" ]]; then
    WARN_SCRAPER_DIR="$(dirname "$0")/../warn"
fi

url="https://github.com/biglocalnews/warn-scraper/archive/refs/tags/$version.tar.gz"
mkdir -p "$WARN_SCRAPER_DIR"
cd "$WARN_SCRAPER_DIR"
curl -fsL "$url" | tar xz --strip-components 2 "warn-scraper-$version/warn"
echo '*' > .gitignore
