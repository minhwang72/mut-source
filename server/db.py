"""
**영속 저장소.** 판독 결과와 이미지는 여기 안 들어온다 — 그건 메모리에만
있다가 사라진다(설계). 여기 남는 건 사람과 돈이다: 회원, 세션, 크레딧,
결제. 서버가 다시 떠도 살아 있어야 하는 것들만 둔다.

연결이 없으면 **서버가 뜨지 않는다**. 조용히 메모리로 되돌아가면 결제한
크레딧이 재시작 때 사라지는데, 그건 돈 문제라 조용히 넘어갈 수 없다.
"""
from __future__ import annotations

import os
import threading
import time

_local = threading.local()

SCHEMA = """
CREATE TABLE IF NOT EXISTS user (
  id            VARCHAR(64)  NOT NULL PRIMARY KEY,
  name          VARCHAR(40)  NOT NULL DEFAULT '',
  image         VARCHAR(512) NOT NULL DEFAULT '',
  email         VARCHAR(254) NOT NULL DEFAULT '',
  label         VARCHAR(40)  NOT NULL DEFAULT '',
  pw_hash       VARCHAR(255) NOT NULL DEFAULT '',
  balance       INT          NOT NULL DEFAULT 0,
  agreed_at     DATETIME     NULL,
  created_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  last_login_at DATETIME     NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS session (
  sid        VARCHAR(64) NOT NULL PRIMARY KEY,
  user_id    VARCHAR(64) NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  seen_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY k_user (user_id), KEY k_seen (seen_at),
  CONSTRAINT fk_sess_user FOREIGN KEY (user_id) REFERENCES user(id)
    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- **지우지 않는다.** 크레딧이 왜 줄었는지 못 대면 분쟁에서 진다.
CREATE TABLE IF NOT EXISTS credit_log (
  id            BIGINT AUTO_INCREMENT PRIMARY KEY,
  user_id       VARCHAR(64) NOT NULL,
  delta         INT NOT NULL,
  reason        VARCHAR(32) NOT NULL,
  ref           VARCHAR(64) NOT NULL DEFAULT '',
  balance_after INT NOT NULL,
  at            DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY k_user_at (user_id, at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 전자상거래법 제6조: 대금 결제 기록은 5년 보존한다
CREATE TABLE IF NOT EXISTS payment (
  order_id    VARCHAR(64) NOT NULL PRIMARY KEY,
  user_id     VARCHAR(64) NOT NULL,
  pack        VARCHAR(16) NOT NULL,
  credits     INT NOT NULL,
  amount      INT NOT NULL,
  status      VARCHAR(16) NOT NULL,
  pg          VARCHAR(16) NOT NULL DEFAULT 'toss',
  pg_key      VARCHAR(200) NOT NULL DEFAULT '',
  receipt     VARCHAR(512) NOT NULL DEFAULT '',
  email       VARCHAR(254) NOT NULL DEFAULT '',
  created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  paid_at     DATETIME NULL,
  canceled_at DATETIME NULL,
  KEY k_user (user_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 무차별 대입 차단용. 성공하면 지운다.
CREATE TABLE IF NOT EXISTS login_fail (
  id  BIGINT AUTO_INCREMENT PRIMARY KEY,
  who VARCHAR(100) NOT NULL,
  at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY k_who_at (who, at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""


def configured() -> bool:
    return bool(os.environ.get("MUT_DB_HOST"))


def conn():
    """스레드마다 하나. 끊겼으면 다시 잇는다 — 서버는 오래 떠 있다."""
    # 드라이버는 여기서 불러온다. 이 모듈에는 DB 없이 쓰는 것(비밀번호
    # 해시)도 있어서, 위에서 부르면 드라이버 없는 곳에서 통째로 못 쓴다.
    import pymysql
    import pymysql.cursors
    c = getattr(_local, "c", None)
    if c is not None:
        try:
            c.ping(reconnect=True)
            return c
        except Exception:                        # noqa: BLE001
            try:
                c.close()
            except Exception:                    # noqa: BLE001
                pass
    c = pymysql.connect(
        host=os.environ.get("MUT_DB_HOST") or "127.0.0.1",
        port=int(os.environ.get("MUT_DB_PORT") or 3306),
        user=os.environ.get("MUT_DB_USER") or "mut",
        password=os.environ.get("MUT_DB_PASS") or "",
        database=os.environ.get("MUT_DB_NAME") or "mut",
        charset="utf8mb4", autocommit=True,
        cursorclass=pymysql.cursors.DictCursor,
        # 장부 시각은 한국시간으로 적는다 — 분쟁 때 사람이 바로 읽는 기록이다.
        # NOW()·CURRENT_TIMESTAMP 가 세션 시간대를 따르므로 연결마다 박는다.
        init_command="SET time_zone = '+09:00'",
    )
    _local.c = c
    return c


def setup(retries: int = 10) -> None:
    """스키마를 맞춘다. DB 컨테이너가 늦게 뜰 수 있어 잠깐 기다려 준다."""
    last = None
    for i in range(retries):
        try:
            with conn().cursor() as cur:
                for stmt in (SCHEMA + READ_SCHEMA).split(";"):
                    if stmt.strip():
                        cur.execute(stmt)
            return
        except Exception as e:                   # noqa: BLE001
            last = e
            time.sleep(min(2 ** i * 0.2, 3))
    raise RuntimeError(f"DB 를 준비하지 못했습니다: {type(last).__name__}")


def q(sql: str, *args) -> list[dict]:
    with conn().cursor() as cur:
        cur.execute(sql, args)
        return cur.fetchall()


def one(sql: str, *args) -> dict | None:
    r = q(sql, *args)
    return r[0] if r else None


def run(sql: str, *args) -> int:
    with conn().cursor() as cur:
        cur.execute(sql, args)
        return cur.rowcount


# ─────────────────────────────────────────────────────── 세션
def touch_session(sid: str, ttl_days: int = 30) -> None:
    run("INSERT INTO session (sid) VALUES (%s) "
        "ON DUPLICATE KEY UPDATE seen_at = CURRENT_TIMESTAMP", sid)
    # 오래 안 쓴 세션은 버린다. 로그인 상태를 영원히 들고 있지 않는다.
    run("DELETE FROM session WHERE seen_at < NOW() - INTERVAL %s DAY", ttl_days)


def bind_session(sid: str, uid: str) -> None:
    run("INSERT INTO session (sid, user_id) VALUES (%s, %s) "
        "ON DUPLICATE KEY UPDATE user_id = VALUES(user_id), "
        "seen_at = CURRENT_TIMESTAMP", sid, uid)


def unbind_session(sid: str) -> None:
    run("UPDATE session SET user_id = NULL WHERE sid = %s", sid)


def user_of_session(sid: str) -> str | None:
    r = one("SELECT user_id FROM session WHERE sid = %s", sid)
    return (r or {}).get("user_id")


# ─────────────────────────────────────────────────────── 회원
def get_user(uid: str) -> dict | None:
    return one("SELECT * FROM user WHERE id = %s", uid)


def upsert_user(uid: str, name: str = "", image: str = "",
                bonus: int = 0) -> tuple[dict, bool]:
    """(회원, 처음인가). 처음이면 체험 크레딧을 얹고 그 사실을 장부에 남긴다."""
    fresh = get_user(uid) is None
    if fresh:
        run("INSERT INTO user (id, name, image, balance, last_login_at) "
            "VALUES (%s, %s, %s, %s, NOW())", uid, name, image, bonus)
        if bonus:
            _log(uid, bonus, "signup", "", bonus)
    else:
        # 이름·사진은 로그인할 때마다 갱신한다. 빈 값으로 덮지는 않는다 —
        # 선택 동의라 거절하면 빈 값이 오는데, 그게 기존 값을 지우면 안 된다.
        run("UPDATE user SET name = COALESCE(NULLIF(%s, ''), name), "
            "image = COALESCE(NULLIF(%s, ''), image), last_login_at = NOW() "
            "WHERE id = %s", name, image, uid)
    return get_user(uid), fresh


def agree(uid: str) -> None:
    run("UPDATE user SET agreed_at = NOW() WHERE id = %s AND agreed_at IS NULL",
        uid)


def save_profile(uid: str, fields: dict) -> None:
    cols = [k for k in ("email", "label") if k in fields]
    if not cols:
        return
    sets = ", ".join(f"{c} = %s" for c in cols)
    run(f"UPDATE user SET {sets} WHERE id = %s",
        *[fields[c] for c in cols], uid)


# ─────────────────────────────────────────────── 크레딧 (장부)
def _log(uid: str, delta: int, reason: str, ref: str, after: int) -> None:
    run("INSERT INTO credit_log (user_id, delta, reason, ref, balance_after) "
        "VALUES (%s, %s, %s, %s, %s)", uid, delta, reason, ref, after)


def balance(uid: str) -> int:
    r = one("SELECT balance FROM user WHERE id = %s", uid)
    return int((r or {}).get("balance") or 0)


def spend(uid: str, n: int, ref: str, reason: str = "read") -> bool:
    """
    **조건부 UPDATE 한 방으로 깎는다.** 읽고 나서 빼면 두 요청이 같은
    잔액을 읽고 각자 깎아 한 번 값으로 두 번 판독할 수 있다(경합).
    WHERE balance >= n 이 걸린 UPDATE 는 DB 가 직렬화해 준다.
    """
    if run("UPDATE user SET balance = balance - %s "
           "WHERE id = %s AND balance >= %s", n, uid, n) != 1:
        return False
    _log(uid, -n, reason, ref, balance(uid))
    return True


def grant(uid: str, n: int, ref: str, reason: str) -> int:
    run("UPDATE user SET balance = balance + %s WHERE id = %s", n, uid)
    b = balance(uid)
    _log(uid, n, reason, ref, b)
    return b


def ledger(uid: str, limit: int = 50) -> list[dict]:
    return q("SELECT delta, reason, ref, balance_after, at FROM credit_log "
             "WHERE user_id = %s ORDER BY id DESC LIMIT %s", uid, limit)


# ─────────────────────────────────────────── 무차별 대입 차단
def fail_count(who: str, minutes: int = 15) -> int:
    r = one("SELECT COUNT(*) n FROM login_fail "
            "WHERE who = %s AND at > NOW() - INTERVAL %s MINUTE", who, minutes)
    return int((r or {}).get("n") or 0)


def note_fail(who: str) -> None:
    run("INSERT INTO login_fail (who) VALUES (%s)", who)
    run("DELETE FROM login_fail WHERE at < NOW() - INTERVAL 1 DAY")


def clear_fails(who: str) -> None:
    run("DELETE FROM login_fail WHERE who = %s", who)


# ──────────────────────────────────────────────────── 비밀번호
# **scrypt.** 표준 라이브러리에 있고(의존성 0), 메모리를 많이 쓰게 만들어
# GPU 로 몰아치는 걸 어렵게 한다. 소금은 회원마다 다르다 — 같은 비밀번호를
# 쓴 두 사람의 해시가 같으면 한 번에 둘이 뚫린다.
_SCRYPT = dict(n=2 ** 14, r=8, p=1, dklen=32, maxmem=64 * 1024 * 1024)


def hash_pw(pw: str) -> str:
    import hashlib
    import secrets as _s
    salt = _s.token_bytes(16)
    h = hashlib.scrypt(pw.encode(), salt=salt, **_SCRYPT)
    return f"scrypt${salt.hex()}${h.hex()}"


def check_pw(pw: str, stored: str) -> bool:
    import hashlib
    import hmac
    try:
        kind, salt, want = stored.split("$")
        if kind != "scrypt":
            return False
        got = hashlib.scrypt(pw.encode(), salt=bytes.fromhex(salt), **_SCRYPT)
        # **timing-safe.** == 는 앞에서부터 비교하다 다르면 바로 멈춰서,
        # 걸린 시간으로 몇 글자가 맞았는지 새어 나간다.
        return hmac.compare_digest(got.hex(), want)
    except Exception:                            # noqa: BLE001
        return False


def create_local(uid: str, pw: str, email: str, bonus: int) -> None:
    run("INSERT INTO user (id, name, email, pw_hash, balance, agreed_at, "
        "last_login_at) VALUES (%s, %s, %s, %s, %s, NOW(), NOW())",
        uid, uid.split(":", 1)[-1], email, hash_pw(pw), bonus)
    if bonus:
        _log(uid, bonus, "signup", "", bonus)


# ──────────────────────────────────────────── 판독 기록 (진단용)
# **악보 내용은 남기지 않는다.** 남기는 건 "무엇이 안 풀렸나"라는 구조적
# 사유뿐이다 — 가사도, 코드도, 이미지도 들어오지 않는다. 이게 없으면
# 왜 전부 환불되는지 알 길이 없어서 개선할 지점을 못 고른다.
READ_SCHEMA = """
CREATE TABLE IF NOT EXISTS read_log (
  id       BIGINT AUTO_INCREMENT PRIMARY KEY,
  user_id  VARCHAR(64) NULL,
  job_id   VARCHAR(32) NOT NULL,
  status   VARCHAR(16) NOT NULL,
  gate     VARCHAR(16) NOT NULL,
  charged  TINYINT NOT NULL DEFAULT 0,
  two_voice DECIMAL(5,3) NULL,
  systems  INT NULL,
  notes    INT NULL,
  issues   INT NOT NULL DEFAULT 0,
  secs     INT NULL,
  at       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY k_at (at), KEY k_gate (gate, at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS read_issue (
  id      BIGINT AUTO_INCREMENT PRIMARY KEY,
  read_id BIGINT NOT NULL,
  kind    VARCHAR(48) NOT NULL,
  detail  VARCHAR(200) NOT NULL DEFAULT '',
  KEY k_kind (kind), KEY k_read (read_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""

# 사유 하나하나는 "단 3: 박자 합이 …" 처럼 다 달라서 그대로 세면 전부
# 1건씩 나온다. 숫자를 지워 **같은 종류끼리 묶일 열쇠**를 만든다.
import re as _re

_KINDS = (
    ("two_voice",     "두 성부"),
    ("no_struct",     "음표 구조가 없어"),
    ("system_count",  "단 수가 다릅니다"),
    ("missing_pitch", "음높이를 정하지 못한"),
    ("verify_fail",   "구조 검증 실패"),
    ("no_staff",      "오선을 찾지 못"),
)


def issue_kind(msg: str) -> str:
    for kind, needle in _KINDS:
        if needle in msg:
            return kind
    # "단 N: 사유" 는 사유만 남긴다
    tail = _re.sub(r"^단\s*\d+\s*[:：]\s*", "", msg).strip()
    tail = _re.sub(r"\d+", "N", tail)
    return ("assemble:" + tail)[:48]


def log_read(user_id, job_id, status, gate, charged, two_voice,
             systems, notes, issues, secs) -> None:
    try:
        run("INSERT INTO read_log (user_id, job_id, status, gate, charged, "
            "two_voice, systems, notes, issues, secs) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            user_id, job_id[:32], status[:16], gate[:16], int(bool(charged)),
            two_voice, systems, notes, len(issues), secs)
        rid = one("SELECT LAST_INSERT_ID() id")["id"]
        for m in issues[:40]:
            run("INSERT INTO read_issue (read_id, kind, detail) VALUES (%s,%s,%s)",
                rid, issue_kind(m)[:48], str(m)[:200])
    except Exception as e:                       # noqa: BLE001
        # **진단이 판독을 막으면 안 된다.** 기록에 실패해도 결과는 나간다.
        print(f"판독 기록 실패: {type(e).__name__}", file=__import__("sys").stderr)
