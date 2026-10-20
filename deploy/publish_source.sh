#!/bin/zsh
# **공개 소스를 운영 버전에 맞춘다** — AGPL-3.0 은 돌아가는 버전의 소스를 요구한다.
# 배포할 때마다 돌린다: main HEAD 에서 상업 악보 유래 자료를 빼고 비밀값을 검사한 뒤
# github.com/minhwang72/mut-source 에 한 커밋으로 올린다(이 저장소의 기록은 싣지 않는다).
set -e
cd "$(dirname "$0")/.."
REV=$(git rev-parse --short HEAD)
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
git clone -q https://github.com/minhwang72/mut-source.git "$TMP/pub"
cd "$TMP/pub" && git rm -rq . >/dev/null && cd - >/dev/null
git archive HEAD | tar -x -C "$TMP/pub"
cd "$TMP/pub"
# 저작권·내부 정보 — 공개본에서 뺀다
rm -rf test/fixtures tools/score_benchmark.mjs live eval/fetch_and_compare.* \
       tools/train_shared.sh tools/train_mac.sh CLAUDE.md
find eval -type f ! -name "*.py" ! -name "*.sh" -delete
find eval -type d -empty -delete
# 공개본 안내는 이전 공개본의 README 머리말을 그대로 쓴다
git show HEAD:README.md | sed -n '1,/^$/p' > /tmp/mut_pub_head.md
cat /tmp/mut_pub_head.md README.md > README.new && mv README.new README.md
if grep -rIlE --exclude=publish_source.sh "sk-ant-[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16}|BEGIN [A-Z ]*PRIVATE KEY|ghp_[A-Za-z0-9]{20,}|010-[0-9]{4}-[0-9]{4}|copyright \(c\) 1995|cocoa" . ; then
  echo "✗ 공개하면 안 되는 내용이 있다 — 위 파일을 확인하라"; exit 1
fi
git add -A
git diff --cached --quiet && { echo "공개본 변경 없음"; exit 0; }
git -c user.name=minhwang72 -c user.email=minhwang72@users.noreply.github.com \
    commit -q -m "운영 버전 ${REV} 에 맞춤"
git push -q origin main
echo "공개본 갱신: ${REV}"
