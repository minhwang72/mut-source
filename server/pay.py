"""
**토스페이먼츠 결제 — 주문 만들기 · 승인 · 크레딧 지급.**

흐름(결제창형, SDK v2):
  1. 브라우저가 /api/pay/order 로 상품만 알려 준다 → 서버가 **값을 정해** 주문을 'ready' 로 남긴다.
     금액은 절대 브라우저 값을 믿지 않는다.
  2. 토스 결제창 → 성공하면 /pay/success?paymentKey&orderId&amount 로 돌아온다.
  3. 서버가 주문 금액과 대조한 뒤 토스 승인 API 를 부르고, DONE 이면 크레딧을 준다.
     'ready' → 'paid' 조건부 UPDATE 가 한 번만 성공하므로 새로고침·중복 호출에도 한 번만 지급된다.

키는 환경변수로만 들어온다(TOSS_CLIENT_KEY · TOSS_SECRET_KEY). 심사 전에는 토스
문서의 테스트 키로 돈이 나가지 않는 결제창을 띄운다.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import urllib.error
import urllib.request

import db

# web/app.js 의 PACKS · UNIT_WON 과 같아야 한다 — 금액의 원본은 여기다
PACKS = {"p10": (10, 5000), "p50": (50, 20000), "p200": (200, 60000)}
UNIT_WON = 500
MAX_BUY = 999
CONFIRM_URL = "https://api.tosspayments.com/v1/payments/confirm"


def configured() -> bool:
    return bool(os.environ.get("TOSS_CLIENT_KEY") and os.environ.get("TOSS_SECRET_KEY"))


def quote(pack: str) -> tuple[int, int] | None:
    """상품 id → (크레딧, 금액). 'p50' 같은 묶음이거나 'c7' 같은 낱개."""
    if pack in PACKS:
        return PACKS[pack]
    if pack.startswith("c") and pack[1:].isdigit():
        n = int(pack[1:])
        if 1 <= n <= MAX_BUY:
            return n, n * UNIT_WON
    return None


def customer_key(uid: str) -> str:
    """토스에 넘기는 구매자 키 — 회원번호를 그대로 보내지 않는다."""
    return "mut_" + hashlib.sha256(uid.encode()).hexdigest()[:40]


def create_order(uid: str, pack: str) -> dict | None:
    q = quote(pack)
    if q is None:
        return None
    credits, amount = q
    order_id = "mut_" + secrets.token_hex(12)
    db.run("INSERT INTO payment (order_id, user_id, pack, credits, amount, status) "
           "VALUES (%s, %s, %s, %s, %s, 'ready')", order_id, uid, pack, credits, amount)
    return {"orderId": order_id, "amount": amount, "credits": credits,
            "orderName": f"mut {credits}크레딧",
            "clientKey": os.environ.get("TOSS_CLIENT_KEY", ""),
            "customerKey": customer_key(uid)}


def _toss_confirm(payment_key: str, order_id: str, amount: int) -> tuple[int, dict]:
    auth = base64.b64encode((os.environ["TOSS_SECRET_KEY"] + ":").encode()).decode()
    req = urllib.request.Request(
        CONFIRM_URL, method="POST",
        data=json.dumps({"paymentKey": payment_key, "orderId": order_id,
                         "amount": amount}).encode(),
        headers={"Authorization": f"Basic {auth}", "Content-Type": "application/json",
                 "Idempotency-Key": order_id})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except Exception:                                   # noqa: BLE001
            return e.code, {}


def confirm(uid: str | None, payment_key: str, order_id: str, amount: str) -> tuple[bool, str]:
    """결제 승인. (성공, 사용자에게 보일 말)."""
    row = db.one("SELECT * FROM payment WHERE order_id = %s", order_id)
    if not row:
        return False, "주문을 찾을 수 없습니다."
    if uid and row["user_id"] != uid:
        return False, "다른 계정의 주문입니다."
    if row["status"] == "paid":
        return True, "이미 결제가 끝난 주문입니다."
    if row["status"] != "ready":
        return False, "처리할 수 없는 주문입니다."
    if not amount.isdigit() or int(amount) != int(row["amount"]):
        db.run("UPDATE payment SET status = 'failed' WHERE order_id = %s AND status = 'ready'",
               order_id)
        return False, "결제 금액이 주문과 다릅니다."
    code, body = _toss_confirm(payment_key, order_id, int(row["amount"]))
    if code != 200 or body.get("status") != "DONE":
        db.run("UPDATE payment SET status = 'failed' WHERE order_id = %s AND status = 'ready'",
               order_id)
        return False, body.get("message") or "결제를 승인하지 못했습니다."
    receipt = ((body.get("receipt") or {}).get("url") or "")[:512]
    if db.run("UPDATE payment SET status = 'paid', pg_key = %s, receipt = %s, paid_at = NOW() "
              "WHERE order_id = %s AND status = 'ready'",
              payment_key[:200], receipt, order_id) == 1:
        db.grant(row["user_id"], int(row["credits"]), order_id, "buy")
    return True, f"{row['credits']}크레딧이 충전됐습니다."


def fail(order_id: str) -> None:
    db.run("UPDATE payment SET status = 'canceled' WHERE order_id = %s AND status = 'ready'",
           order_id)


if __name__ == "__main__":
    assert quote("p50") == (50, 20000)
    assert quote("c7") == (7, 3500)
    assert quote("c0") is None and quote("c1000") is None and quote("p999") is None
    assert quote("cx") is None
    assert customer_key("local:a") == customer_key("local:a") != customer_key("local:b")
    print("ok")
