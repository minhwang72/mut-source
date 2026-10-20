"""
**음가 합이 얼마나 어긋났나.**

797건이 1위 차단 사유인데, "안 맞는다"만으로는 고칠 곳을 못 정한다.
  · 0.5박 부족  = 음가를 한 단계 잘못 읽었다(점·꼬리) → 음가 판독 문제
  · 정수 박 부족 = 음표가 통째로 빠졌다              → 검출 문제
  · 초과        = 없는 음표를 만들었거나 마디선을 놓쳤다
셋은 고치는 자리가 완전히 다르다. 섞어 세면 방향을 못 정한다.
"""
import json, re, sys, collections

rows = json.load(open(sys.argv[1] if len(sys.argv) > 1 else "eval/gate_tally.json"))
PAT = re.compile(r"음가 합 ([\d.]+)박 — 기준 ([\d.]+)박")

devs, per_page = [], collections.Counter()
for r in rows:
    for m in r.get("raw", []):
        hit = PAT.search(m)
        if not hit:
            continue
        got, want = float(hit.group(1)), float(hit.group(2))
        devs.append((round(got - want, 3), want, r["page"]))
        per_page[r["page"]] += 1

if not devs:
    sys.exit("음가 합 사유가 없다 — raw 가 비었는지 확인")

short = [d for d, *_ in devs if d < 0]
over = [d for d, *_ in devs if d > 0]
print(f"음가 합 불일치 {len(devs)}건 · {len(per_page)}장 (장당 {len(devs)/len(per_page):.1f})")
print(f"  모자람 {len(short)} ({len(short)/len(devs):.0%})  ·  넘침 {len(over)} ({len(over)/len(devs):.0%})\n")

print("편차별 (박)")
c = collections.Counter(d for d, *_ in devs)
cum = 0
for d, n in sorted(c.items(), key=lambda kv: -kv[1])[:14]:
    cum += n
    tag = ("음가 한 단계" if abs(d) in (0.5, 0.25, 1.5)
           else "음표 통째" if float(d).is_integer() else "")
    print(f"  {d:+7.3f}  {n:4}건 {n/len(devs):5.0%}  누적 {cum/len(devs):4.0%}  {tag}")

print("\n기준 박자별")
for want, n in collections.Counter(w for _d, w, _p in devs).most_common():
    print(f"  기준 {want:g}박  {n:4}건")

half = sum(n for d, n in c.items() if abs(d) in (0.5, 0.25, 1.5, 0.75))
whole = sum(n for d, n in c.items() if float(d).is_integer())
print(f"\n음가 한 단계 차이 {half}건 ({half/len(devs):.0%}) · "
      f"정수 박 차이 {whole}건 ({whole/len(devs):.0%})")
print("\n많이 걸린 장")
for p, n in per_page.most_common(8):
    print(f"  {n:4}건  {p}")
