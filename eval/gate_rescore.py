"""
**기준선을 바꾸면 통과율이 어떻게 되나.**

지금 게이트는 이슈가 하나라도 있으면 차감을 막는다. 그런데 이슈에는 두
종류가 섞여 있다.

  안내  — "조표를 못 읽어 C장조로 추정했습니다", "박자표를 추정했습니다".
         우리가 악보를 **다시 그려 줬고**, 다만 한 항목을 짐작했으니
         봐 달라는 말이다. 사용자는 화면에서 키를 직접 고를 수 있다.
  실패  — rebuild.js 가 "이 단을 다시 그릴 수 없다"고 한 것. 상품이 안 나왔다.

돈은 **상품이 나왔는가**로 받아야 한다. 안내가 과금을 막으면, 조표가 없는
악보는 아무리 잘 읽어도 영원히 무료다.
"""
import sys, json, collections

ADVISORY = (                      # 결과는 나왔고 한 항목을 짐작했다는 안내
    "추정했습니다",               # 조표·박자표 추정
    "원조성을 확인하지 못했습니다",
    "곡 중간에 조표가 바뀌는",
)
SOFT = (                          # 결과는 나왔지만 일부가 빈다
    "코드", "붙임줄",
)

def bucket(kind: str) -> str:
    if any(k in kind for k in ADVISORY):
        return "안내"
    if any(k in kind for k in SOFT):
        return "부분"
    return "실패"

rows = json.load(open(sys.argv[1] if len(sys.argv) > 1 else "eval/gate_tally.json"))
n = len(rows)

def rate(keep) -> tuple[int, list]:
    hit = [r for r in rows if not [k for k in r["kinds"] if bucket(k) in keep]]
    return len(hit), hit

cur, _ = rate({"안내", "부분", "실패"})
noadv, _ = rate({"부분", "실패"})
hard, hard_rows = rate({"실패"})

print(f"악보 {n}장\n")
print(f"  ① 지금 기준 (이슈 0개)                 {cur:3}장  {cur/n:5.0%}")
print(f"  ② 안내를 빼면                          {noadv:3}장  {noadv/n:5.0%}")
print(f"  ③ 안내·부분을 빼면 (= 다시 그려졌나)   {hard:3}장  {hard/n:5.0%}")

buckets = collections.Counter()
by_kind = collections.Counter()
pages = collections.Counter()
for r in rows:
    for k in r["kinds"]:
        buckets[bucket(k)] += 1
        by_kind[(bucket(k), k)] += 1
    for k in set(r["kinds"]):
        pages[(bucket(k), k)] += 1

print(f"\n이슈 {sum(buckets.values())}건 — " +
      " · ".join(f"{b} {c}" for b, c in buckets.most_common()))
print("\n실패로 남는 사유 (건수 · 장 수)")
for (b, k), c in by_kind.most_common(40):
    if b == "실패":
        print(f"  {c:5}  {pages[(b,k)]:3}장  {k}")
print("\n안내·부분으로 빠지는 사유")
for (b, k), c in by_kind.most_common(40):
    if b != "실패":
        print(f"  {c:5}  {pages[(b,k)]:3}장  [{b}] {k}")
