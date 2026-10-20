"""
**개수 불일치 — LLM 과 검출기 중 누가 틀렸나.**

detstruct 는 단마다 "LLM 이 센 음표 수"와 "검출기가 찾은 수"를 견준다.
다르면 차단한다. 그런데 **누가 틀렸는지는 안 본다.** 검출기가 맞는데
LLM 이 잘못 셌다면 멀쩡한 판독을 막는 것이고, 반대면 진짜 오류다.

독립 심판은 박자다. 검출기가 읽은 대로 마디 합이 맞으면 검출기가
맞을 가능성이 크고, 합이 모자라면 정말 음표를 놓친 것이다.

  검출 < LLM 이고 그 단의 합이 모자람  → 검출이 놓쳤다 (LLM 이 맞다)
  검출 < LLM 인데 합은 정확            → LLM 이 더 셌다 (검출이 맞다)
  검출 > LLM 이고 합이 넘침            → 검출이 더 찾았다
  검출 > LLM 인데 합은 정확            → LLM 이 덜 셌다

LLM 캐시를 쓰므로 돈이 들지 않는다.
"""
import os, sys, json, hashlib, warnings, collections
sys.path.insert(0, "tools"); sys.path.insert(0, "server")
warnings.filterwarnings("ignore")
sys.argv = [sys.argv[0]]                        # ai_tally 의 인자 파싱을 피한다
import importlib.util
spec = importlib.util.spec_from_file_location("ai_tally", "eval/ai_tally.py")

# ai_tally 의 캐시 설치만 빌려 쓴다 (실행은 안 한다)
exec(open("eval/ai_tally.py").read().split("calls = install_cache()")[0])
calls = install_cache()
import serve

DUR = {"whole": 32, "half": 16, "quarter": 8, "eighth": 4, "16th": 2}
PAGES = sorted(f"악보샘플/이미지/{f}" for f in os.listdir("악보샘플/이미지")
               if f.endswith(".png"))
step = max(1, len(PAGES) // 25)
PAGES = PAGES[::step][:25]

serve.STATE["mode"] = "ai"
tag = collections.Counter()
gaps = collections.Counter()
rows = []
for p in PAGES:
    name = os.path.basename(p)[:-4]
    try:
        ex = serve.read_sheet(open(p, "rb").read(), None)
    except Exception as e:                       # noqa: BLE001
        print(f"{name:18} 오류 {type(e).__name__}", flush=True)
        continue
    st = ex.get("struct") or {}
    full = int(round(float(st.get("beats") or 4) * 8))
    for s in (st.get("systems") or []):
        msgs = [m for m in (s.get("review") or []) if "불일치" in m]
        if not msgs:
            continue
        import re
        m = re.search(r"판독 (\d+)개와 검출 (\d+)개", msgs[0])
        if not m:
            continue
        want, got = int(m.group(1)), int(m.group(2))
        per = collections.defaultdict(int)
        for n in (s.get("notes") or []):
            if n.get("chord"):
                continue
            v = DUR.get(n.get("duration"), 0)
            per[n.get("measure")] += v * 3 // 2 if n.get("dotted") else v
        bad = sum(1 for v in per.values() if v != full)
        short = sum(1 for v in per.values() if v < full)
        over = sum(1 for v in per.values() if v > full)
        d = got - want
        gaps[d] += 1
        if d < 0:
            tag["검출이 적음 · 합도 모자람 → 검출이 놓침" if short
                else "검출이 적음 · 합은 정확 → LLM 이 더 셌다"] += 1
        else:
            tag["검출이 많음 · 합도 넘침 → 검출이 더 찾음" if over
                else "검출이 많음 · 합은 정확 → LLM 이 덜 셌다"] += 1
        rows.append({"page": name, "sys": s.get("system"), "want": want,
                     "got": got, "bad": bad, "measures": len(per)})
    print(f"{name:18} 불일치 단 {sum(1 for r in rows if r['page']==name)}", flush=True)

n = max(1, sum(tag.values()))
print(f"\n== 개수 불일치가 난 단 {n}개\n")
for k, v in tag.most_common():
    print(f"  {v:4}  {v/n:5.0%}  {k}")
print("\n차이(검출 − LLM) 분포")
for d, v in sorted(gaps.items(), key=lambda t: -t[1])[:10]:
    print(f"  {v:4}  {d:+3}")
json.dump(rows, open("eval/count_gap.json", "w"), ensure_ascii=False, indent=1)
