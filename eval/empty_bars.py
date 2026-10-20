"""
**음표가 하나도 없는 마디는 어디서 생기나.**

rebuild.js 는 마디에 음표도 쉼표도 없으면 "읽은 음표·쉼표가 없어 원본
확인 필요"로 차단한다. ai 경로 25장에서 15건/10장이다.

두 가지가 섞여 있을 수 있다.
  · 줄막대를 헛검출했다 — 없는 경계가 생겨 빈 칸이 끼어든다. 음표가
    옮겨 간 게 아니므로 이웃 마디의 합은 멀쩡하다
  · 온쉼표 한 개짜리 마디를 못 읽었다 — 그 자리에 잉크가 있다

가르는 법은 화소다. 그 마디 자리에 잉크가 있으면 뭔가를 놓친 것이고,
비어 있으면 줄막대가 헛것이다. LLM 캐시를 쓰므로 돈이 들지 않는다.
"""
import os, sys, warnings, collections
sys.path.insert(0, "tools"); sys.path.insert(0, "server")
warnings.filterwarnings("ignore")
exec(open("eval/ai_tally.py").read().split("calls = install_cache()")[0])
install_cache()
import numpy as np
import serve

PAGES = sorted(f"악보샘플/이미지/{f}" for f in os.listdir("악보샘플/이미지")
               if f.endswith(".png"))
PAGES = PAGES[::max(1, len(PAGES) // 25)][:25]
serve.STATE["mode"] = "ai"

where = collections.Counter()
ink_tag = collections.Counter()
rows = []
for p in PAGES:
    name = os.path.basename(p)[:-4]
    try:
        ex = serve.read_sheet(open(p, "rb").read(), None)
    except Exception:                            # noqa: BLE001
        continue
    st = ex.get("struct") or {}
    geo = ex.get("geometry") or {}
    gsys = geo.get("systems") or []
    for si, s in enumerate(st.get("systems") or []):
        per = collections.defaultdict(list)
        for n in (s.get("notes") or []):
            per[n.get("measure")].append(n)
        # **마디 번호는 1 부터다.** 0 부터로 세면 모든 단의 첫 칸이 비어
        # 보여서, 빈 마디가 실제의 몇 배로 부풀어 나온다(실측으로 당했다).
        total = s.get("measures") or (max(per) if per else 0)
        for mi in range(1, total + 1):
            if per.get(mi):
                continue
            where["단의 첫 마디" if mi == 1 else
                  "단의 끝 마디" if mi == total else "단 가운데"] += 1
            # 그 마디 자리에 잉크가 있나 — 줄막대 좌표가 있어야 잰다
            bars = (gsys[si] or {}).get("barlines") if si < len(gsys) else None
            rows.append({"page": name, "sys": si, "measure": mi,
                         "of": total, "bars": len(bars or [])})
print(f"빈 마디 {sum(where.values())}개\n")
for k, v in where.most_common():
    print(f"  {v:4}  {v/max(1,sum(where.values())):5.0%}  {k}")
print("\n장별")
c = collections.Counter(r["page"] for r in rows)
for k, v in c.most_common(10):
    print(f"  {v:3}  {k}")
print("\n예시 (단, 마디/전체, 그 단의 줄막대 수)")
for r in rows[:10]:
    print(f"  {r['page']:16} 단{r['sys']+1} 마디{r['measure']}/{r['of']} "
          f"· 줄막대 {r['bars']}")
