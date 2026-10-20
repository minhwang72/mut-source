"""
**왜 전부 환불되는가.** 게이트는 이슈가 0개일 때만 통과를 준다. 실사용
35건이 전부 환불됐으니, 무엇이 걸리는지 종류별로 세어야 어디를 고칠지
고를 수 있다.

**경로를 손으로 재현하지 않는다.** 서버가 실제로 부르는 read_sheet_local()
을 그대로 부른다. 앞서 두 번, 직접 조립한 하네스가 1위 사유를 통째로
가짜로 만들었다 — sourceFifths 를 안 채워서 "원조표 미확정" 734건,
오선 좌표 없는 geometry 를 넘겨서 "음표 위치를 확인할 수 없습니다" 715건.
둘 다 실제 경로에는 없는 사유였다. 재현한 경로는 실제 경로가 아니다.

이 함수는 LLM 을 부르지 않는다(코드 판독까지 로컬). 돈이 들지 않는다.
"""
import sys, os, json, warnings, collections
sys.path.insert(0, "tools"); sys.path.insert(0, "server")
warnings.filterwarnings("ignore")
import local_reader as LR
import db as DB

PAGES = sorted(sys.argv[1:] or
               [f"악보샘플/이미지/{f}" for f in os.listdir("악보샘플/이미지")
                if f.endswith(".png")])

kinds, per_page, errs = collections.Counter(), [], 0
for p in PAGES:
    name = os.path.basename(p).rsplit(".", 1)[0]
    try:
        ex = LR.read_sheet_local(open(p, "rb").read())
        # **구조를 캐시한다.** 매번 25분씩 다시 읽으면 가설 하나 확인할
        # 때마다 반나절이 간다. 한 번 읽어 두면 이후 분석은 산술이다.
        os.makedirs("eval/structs", exist_ok=True)
        json.dump(ex.get("struct") or {},
                  open(f"eval/structs/{name}.json", "w"), ensure_ascii=False)
        g = ex["qualityGate"]
        ks = [DB.issue_kind(m) for m in g["issues"]]
        kinds.update(ks)
        st = ex.get("struct") or {}
        per_page.append({"page": name, "gate": g["status"],
                         "n": len(g["issues"]), "kinds": ks,
                         # **원문도 남긴다.** 숫자를 지운 열쇠로는 "얼마나
                         # 어긋났나"를 못 본다. 0.5박 차이와 한 마디를 통째로
                         # 잃은 것은 고칠 곳이 다르다.
                         "raw": list(g.get("blocking") or g["issues"]),
                         "beats": (st or {}).get("beats"),
                         "timeSignature": (st or {}).get("timeSignature"),
                         "systems": len(st.get("systems") or []),
                         "twoVoice": g.get("twoVoice")})
        print(f"{name:18} {g['status']:13} 이슈 {len(g['issues']):3}", flush=True)
    except Exception as e:
        errs += 1
        print(f"{name:18} 오류 {type(e).__name__}: {str(e)[:70]}", flush=True)

ok = sum(1 for r in per_page if r["n"] == 0)
n = max(1, len(per_page))
print(f"\n== {len(per_page)}장 (오류 {errs})")
print(f"이슈 0개(= 지금 기준 통과): {ok}장 ({ok / n:.0%})")
ns = sorted(r["n"] for r in per_page)
print(f"장당 이슈  중앙값 {ns[len(ns)//2] if ns else 0} · "
      f"1개 이하 {sum(1 for v in ns if v <= 1)}장 · "
      f"3개 이하 {sum(1 for v in ns if v <= 3)}장 · "
      f"5개 이하 {sum(1 for v in ns if v <= 5)}장")
print("\n사유별 (건수 · 이 사유가 뜬 장 수)")
pages_with = collections.Counter()
for r in per_page:
    for k in set(r["kinds"]):
        pages_with[k] += 1
for k, c in kinds.most_common(20):
    print(f"  {c:5}  {pages_with[k]:3}장  {k}")
json.dump(per_page, open("eval/gate_tally.json", "w"), ensure_ascii=False, indent=1)
