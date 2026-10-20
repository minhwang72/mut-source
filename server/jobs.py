#!/usr/bin/env python3
"""
작업 큐 + 체험 크레딧 장부 (인메모리).

왜 큐가 필요한가: 지금은 업로드 한 번이 30~60초짜리 동기 요청이라 브라우저가
멈춘다. 게다가 같은 사진을 다시 올리면 같은 일을 처음부터 또 한다.
작업으로 쪼개면 화면은 진행 상황을 받고, 같은 입력은 한 번만 돈다.

**이건 결제 시스템이 아니다.** 신원은 로컬 쿠키 하나이고 장부는 메모리에만
있다 — 서버를 다시 띄우면 잔액이 초기값으로 돌아간다. 그 사실을
/api/health · /api/account 가 그대로 말한다. PG 연동·회원 인증은 없다.
"""

from __future__ import annotations

import hashlib
import json
import os
import queue
import secrets
import threading
import time
import traceback

try:
    import db as DB
except Exception:      # noqa: BLE001  (테스트는 DB 없이 돈다)
    DB = None


class Busy(Exception):
    """큐가 찼거나 동시 작업 한도를 넘었다 → 429."""


class Denied(Exception):
    """요청은 owner 것이 맞지만 조건을 못 채웠다 → 409."""


ACTIVE = ("queued", "running")


def _looks_like_email(v: str) -> bool:
    """
    **형식만 본다.** 실제로 살아 있는 주소인지는 메일이 가 봐야 안다 —
    영수증이 반송되면 그때 알게 된다. 여기서는 오타로 보이는 것만 막는다.
    """
    if v.count("@") != 1 or " " in v:
        return False
    local, _, host = v.partition("@")
    return bool(local) and "." in host and not host.startswith(".") \
        and not host.endswith(".")


