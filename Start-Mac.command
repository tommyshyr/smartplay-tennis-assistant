#!/bin/sh
cd "$(dirname "$0")" || exit 1
if ! command -v python3 >/dev/null 2>&1; then
  echo '请安装 Python 3.11 或更新版本。https://www.python.org/downloads/'
  exit 1
fi
exec python3 launch.py
