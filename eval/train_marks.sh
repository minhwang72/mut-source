#!/bin/bash
# 사람 표시(구역 글자·형광펜·손글씨)를 넣은 합성으로 재학습.
# 중단되면: tools/train.py --name omr_marks --resume
set -e
cd /Users/hwangmin/development/pj/min/mut
V=/Users/hwangmin/Documents/Codex/2026-09-14/new-chat/work/mute-venv/bin/python
export YOLO_CONFIG_DIR=/private/tmp/claude-501/-Users-hwangmin-Desktop/068aa7a5-522c-41c4-8df3-eb7475a40ab2/scratchpad
echo "=== ① 합성 $(date +%H:%M) ==="
$V tools/gendata.py -n 6000 -o data/synth --seed 777 2>&1 | tail -4
echo "=== ② 학습 $(date +%H:%M) ==="
$V tools/train.py --data data/synth --epochs 16 --name omr_marks 2>&1 | grep -E '^ *all|Epoch|it\]' | tail -60
echo "=== 종료 $(date +%H:%M) ==="