class JobStore:
    def __init__(self, reader, *, trial_balance: int = 5, price: int = 1,
                 ttl: float = 900.0, max_queue: int = 8, max_active: int = 2,
                 max_jobs: int = 64, workers: int = 1,
                 reader_version: str = "v1",
                 ip_hourly: int = 12):
        self.reader = reader
        self.trial_balance = int(trial_balance)
        self.price = int(price)
        self.ttl = float(ttl)
        self.max_queue = int(max_queue)
        self.max_active = int(max_active)
        self.max_jobs = int(max_jobs)
        self.reader_version = reader_version
        # **판독은 IP 단위로도 막는다.** 비용은 판독에서 나는데 차감은 저장에서
        # 하므로, 세션 쿠키만 지우면 누구나 무한히 판독을 돌릴 수 있다. 익명
        # 신원은 원래 초기화되는 것이라, 익명 구간에서 기댈 수 있는 건 IP 뿐이다
        # (완벽하지 않다 — 모바일·VPN 은 바뀐다. 그래서 로그인이 필요하다).
        self.ip_hourly = int(ip_hourly)
        self.started = time.time()

        self._lock = threading.Lock()
        self._jobs: dict[str, dict] = {}
        self._balances: dict[str, int] = {}
        self._blobs: dict[str, bytes] = {}
        self._ip_hits: dict[str, list[float]] = {}
        # **체험 크레딧은 IP 로도 센다.** 세션 쿠키를 지우면 새 장부가 생기므로
        # 세션만으로는 체험을 무한히 갱신할 수 있다. 익명 구간에서 기댈 수
        # 있는 건 IP 뿐이다 — 완벽하지 않지만(모바일·VPN 은 바뀐다) 쿠키
        # 지우기 한 번으로 뚫리지는 않게 한다. 제대로 막으려면 로그인이다.
        self._ip_spent: dict[str, int] = {}
        # 마스터 세션. 결제가 붙기 전까지 전 기능을 열어 두되, **세션 단위**다 —
        # 전역으로 열면 공개 주소에서 누구나 판독을 무한히 돌린다.
        self._master: set[str] = set()
        # 로그인한 세션. 지금은 마스터만 들어오지만, 카카오 로그인이 붙으면
        # 인증 성공 때 여기에 넣으면 된다 — 나머지 흐름은 그대로다.
        self._authed: set[str] = set()
        # 세션 → 회원번호, 회원번호 → 잔액·이름. 로그인하면 장부가 회원을
        # 따라간다(세션이 아니라). 결제 전에 DB 로 옮겨야 한다.
        self._user_of: dict[str, str] = {}
        self._name_of: dict[str, str] = {}
        # 회원이 직접 채우는 값 + 카카오가 준 프로필 사진 URL.
        # {회원번호: {image, email, label}}
        self._prof_of: dict[str, dict] = {}
        # 방금 처음 들어온 회원 — 약관 동의를 받아야 한다
        self._fresh: set[str] = set()
        self._user_balance: dict[str, int] = {}
        self.require_auth = False
        self._q: queue.Queue = queue.Queue(maxsize=self.max_queue)
        self._threads = [threading.Thread(target=self._worker, daemon=True)
                         for _ in range(max(1, int(workers)))]
        for t in self._threads:
            t.start()

    # ───────────────────────────────────────────────────────── 세션·장부
    def new_session(self) -> str:
        return secrets.token_urlsafe(24)

    @property
    def durable(self) -> bool:
        """DB 가 붙어 있나. 붙어 있으면 잔액·로그인은 전부 거기서 산다."""
        return bool(DB and DB.configured())

    def touch(self, sid: str) -> None:
        if self.durable:
            DB.touch_session(sid)
            # **재시작 뒤 되살리기.** _authed 는 메모리라 서버가 다시 뜨면
            # 빈다. 쿠키를 들고 온 사람은 DB 에 세션이 남아 있으니 여기서
            # 다시 이어 준다 — 안 하면 재배포할 때마다 전원이 로그아웃된다.
            if sid not in self._authed:
                u = DB.user_of_session(sid)
                if u:
                    with self._lock:
                        self._authed.add(sid)
                        self._user_of[sid] = u
            return
        with self._lock:
            self._balances.setdefault(sid, self.trial_balance)

    def grant_master(self, sid: str) -> None:
        with self._lock:
            self._master.add(sid)
            self._authed.add(sid)

    def grant_auth(self, sid: str, user: str | None = None,
                   name: str = "", image: str = "") -> None:
        """
        로그인 성공. `user` 는 제공자가 주는 **고유 회원번호**다.

        같은 사람이 다시 로그인하면 잔액이 이어져야 하므로, 세션이 아니라
        회원번호로 장부를 붙인다. 지금은 메모리라 서버를 다시 시작하면
        사라진다 — 결제를 붙이기 전에 DB 로 옮겨야 한다.
        """
        if self.durable and user:
            _row, fresh = DB.upsert_user(user, name, image,
                                         bonus=self.trial_balance)
            DB.bind_session(sid, user)
            with self._lock:
                self._authed.add(sid)
                self._user_of[sid] = user
                self._fresh.add(user) if fresh else self._fresh.discard(user)
            return
        with self._lock:
            self._authed.add(sid)
            if user:
                self._user_of[sid] = user
                self._name_of[user] = name or self._name_of.get(user, "")
                p = self._prof_of.setdefault(user, {})
                # 사진은 로그인할 때마다 갱신한다(카카오에서 바꿨을 수 있다).
                # 회원이 직접 채운 값(email·label)은 건드리지 않는다.
                if image:
                    p["image"] = image
                # 이 회원의 잔액을 세션에 연결한다
                bal = self._user_balance.setdefault(user, self.trial_balance)
                self._balances[sid] = bal

    def revoke_auth(self, sid: str) -> None:
        """
        로그아웃. **세션에서 신원만 뗀다.**

        잔액은 회원번호에 붙어 있으므로 건드리지 않는다 — 다시 로그인하면
        그대로 이어진다. 세션에 남아 있던 잔액 사본은 지운다. 안 지우면
        로그아웃한 브라우저가 그 잔액으로 계속 판독할 수 있다.
        """
        if self.durable:
            DB.unbind_session(sid)
        with self._lock:
            u = self._user_of.get(sid)
            self._authed.discard(sid)
            self._master.discard(sid)
            self._user_of.pop(sid, None)
            self._balances.pop(sid, None)
            # **이 세션의 작업도 함께 버린다.** submit 의 "같은 그림 재사용"
            # 경로는 로그인 검사보다 앞에 있다(공짜라서 그렇게 뒀다). 결과를
            # 남겨 두면 로그아웃한 브라우저에서 앞사람 악보를 계속 받아 갈 수
            # 있다 — 교회 공용 PC 에서 그대로 터진다.
            back = 0
            for jid, j in list(self._jobs.items()):
                if j["owner"] != sid:
                    continue
                # 읽는 중에 로그아웃했다면 잡아 둔 크레딧은 돌려준다
                if not j["charged"]:
                    back += j.get("held", 0)
                del self._jobs[jid]
                self._blobs.pop(jid, None)
            if u and back:
                self._user_balance[u] = self._user_balance.get(u, 0) + back

    # 회원이 직접 채우는 칸. **길이는 여기서 자른다** — 신뢰 경계다.
    FIELDS = {"email": 254, "label": 40}

    def profile(self, sid: str) -> dict:
        u = self._user_of.get(sid)
        if self.durable:
            r = DB.get_user(u) if u else None
            return {k: (r or {}).get(k) or "" for k in ("image", *self.FIELDS)}
        with self._lock:
            p = self._prof_of.get(u or "", {})
            return {k: p.get(k, "") for k in ("image", *self.FIELDS)}

    def set_profile(self, sid: str, data: dict) -> dict:
        """
        회원이 채운 값을 저장한다. **image 는 받지 않는다** — 카카오가 주는
        값이지 사용자가 넣는 값이 아니다. 받으면 아무 주소나 아바타로
        띄울 수 있다.
        """
        u = self._user_of.get(sid)
        if not u:
            raise Denied("로그인이 필요합니다.")
        clean = {}
        for k, cap in self.FIELDS.items():
            if k not in data:
                continue
            v = str(data.get(k) or "").strip()[:cap]
            if k == "email" and v and not _looks_like_email(v):
                raise Denied("이메일 주소를 다시 확인해 주세요.")
            clean[k] = v
        if self.durable:
            DB.save_profile(u, clean)
        else:
            with self._lock:
                self._prof_of.setdefault(u, {}).update(clean)
        return self.profile(sid)

    def _agreed(self, uid: str) -> bool:
        row = DB.get_user(uid) if self.durable else None
        return bool(row and row.get("agreed_at"))

    def user_of(self, sid: str) -> str | None:
        with self._lock:
            return self._user_of.get(sid)

    def display_name(self, sid: str) -> str:
        with self._lock:
            u = self._user_of.get(sid)
            return self._name_of.get(u, "") if u else ""

    def is_authed(self, sid: str) -> bool:
        with self._lock:
            return sid in self._authed

    def is_master(self, sid: str) -> bool:
        with self._lock:
            return sid in self._master

    def account(self, sid: str) -> dict:
        with self._lock:
            master = sid in self._master
            u = self._user_of.get(sid)
        row = None
        if self.durable:
            row = DB.get_user(u) if u else None
            bal = int((row or {}).get("balance") or 0)
            need_agree = bool(row) and row.get("agreed_at") is None
        else:
            need_agree = False
            with self._lock:
                bal = self._balances.setdefault(sid, self.trial_balance)
        return {
            "trial": not master,
            "master": master,
            "authRequired": self.require_auth,
            "authed": master or sid in self._authed,
            # 이름도 DB 가 원본이다 — 메모리 사전은 DB 없이 도는 테스트용
            "name": (row or {}).get("name", "") if self.durable
                    else self._name_of.get(u or "", ""),
            **self.profile(sid),
            "balance": bal,
            "chargeOn": "read",
            "pricePerScore": self.price,
            # 이 두 줄이 "아직 결제 시스템이 아니다"를 말한다.
            # 가입 직후 약관 동의를 아직 안 받은 상태
            "needsAgree": need_agree,
            "storage": "db" if self.durable else "memory",
            "resetsOnRestart": not self.durable,
        }

    # ─────────────────────────────────────────────────────────── 작업
    def submit(self, sid: str, blob: bytes, opts: dict,
               ip: str | None = None) -> tuple[dict, bool]:
        """
        같은 세션 + 같은 내용 + 같은 옵션 + 같은 모델이면 **이미 있는 작업을
        돌려준다.** 남의 작업은 절대 재사용하지 않는다 — 결과가 새어 나간다.
        """
        key = self._cache_key(blob, opts)
        with self._lock:
            self._purge_locked()
            hit = next((j for j in self._jobs.values()
                        if j["owner"] == sid and j["key"] == key
                        and j["status"] != "failed"), None)
            if hit is not None:
                return self._public(hit), True     # 같은 그림 재사용은 공짜다

            if ip and self.ip_hourly > 0:
                now = time.time()
                hits = [t for t in self._ip_hits.get(ip, ()) if now - t < 3600]
                if len(hits) >= self.ip_hourly:
                    raise Busy("한 시간에 올릴 수 있는 악보 수를 넘었습니다. "
                               "잠시 뒤 다시 시도해 주세요.")
                hits.append(now)
                self._ip_hits[ip] = hits

            active = sum(1 for j in self._jobs.values()
                         if j["owner"] == sid and j["status"] in ACTIVE)
            if active >= self.max_active:
                raise Busy(f"진행 중인 작업이 이미 {active}개입니다. 끝난 뒤 올려 주세요.")

            # **판독을 시작하기 전에 크레딧을 잡는다.** 비용은 판독에서
            # 나므로 저장에서 깎으면 구조가 어긋난다 — 미리보기를 화면에서
            # 받아 가면 그만이고(캔버스는 우클릭으로 저장된다), 쿠키를 지우면
            # 판독을 무한히 돌릴 수 있었다. 잡아 두기만 하고 **결과가 검사를
            # 통과할 때 확정**한다. 실패하거나 확인이 필요한 결과면 돌려준다.
            master = sid in self._master
            u = self._user_of.get(sid)
            bal = (DB.balance(u) if (self.durable and u) else
                   self._balances.setdefault(sid, self.trial_balance))
            # **계정 없이는 판독하지 않는다.** 주소를 아는 사람이 쓰면 비용이
            # 개인 API 키에서 나간다(실측 84건). 결제와 로그인이 붙기 전까지는
            # 잠가 두고, 붙으면 이 검사가 그대로 "로그인 + 크레딧" 이 된다.
            if self.require_auth and sid not in self._authed:
                raise Denied("로그인이 필요합니다. 현재는 준비 중입니다.")
            # **동의도 서버가 확인한다.** 간편 로그인은 버튼 한 번에 계정이
            # 생기고, 그 뒤 약관 화면으로 보내는데 — 거기서 창을 닫아도
            # 로그인 상태는 남는다. 화면만 막아 두면 그 사람은 동의 기록
            # 없이 계속 쓸 수 있고, 분쟁이 나면 댈 게 없다.
            if self.durable and u and not self._agreed(u):
                raise Denied("약관 동의가 필요합니다. 회원가입 화면에서 "
                             "동의해 주세요.")
            jid = secrets.token_urlsafe(12)
            if not master:
                if ip and self._ip_spent.get(ip, 0) >= self.trial_balance:
                    raise Denied("체험 크레딧을 모두 사용했습니다.")
                if self.durable and u:
                    # **읽고 빼지 않는다.** 두 요청이 같은 잔액을 읽으면 한 번
                    # 값으로 두 번 판독된다. 조건부 UPDATE 한 방으로 깎아
                    # DB 가 직렬화하게 둔다.
                    if not DB.spend(u, self.price, jid):
                        raise Denied("크레딧이 모자랍니다.")
                else:
                    if bal < self.price:
                        raise Denied("체험 크레딧이 모자랍니다.")
                    self._balances[sid] = bal - self.price
                    if u:
                        self._user_balance[u] = self._balances[sid]

            job = {"id": jid, "owner": sid, "status": "queued", "stage": "queued",
                   "progress": 0, "result": None, "error": None,
                   "key": key, "charged": False,
                   "held": 0 if master else self.price, "ip": ip, "master": master,
                   "created": time.time(), "updated": time.time()}
            self._jobs[jid] = job
            self._blobs[jid] = blob
            try:
                self._q.put_nowait((jid, opts))
            except queue.Full:
                del self._jobs[jid]
                del self._blobs[jid]
                if not master:                       # 잡아 둔 값을 되돌린다
                    if self.durable and u:
                        DB.grant(u, self.price, jid, "refund")
                    else:
                        self._balances[sid] += self.price
                raise Busy("대기열이 가득 찼습니다. 잠시 뒤 다시 시도해 주세요.") from None
            return self._public(job), False

    def get(self, sid: str, jid: str) -> dict | None:
        """남의 작업이면 **없는 것처럼** 낸다 — 존재 여부도 알리지 않는다."""
        with self._lock:
            self._purge_locked()
            job = self._jobs.get(jid)
            if job is None or job["owner"] != sid:
                return None
            return self._public(job, with_result=True)

    def commit(self, sid: str, jid: str) -> dict:
        """
        **더 이상 여기서 깎지 않는다.** 과금은 판독 시점으로 옮겼다
        (`submit` 에서 잡고 `_settle` 에서 확정한다). 저장은 이미 값을 치른
        결과를 받아 가는 것이므로 공짜다 — 예전처럼 저장에서 깎으면
        미리보기를 화면에서 가져가는 쪽이 이득이 되어 구조가 어긋난다.

        클라이언트가 저장할 때 계속 부르므로 현재 상태만 돌려준다.
        """
        with self._lock:
            self._purge_locked()
            job = self._jobs.get(jid)
            if job is None or job["owner"] != sid:
                raise KeyError(jid)
            if job["status"] != "done":
                raise Denied(f"아직 끝나지 않은 작업입니다 (status={job['status']}).")
            if not job["charged"] and not job.get("master"):
                raise Denied("확인이 필요한 결과라 차감하지 않았습니다.")
            return {"charged": False, "alreadyCharged": True,
                    "balance": self._balances.setdefault(sid, self.trial_balance),
                    "jobId": jid}

    def health(self) -> dict:
        with self._lock:
            self._purge_locked()
            n = len(self._jobs)
            active = sum(1 for j in self._jobs.values() if j["status"] in ACTIVE)
        return {
            "billingMode": "trial",
            "authRequired": self.require_auth,
            # 카카오 로그인이 설정됐는지. 화면이 버튼을 보일지 정한다.
            "kakao": bool(os.environ.get("KAKAO_REST_KEY")),
            "naver": bool(os.environ.get("NAVER_CLIENT_ID")),
            "chargeOn": "read",          # 저장이 아니라 판독에서 깎는다
            "pricePerScore": self.price,
            "trialBalance": self.trial_balance,
            "storage": "memory",
            "resetsOnRestart": True,
            "jobs": n,
            "active": active,
            "queueLimit": self.max_queue,
            "maxActivePerUser": self.max_active,
            "workers": len(self._threads),
            "resultTtlSeconds": int(self.ttl),
            "uptimeSeconds": int(time.time() - self.started),
        }

    def stop(self) -> None:
        for _ in self._threads:
            try:
                self._q.put_nowait((None, None))
            except queue.Full:
                pass

    # ───────────────────────────────────────────────────────── 내부
    def _cache_key(self, blob: bytes, opts: dict) -> str:
        h = hashlib.sha256(blob).hexdigest()
        o = hashlib.sha256(
            json.dumps(opts, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]
        return f"{h}:{o}:{self.reader_version}"

    def _public(self, job: dict, with_result: bool = False) -> dict:
        out = {"id": job["id"], "status": job["status"], "stage": job["stage"],
               "progress": job["progress"]}
        if with_result:
            if job["status"] == "done":
                out["result"] = job["result"]
                out["charged"] = job["charged"]
            elif job["status"] == "failed":
                out["error"] = job["error"]
        return out

    def _purge_locked(self) -> None:
        """끝난 지 오래된 결과를 버린다. 메모리는 유한하고 결과는 무겁다."""
        now = time.time()
        for jid, j in list(self._jobs.items()):
            if j["status"] in ACTIVE:
                continue
            if now - j["updated"] > self.ttl:
                del self._jobs[jid]
        if len(self._jobs) > self.max_jobs:
            done = sorted((j for j in self._jobs.values() if j["status"] not in ACTIVE),
                          key=lambda j: j["updated"])
            for j in done[:len(self._jobs) - self.max_jobs]:
                del self._jobs[j["id"]]

    def _set(self, jid: str, **kw) -> None:
        with self._lock:
            job = self._jobs.get(jid)
            if job is not None:
                job.update(kw, updated=time.time())

    def _settle(self, jid: str) -> None:
        """
        잡아 둔 크레딧을 **확정하거나 돌려준다.**

        확정 조건은 저장 때 쓰던 것과 같다 — 끝났고, 품질 검사가 ready 다.
        읽다 실패했거나 "확인이 필요한 결과"면 돌려준다: 우리가 못 준 것에
        받지 않는다. 확정한 뒤에는 미리보기·키 재변환·저장이 전부 포함이다.
        """
        with self._lock:
            job = self._jobs.get(jid)
            if job is None or not job.get("held"):
                return
            gate = ((job.get("result") or {}).get("qualityGate") or {})
            ok = job["status"] == "done" and gate.get("status") == "ready"
            sid = job["owner"]
            if ok:
                job["charged"] = True
                job["chargedAt"] = time.time()
                if job.get("ip"):
                    self._ip_spent[job["ip"]] = (
                        self._ip_spent.get(job["ip"], 0) + job["held"])
            else:
                u = self._user_of.get(sid)
                if self.durable and u:
                    DB.grant(u, job["held"], jid, "refund")
                else:
                    self._balances[sid] = (
                        self._balances.get(sid, self.trial_balance) + job["held"])
                    if u:
                        self._user_balance[u] = self._balances[sid]
                job["refunded"] = True
            job["held"] = 0
            job["updated"] = time.time()
            snapshot = (job, gate, ok)
        # **락 밖에서 기록한다.** DB 쓰기가 느려도 판독 경로를 붙잡지 않는다.
        self._log_read(*snapshot)

    def _log_read(self, job: dict, gate: dict, charged: bool) -> None:
        """
        왜 통과하지 못했는지 남긴다. **악보 내용은 안 남긴다** — 가사도
        코드도 이미지도 들어가지 않고, "무엇이 안 풀렸나"라는 구조적 사유만
        들어간다. 이게 없으면 전부 환불되는 이유를 알 수 없어서 어디를
        고쳐야 할지 고를 수가 없다.
        """
        if not self.durable:
            return
        res = job.get("result") or {}
        struct = res.get("struct") or {}
        systems = struct.get("systems") or []
        issues = list(gate.get("issues") or [])
        if job["status"] == "failed" and job.get("error"):
            issues = issues or [str(job["error"])]
        DB.log_read(
            user_id=self._user_of.get(job["owner"]),
            job_id=job["id"],
            status=job["status"],
            gate=gate.get("status") or ("failed" if job["status"] == "failed"
                                        else "none"),
            charged=charged,
            two_voice=gate.get("twoVoice"),
            systems=len(systems) or None,
            notes=sum(len(m.get("notes") or [])
                      for sy in systems for m in (sy.get("measures") or [])) or None,
            issues=issues,
            secs=int(job["updated"] - job["created"]),
        )

    def _worker(self) -> None:
        while True:
            jid, opts = self._q.get()
            if jid is None:
                return
            with self._lock:
                blob = self._blobs.pop(jid, None)
                alive = jid in self._jobs
            if blob is None or not alive:
                continue
            self._set(jid, status="running", stage="start", progress=1)
            try:
                result = self.reader(
                    blob, opts,
                    lambda stage, pct, _j=jid: self._set(_j, stage=stage,
                                                         progress=int(pct)))
                self._set(jid, status="done", stage="done", progress=100,
                          result=result)
                self._settle(jid)
            except Exception as e:                # noqa: BLE001
                traceback.print_exc()
                self._set(jid, status="failed", stage="failed", progress=100,
                          error=_safe_error(e))
                self._settle(jid)
            finally:
                # 원본 바이트는 성공·실패와 무관하게 여기서 끝난다.
                blob = None
                del blob


def _safe_error(e: Exception) -> str:
    """
    사용자에게는 짧은 사유만 준다. 역추적은 서버 로그에만 남긴다 —
    경로·모듈 이름이 그대로 나가면 그 자체가 정보 누출이다.
    """
    if isinstance(e, (ValueError, Denied)):
        return str(e)[:200]
    return "판독에 실패했습니다. 더 선명한 사진으로 다시 시도해 주세요."
