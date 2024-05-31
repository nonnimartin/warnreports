#!/bin/bash
set -e
basedir="$(dirname "$0")/.."
version=1.2.73
url="https://github.com/biglocalnews/warn-scraper/archive/refs/tags/$version.tar.gz"
cd "$basedir"
curl -fsL "$url" | tar xz --strip-components 1 "warn-scraper-$version/warn"
echo '*' > warn/.gitignore