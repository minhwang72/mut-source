"""IP 제한이 실제로 판독을 막는가. 비용이 나는 건 판독이라 여기가 새면 끝이다."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jobs

store = jobs.JobStore(lambda blob, opts, progress=None: {"ok": True},
                      trial_balance=5, ip_hourly=3, workers=1,
                      # 동시 작업 한도(max_active)도 Busy 를 낸다 — 그게 아니라
                      # IP 제한이 걸리는지 보려면 이쪽을 넉넉히 열어야 한다
                      max_active=64, max_queue=64)
try:
    sid = store.new_session()
    ok = 0
    for i in range(10):
        try:
            # 그림이 매번 달라야 캐시 재사용에 걸리지 않는다
            store.submit(sid, f"img{i}".encode(), {"mode": "ai"}, ip="1.2.3.4")
            ok += 1
        except jobs.Busy:
            break
    assert ok == 3, f"IP 제한이 안 걸렸다 (통과 {ok}개)"

    # 쿠키를 지워 새 세션을 만들어도 같은 IP면 막혀야 한다
    sid2 = store.new_session()
    try:
        store.submit(sid2, b"another", {"mode": "ai"}, ip="1.2.3.4")
        raise AssertionError("세션만 바꾸면 뚫린다")
    except jobs.Busy:
        pass

    # 다른 IP는 따로 센다
    store.submit(store.new_session(), b"other", {"mode": "ai"}, ip="5.6.7.8")

    # 같은 그림 재요청은 캐시라 한도를 안 먹는다
    before = len(store._ip_hits["5.6.7.8"])
    store.submit(sid, b"img0", {"mode": "ai"}, ip="1.2.3.4")
    assert len(store._ip_hits["1.2.3.4"]) == 3, "캐시 재사용이 한도를 먹었다"
    print("ok")
finally:
    store.stop()
