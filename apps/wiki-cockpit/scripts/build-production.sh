#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
NODE_BIN=$(command -v node) || {
  echo "release build launcher could not resolve node" >&2
  exit 1
}
while [ -L "$NODE_BIN" ]; do
  NODE_LINK=$(readlink "$NODE_BIN")
  case "$NODE_LINK" in
    /*) NODE_BIN=$NODE_LINK ;;
    *) NODE_BIN=$(dirname -- "$NODE_BIN")/$NODE_LINK ;;
  esac
done
NODE_DIR=$(CDPATH= cd -P -- "$(dirname -- "$NODE_BIN")" && pwd)
NODE_BIN="$NODE_DIR/$(basename -- "$NODE_BIN")"
NODE_MAGIC=$(
  /bin/dd if="$NODE_BIN" bs=1 count=4 2>/dev/null |
    /usr/bin/od -An -tx1 |
    /usr/bin/tr -d ' \n'
)
case "$NODE_MAGIC" in
  7f454c46|feedface|cefaedfe|feedfacf|cffaedfe|4d5a*) ;;
  *)
    echo "release build launcher requires a native Node executable" >&2
    exit 1
    ;;
esac

exec /usr/bin/env -i \
  PATH="$NODE_DIR:/usr/bin:/bin" \
  LANG=C \
  LC_ALL=C \
  TZ=UTC \
  SOURCE_DATE_EPOCH=0 \
  NODE_ENV=production \
  WIKI_COCKPIT_RELEASE_BUILD_INTERNAL=1 \
  "$NODE_BIN" "$SCRIPT_DIR/build-production.mjs"
