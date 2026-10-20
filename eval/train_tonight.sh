#!/bin/bash
# 밤에 돌릴 재학습 — 사람 표시(구역 글자·형광펜·손글씨) 음성 표본 포함.
# 합성은 이미 data/synth 에 6000장 준비돼 있어 학습만 한다.
#
#   cd /Users/hwangmin/development/pj/min/mut && nohup eval/train_tonight.sh > eval/train_tonight.log 2>&1 &
#
# 중단되면:  tools/train.py --data data/synth --epochs 16 --name omr_marks --resume
# 끝나면 검증:  eval/auto_rate.py --repair (캐시된 8장, API 0원)
set -e
cd /Users/hwangmin/development/pj/min/mut
V=/Users/hwangmin/Documents/Codex/2026-09-14/new-chat/work/mute-venv/bin/python
export YOLO_CONFIG_DIR=/private/tmp/claude-501/-Users-hwangmin-Desktop/068aa7a5-522c-41c4-8df3-eb7475a40ab2/scratchpad
echo "=== 학습 시작 $(date +%H:%M) ==="
rm -rf runs/detect/runs/omr_marks          # 3에폭짜리 찌꺼기를 지우고 처음부터
$V tools/train.py --data data/synth --epochs 16 --name omr_marks 2>&1 | grep -E '^ *all|^ *notehead' | tail -40
echo "=== 학습 끝 $(date +%H:%M) ==="
echo "=== 검증: 옛 모델 vs 새 모델 ==="
$V eval/cmp_models.py 2>&1 | tail -12
