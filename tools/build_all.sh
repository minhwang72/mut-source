#!/bin/bash
# 데모 빌드 전체 — 샘플 악보 생성부터 Artifact용 HTML까지
set -e
cd "$(dirname "$0")/.."
OUT=${1:-dist}
mkdir -p "$OUT"

echo "① 브라우저 엔진 빌드"
node tools/build_web.mjs

echo "② 샘플 악보 생성 (저작권 없는 합성 악보)"
python3 tools/make_test_sheet.py -o "$OUT/sample.png" \
  --extraction "$OUT/sample-truth.json" --spacing 16 --systems 8 --width 1120

echo "③ 판독 결과 + 기하 정보 굽기"
python3 tools/build_demo.py "$OUT/sample.png" "$OUT/sample-truth.json" \
  -o "$OUT/demo-data.json"

echo "④ 번들"
node tools/bundle_demo.mjs "$OUT/demo-data.json" "$OUT/demo.html"
node tools/bundle_demo.mjs "$OUT/demo-data.json" "$OUT/artifact.html" --artifact

echo "⑤ 저해상도(웹 다운로드급) 검증용 데모 — 오선 7px, JPEG"
python3 tools/downscale_fixture.py "$OUT/sample.png" "$OUT/sample-truth.json" \
  --scale 0.42 -o "$OUT/lowres.jpg" --truth-out "$OUT/lowres-truth.json"
python3 tools/build_demo.py "$OUT/lowres.jpg" "$OUT/lowres-truth.json" \
  -o "$OUT/lowres-data.json"
node tools/bundle_demo.mjs "$OUT/lowres-data.json" "$OUT/lowres.html"

echo
echo "완료:"
echo "  $OUT/demo.html      — 로컬·정적호스팅용 (완전한 HTML)"
echo "  $OUT/artifact.html  — Artifact 발행용 (래퍼 태그 없음)"
echo "  $OUT/lowres.html    — 저해상도 검증용 (사용자가 실제로 올리는 조건)"
