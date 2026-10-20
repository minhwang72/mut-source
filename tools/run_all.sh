#!/bin/bash
# 새 악보 하나를 **끝까지** 관통시킨다. 사람이 볼 결과와 검산까지 낸다.
#
#   tools/run_all.sh <악보이미지> <반음수> [출력폴더]
#
# 왜 스크립트인가: 단계가 여섯 개(코드 판독 → 개수 판독 → 재조립 → 렌더 →
# 배관 감사 → 박자 검산)라 손으로 하면 순서를 틀린다. 특히 **개수 판독이
# 검출기보다 먼저** 와야 한다 — 단별 음표·쉼표 수를 알아야 점수가 낮은
# 기호(속 빈 머리·2분쉼표)를 개수만큼 받을 수 있다.
set -e
IMG="$1"; SEMI="${2:-0}"; OUT="${3:-out/run}"
[ -z "$IMG" ] && { echo "사용법: tools/run_all.sh <악보> <반음수> [출력폴더]"; exit 1; }
: "${MUTE_PY:=python3}"        # verovio·cairosvg 있는 파이썬
: "${MUTE_DETECT_PYTHON:=python3}"   # ultralytics 있는 파이썬
: "${MUTE_MODEL:=models/omr.pt}"
# 붙임줄(곡선)만 읽는 모델. 구조 모델과 나누는 이유는
# tools/detstruct.py detect_curves 주석에 있다. 없으면 붙임줄만 빈다.
: "${MUTE_TIE_MODEL:=models/omr_tie.pt}"
mkdir -p "$OUT"
BASE=$(basename "${IMG%.*}")

# Evaluation must never turn a missing cache into an unexpected paid read.
# Use MUTE_OFFLINE=1 with saved structural inputs, or offline_capture/replay.
if [ "${MUTE_OFFLINE:-0}" = "1" ]; then
  for CACHE in "$OUT/$BASE.ex.json" "$OUT/$BASE.struct.json"; do
    [ -s "$CACHE" ] || { echo "✗ 오프라인 판독 캐시 없음: $CACHE (API 호출하지 않음)"; exit 1; }
  done
fi

# **필요한 환경을 미리 확인한다.** 없으면 조용히 물러나 원조성을 코드 통계로만
# 추정하거나(조표를 못 셈) 렌더가 죽는다 — 결과를 다 만든 뒤에 알면 늦다.
"$MUTE_DETECT_PYTHON" -c "import ultralytics" 2>/dev/null || {
  echo "✗ MUTE_DETECT_PYTHON 에 ultralytics 가 없습니다: $MUTE_DETECT_PYTHON"
  echo "  조표를 못 세면 원조성이 틀릴 수 있습니다 (실측: Bb ↔ F)"
  exit 1
}
"$MUTE_PY" -c "import verovio, cairosvg" 2>/dev/null || {
  echo "✗ MUTE_PY 에 verovio·cairosvg 가 없습니다: $MUTE_PY"
  exit 1
}
[ -f "$MUTE_MODEL" ] || { echo "✗ 검출기가 없습니다: $MUTE_MODEL"; exit 1; }

echo "① 코드 판독"
# 이미 있으면 재사용한다 — LLM 호출을 아낀다
if [ ! -s "$OUT/$BASE.ex.json" ]; then
  python3 tools/detect_chords.py "$IMG" --json "$OUT/$BASE.detect.json" >/dev/null
  # **검출기가 있는 파이썬으로 돌린다.** 원조성을 조표에서 세려면 검출기가
  # 필요한데, 없으면 조용히 코드 통계로만 추정한다 — 그건 갈릴 수 있다
  # (실측: 위싱 콘티의 `Bb C F Gm F/A`를 Bb키로 봤으나 실제는 F키).
  "$MUTE_DETECT_PYTHON" tools/read_chords.py "$IMG" \
    "$OUT/$BASE.detect.json" -o "$OUT/$BASE.ex.json" \
    --model-path "$MUTE_MODEL"
