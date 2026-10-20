#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
MUTE_PYTHON="${MUTE_PYTHON:-python3}"
if ! "$MUTE_PYTHON" -c 'import PIL, numpy, ultralytics' >/dev/null 2>&1; then
  echo '로컬 판독 의존성이 필요합니다. 설치된 Python 환경을 MUTE_PYTHON으로 지정해 주세요.' >&2
  exit 1
fi
command -v node >/dev/null || { echo 'Node.js가 필요합니다.' >&2; exit 1; }
export YOLO_OFFLINE=true
export YOLO_AUTOINSTALL=false
# Model changes are explicit. The original model remains the default until
# broader held-out evaluation establishes the candidate's page-level quality.
exec "$MUTE_PYTHON" server/serve.py --mode local --port "${MUTE_PORT:-8200}"
