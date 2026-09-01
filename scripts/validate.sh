#!/bin/bash
set -euo pipefail

plugin_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
omarchy_path="${OMARCHY_PATH:-/usr/share/omarchy}"
qmllint_bin="$(command -v qmllint || true)"
if [[ -z "$qmllint_bin" && -x /usr/lib/qt6/bin/qmllint ]]; then
  qmllint_bin=/usr/lib/qt6/bin/qmllint
fi

cd "$plugin_dir"
omarchy plugin validate .

if [[ -z "$qmllint_bin" ]]; then
  echo "qmllint is not installed; skipping QML lint" >&2
else
  for file in ./*.qml; do
    "$qmllint_bin" -I "$omarchy_path/shell" "$file"
  done
fi

python3 -m py_compile bin/omajelly
python3 -m unittest discover -s tests -p 'test_*.py'
node --test tests/model.test.mjs

if command -v luac >/dev/null 2>&1; then
  luac -p assets/omajelly_subtitles.lua
fi