else
  echo "  이미 있음 — 재사용"
fi

# **구조는 검출기가 읽는다. LLM에는 개수만 묻는다.**
# 실측(마커스): 구조 판독 출력 33,536토큰 → 개수 판독 4,768토큰. 결과는 동일
# (마디 수 9단 전부 일치 · 박자 37정확 · 배관 132/132). 근거는 detstruct 첫머리.
# MUTE_LLM_STRUCT=1 을 주면 옛 경로(LLM 구조 판독)로 돌아간다.
if [ "${MUTE_LLM_STRUCT:-0}" = "1" ]; then
  echo "② 구조 판독 (LLM · 음가·마디·쉼표)"
  if [ ! -s "$OUT/$BASE.struct.json" ]; then
    "$MUTE_DETECT_PYTHON" tools/readstruct.py "$IMG" \
      -o "$OUT/$BASE.struct.json" >/dev/null
  else
    echo "  이미 있음 — 재사용"
  fi
  DET=""
else
  echo "② 개수 판독 (LLM · 단별 음표·쉼표 수만)"
  if [ ! -s "$OUT/$BASE.struct.json" ]; then
    "$MUTE_DETECT_PYTHON" tools/readcounts.py "$IMG" \
      -o "$OUT/$BASE.struct.json" --think >/dev/null
  else
    echo "  이미 있음 — 재사용"
  fi
  DET="--detector"
fi

echo "③ 재조립 (음가·마디는 검출기, 박자로 역산)"
"$MUTE_DETECT_PYTHON" tools/rebuild.py "$IMG" "$OUT/$BASE.struct.json" \
  "$OUT/$BASE.ex.json" -s "$SEMI" -o "$OUT/$BASE.musicxml" \
  --model "$MUTE_MODEL" $DET --tie-model "$MUTE_TIE_MODEL" \
  --dump-struct "$OUT/$BASE.det.json"

echo "④ 한 페이지로 그리기"
# **가사를 출력 음표 자리로 옮기려면 원본 음표 x 가 필요하다**(--heads).
# 없으면 원본 x 를 비율 변환한 자리에 두는데, Verovio 가 간격을 다시 잡으므로
# 음표와 어긋난다(실측: 4장에서 중앙 1.5~4.1칸, 최대 10.2칸).
"$MUTE_PY" tools/renderpage.py "$OUT/$BASE.musicxml" "$IMG" \
  -o "$OUT/$BASE.png" --chords "$OUT/$BASE.ex.json" \
  --heads "$OUT/$BASE.det.json"

echo "⑤ 음높이 배관 감사 (키 안 바꾼 판으로)"
# 감사에는 **검출기가 읽은 구조**가 필요하다 — 개수 파일에는 음가가 없다
"$MUTE_DETECT_PYTHON" tools/rebuild.py "$IMG" "$OUT/$BASE.struct.json" \
  "$OUT/$BASE.ex.json" -s 0 -o "$OUT/$BASE.audit.musicxml" \
  --model "$MUTE_MODEL" $DET --tie-model "$MUTE_TIE_MODEL" \
  --dump-struct "$OUT/$BASE.det.json" \
  2>&1 | grep -E "단 ·|음높이" || true
AUDIT_STRUCT="$OUT/$BASE.struct.json"
[ -s "$OUT/$BASE.det.json" ] && AUDIT_STRUCT="$OUT/$BASE.det.json"
"$MUTE_DETECT_PYTHON" tools/auditpitch.py "$IMG" "$OUT/$BASE.audit.musicxml" \
  --model "$MUTE_MODEL" --struct "$AUDIT_STRUCT" || true

echo "⑥ 박자 검산 (검출기가 읽은 구조로)"
python3 tools/checkbeats.py "$AUDIT_STRUCT" || true

echo "완료 → $OUT/$BASE.png"
