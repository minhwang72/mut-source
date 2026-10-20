/**
 * 뮤트 웹앱.
 *
 * 저작권 설계의 핵심: **변환된 악보 이미지는 이 파일이 브라우저에서 만든다.**
 * 서버는 좌표와 코드 텍스트(구조 데이터)만 돌려주고, 복제물을 생성하지 않는다.
 * 그래서 이조 엔진(engine/)이 의존성 0으로 브라우저에서 돌아야 했다.
 */

import {
  fifths,
  parseChord,
  formatChord,
  formatKey,
  parseKey,
  planBySemitones,
  transposeChords,
} from "./engine/index.js";
import { buildPdf, canvasToJpeg } from "./pdf.js";
import { request, readScore } from './service.js';
import { redraw, whyNoRedraw } from "./redraw.js";
import { fixPanel } from './fixbeats.js';


/* ─────────────────────────── 상태 ─────────────────────────── */

const state = {
  /** 업로드된 원본 (HTMLImageElement) */
  image: null,
  /** 서버가 준 구조 데이터 */
  extraction: null,
  /** 확인이 필요한 코드들의 평탄화 인덱스 */
  pending: [],
  pendingAt: 0,
  /** 선택된 이조 반음 수 */
  semitones: 0,
  /** 결과 화면에서 원본/변환 토글 */
  showOriginal: false,
  job: null,
  uploadController: null,
  exportBusy: false,
  rendered: false,
  uploadFile: null,
  /** /api/account 응답 (잔액·마스터 여부) */
  account: null,
  /** 결제 내역. 실제 주문이 생기기 전까지 비어 있다 — 지어내지 않는다. */
  orders: [],
  pack: null,
};

const $ = (id) => document.getElementById(id);
const SCREENS = ["upload", "loading", "key", "confirm", "result",
                 "login", "signup",
                 "account", "faq", "contact", "terms", "privacy", "oss"];

/**
 * **화면은 두 벌이다.** 변환(위저드)과 계정.
 *
 * 위저드 안의 단계는 URL 에 넣지 않는다 — 새로고침하면 판독 결과가 없어
 * 복원할 수 없으므로, 주소만 그럴싸하고 화면은 빈 상태가 된다. 주소를
 * 갖는 건 이 둘뿐이고, 그래야 뒤로가기가 상식대로 움직인다.
 */
const ROUTES = {
  "/": "upload", "/login": "login", "/signup": "signup",
  "/account": "account",
  "/faq": "faq", "/contact": "contact",
  "/terms": "terms", "/privacy": "privacy", "/oss": "oss",
};

/**
 * **사업자 표시는 전자상거래법 제10조상 의무**다. 유료로 팔려면 빠질 수 없다.
 * 값은 여기 한 곳에서만 채운다 — 푸터·약관·방침이 모두 이걸 읽는다.
 *
 * 비어 있는 칸은 화면에 "입력 필요"로 뜬다. **지어내지 않는다** — 사업자
 * 등록번호나 통신판매업 신고번호를 임의로 채우면 허위 표시가 된다.
 */
const BIZ = {
  // 사업자등록증(2026-07-06 등록, 일반과세자) 기준.
  // 브랜드명은 mut 이지만 표시 의무 상호는 등록증상 이름을 쓴다.
  name: "모이드",
  ceo: "황민",                    // 대표자 = 개인정보 보호책임자
  regNo: "796-39-01338",
  mailOrderNo: "제2026-서울구로-1251호",   // 2026-07-08 신고, 서울시 구로구
  addr: "서울특별시 구로구 경인로 291-3, 나동 405호(개봉동, 휴미락)",
  tel: "0502-6681-5019",         // 안심번호 — 개인 휴대번호를 사이트에 노출하지 않는다
  mail: "zxcyui6181@naver.com",
  host: "자체 서버 (monsil)",
  pg: "",                        // 결제대행사 — 심사 통과 후 확정되면 채운다
  updated: "2026-09-18",
};/** 크레딧 팩. 장당 단가가 내려가게 둔다. */
const PACKS = [
  { id: "p10",  credits: 10,  won: 5000,  name: "10크레딧" },
  { id: "p50",  credits: 50,  won: 20000, name: "50크레딧", best: true },
  { id: "p200", credits: 200, won: 60000, name: "200크레딧" },
];
// 낱개 단가. 묶음에는 할인이 붙으므로 그보다 비싸다 — 묶음이 손해가
// 되는 순간 묶음을 살 이유가 없어진다.
const UNIT_WON = 500;
const MAX_BUY = 999;

/** 로그인 붙기 전까지 쓰는 표시용 사용자. 서버는 이 값을 모른다. */
/** 로그인 전 표시용. 로그인하면 서버가 준 이름으로 덮인다. */


const won = (n) => n.toLocaleString("ko-KR") + "원";

const TITLES = {
  upload: "mut — 악보 키 변환",
  account: "계정 — mut",
  faq: "자주 묻는 질문 — mut",
  contact: "문의 — mut",
  terms: "이용약관 — mut",
  privacy: "개인정보처리방침 — mut",
  oss: "오픈소스 고지 — mut",
};

/** 비어 있으면 지어내지 않고 채워야 한다고 말한다. */
const bizVal = (v) => v || "입력 필요";

function renderBiz() {
  // 전자상거래법 제10조가 요구하는 것만. 호스팅 같은 군더더기는 뺀다.
  // 두 줄로 나눈다 — 한 줄로 흘리면 넘어간 줄이 구분 막대로 시작한다
  const lines = [
    [["상호", BIZ.name], ["대표", BIZ.ceo],
     ["사업자등록번호", BIZ.regNo], ["통신판매업", BIZ.mailOrderNo]],
    [["주소", BIZ.addr], ["전화", BIZ.tel], ["이메일", BIZ.mail]],
  ];
  const box = $("foot-biz");
  if (!box) return;
  box.replaceChildren();
  for (const rows of lines) {
    const line = document.createElement("div");
    line.className = "biz-line";
    for (const [k, v] of rows) {
      const d = document.createElement("span");
      d.className = "biz-item" + (v ? "" : " todo");
      d.innerHTML = `<b>${k}</b> : ${bizVal(v)}`;
      line.appendChild(d);
    }
    box.appendChild(line);
  }
  // 약관·방침 안의 빈칸도 같은 값으로 채운다
  for (const el of document.querySelectorAll(".biz-name")) el.textContent = bizVal(BIZ.name);
  for (const el of document.querySelectorAll(".biz-ceo")) el.textContent = bizVal(BIZ.ceo);
  for (const el of document.querySelectorAll(".biz-mail")) el.textContent = BIZ.mail;
  const pg = $("pg-row");
  if (pg) pg.textContent = BIZ.pg || "결제대행사 (계약 후 표기)";
  const cm = $("contact-mail");
  if (cm) {
    cm.textContent = BIZ.mail;
    cm.href = `mailto:${BIZ.mail}?subject=${encodeURIComponent("[mut] 문의")}`;
  }
  const stamp = `시행일 ${BIZ.updated}`;
  for (const id of ["terms-date", "privacy-date"]) {
    const el = $(id); if (el) el.textContent = stamp;
  }
}

function show(name) {
  for (const s of SCREENS) $(`s-${s}`).hidden = s !== name;
  $("back").hidden = name === "upload" || name === "loading";
  window.scrollTo(0, 0);
}

/** 주소를 가진 화면으로 간다. push=false 면 뒤로가기로 온 것이라 기록하지 않는다. */
function go(path, push = true) {
  const screen = ROUTES[path] || "upload";
  if (push && location.pathname !== path) history.pushState({ path }, "", path);
  if (screen === "account") renderAccount();
  show(screen);
  document.title = TITLES[screen] || "mut — 악보 키 변환";
}

function initRouter() {
  document.addEventListener("click", (e) => {
    const el = e.target.closest?.("[data-go]");
    if (!el) return;
    e.preventDefault();
    const to = el.dataset.go;
    go(to === "home" ? "/" : `/${to}`);
  });
  window.addEventListener("popstate", () => go(location.pathname, false));
}

/* ─────────────────────────────── 계정 화면 ─────────────────────────────── */

// 사진 > 이름 두 글자 > 8분음표. 사진은 선택 동의라 없는 쪽이 기본이다.
function paintAvatar(box, img, a) {
  if (!box) return;
  // **http 사진은 https 로 올린다.** 사이트가 https 라 혼합 콘텐츠로
  // 막힌다. 서버도 올려 보내지만, 이미 저장된 옛 주소가 남아 있다.
  let src = a?.image || "";
  if (src.startsWith("http://")) src = "https://" + src.slice(7);
  const txt = (a?.name || a?.label || "").slice(-2);
  if (img) {
    img.hidden = !src;
    if (src && img.getAttribute("src") !== src) img.src = src;
    // 카카오 CDN 이 죽어도 8분음표로 떨어지게 둔다
    img.onerror = () => { img.hidden = true; box.dataset.fallback = txt || ""; };
  }
  box.dataset.fallback = src ? "" : txt;
  box.classList.toggle("has-photo", !!src);
  box.classList.toggle("has-text", !src && !!txt);
}

function renderAccount() {
  // **이름이 없는 것과 로그인이 안 된 것은 다르다.** 닉네임은 선택 동의라
  // 거절하고 들어오는 사람이 있다 — 그래도 회원번호는 오고, 장부는 그걸로
  // 돈다. 이름이 비었다고 "로그인 전" 이라고 하면 로그인한 사람한테 거짓말이다.
  const a0 = state.account;
  const authed = !!(a0?.authed || a0?.master);
  const who = a0?.name || (a0?.master ? "마스터" : authed ? "카카오 회원" : "");
  // **아바타에 textContent 를 쓰면 안 된다.** 안에 든 <img id="acct-photo">
  // 를 통째로 지워 버린다 — 그래서 큰 아바타는 사진이 영영 안 떴고 늘
  // 이름 두 글자만 보였다. 글자는 ::after 가 data-fallback 으로 그린다
  // (paintAvatar 가 채운다).
  $("acct-name").textContent = who || "로그인 전";
  $("acct-mail").textContent =
    a0?.master ? "마스터 권한"
    : a0?.name ? "카카오 계정"
    : authed ? "카카오 계정 · 닉네임 비공개"
    : "";
  const out = $("logout");
  if (out) out.hidden = !authed;
  paintAvatar($("acct-avatar"), $("acct-photo"), a0);
  const card = $("c-profile");
  if (card) card.hidden = !authed;
  if (authed) {
    // 사용자가 타이핑 중인 값을 서버 값으로 덮지 않는다
    if (document.activeElement !== $("pf-email")) $("pf-email").value = a0?.email || "";
    if (document.activeElement !== $("pf-label")) $("pf-label").value = a0?.label || "";
  }

  const a = state.account;
  $("acct-credits").textContent = a?.master ? "무제한" : `${a?.balance ?? 0}`;
  $("acct-note").textContent = a?.master
    ? "마스터 권한 · 차감 없음"
    : "체험 크레딧 · 서버를 다시 시작하면 초기화됩니다";

  renderPacks($("packs"), true);
  initCustomBuy();
  renderOrders();
}

/** 크레딧 팩 목록. 첫 화면(로그인 전)과 계정 화면이 같은 목록을 쓴다. */
function renderPacks(box, clickable) {
  if (!box) return;
  box.replaceChildren();
  for (const p of PACKS) {
    const b = document.createElement("button");
    b.className = "pack" + (p.best ? " best" : "");
    b.innerHTML = `${p.best ? '<span class="tag">가장 많이 고릅니다</span>' : ""}
      <span class="n">${p.credits}크레딧</span>
      <span class="won">${won(p.won)}</span>
      <span class="per">악보 한 장당 ${won(Math.round(p.won / p.credits))}</span>`;
    if (clickable) b.addEventListener("click", () => openPay(p));
    else b.disabled = true;
    box.appendChild(b);
  }
}

/** 결제 내역. 실제 주문이 없으면 **지어내지 않고** 빈 상태를 보여 준다. */
function renderOrders() {
  const box = $("orders");
  box.replaceChildren();
  const list = state.orders || [];
  if (!list.length) {
    const p = document.createElement("p");
    p.className = "empty";
    p.textContent = "아직 결제 내역이 없습니다.";
    box.appendChild(p);
    return;
  }
  for (const o of list) {
    const r = document.createElement("div");
    r.className = "row-o";
    r.innerHTML = `<span class="when">${o.when}</span>
      <span class="what">${o.name}</span>
      <span class="amt">${won(o.won)}</span>`;
    box.appendChild(r);
  }
}

function openPay(pack) {
  state.pack = pack;
  $("pay-name").textContent = pack.name;
  $("pay-credits").textContent = `${pack.credits}개`;
  $("pay-amount").textContent = won(pack.won);
  $("pay-note").textContent =
    "결제 수단이 아직 연결되어 있지 않습니다. 지금은 화면 흐름만 확인할 수 있습니다.";
  $("pay").hidden = false;
}

/**
 * **원하는 만큼 낱개로 산다.** 묶음(10·50·200)이 안 맞는 사람이 있다 —
 * 이번 주에 3장만 필요한 경우처럼. 단가는 500원으로 묶음보다 비싸게 둔다.
 */
function initCustomBuy() {
  const n = $("buy-n"), out = $("buy-won"), go = $("buy-go");
  if (!n || !out || !go) return;
  // renderAccount 는 계정이 갱신될 때마다 돈다 — 듣는 이를 두 번 달면
  // 클릭 한 번에 결제창이 두 번 열린다.
  if (n.dataset.wired) return;
  n.dataset.wired = "1";
  const read = () => {
    const v = Math.floor(Number(n.value));
    return Number.isFinite(v) && v >= 1 && v <= MAX_BUY ? v : 0;
  };
  const paint = () => {
    const v = read();
    out.textContent = v ? won(v * UNIT_WON) : "—";
    go.disabled = !v;
  };
  n.addEventListener("input", paint);
  go.addEventListener("click", () => {
    const v = read();
    if (!v) return;
    openPay({ id: `c${v}`, credits: v, won: v * UNIT_WON,
              name: `${v}크레딧` });
  });
  paint();
}

function initPay() {
  const close = () => { $("pay").hidden = true; };
  $("pay-close").addEventListener("click", close);
  $("pay").addEventListener("click", (e) => { if (e.target === $("pay")) close(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") close(); });
  $("pay-go").addEventListener("click", () => {
    // **여기서 결제하는 척하지 않는다.** 크레딧을 늘리거나 내역을 만들면
    // 화면과 서버 장부가 어긋나고, 산 적 없는 기록이 남는다.
    $("pay-note").textContent =
      "결제 연동(포트원·카카오페이)과 로그인이 붙으면 여기서 결제창이 열립니다.";
    $("pay-go").disabled = true;
    setTimeout(() => { $("pay-go").disabled = false; }, 1200);
  });
}

/** 판독 결과의 모든 코드를 (단, 코드) 순서로 평탄화 */
function flatChords() {
  const out = [];
  for (const sys of state.extraction.systems) {
    for (const c of sys.chords) out.push({ sys: sys.index, chord: c });
  }
  return out;
}

/* ─────────────────────────── 업로드 ─────────────────────────── */

function wireUpload() {
  guardContent();
  initRouter();
  initPay();
  initLogin();
  initProfile();
  renderPacks($("packs-public"), false);
  renderBiz();
  const drop = $("drop");
  const pick = (input) => input.addEventListener("change", (e) => {
    if (e.target.files?.[0]) upload(e.target.files[0]);
  });
  pick($("file"));
  pick($("file-cam"));

  $("camera-hint").addEventListener("click", (e) => {
    e.preventDefault();
    $("file-cam").click();
  });

  for (const ev of ["dragenter", "dragover"]) {
    drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); });
  }
  for (const ev of ["dragleave", "drop"]) {
    drop.addEventListener(ev, () => drop.classList.remove("over"));
  }
  drop.addEventListener("drop", (e) => {
    e.preventDefault();
    const f = e.dataTransfer?.files?.[0];
    if (f) upload(f);
  });
}

async function upload(file) {
  if (!file.type.startsWith("image/")) {
    alert("이미지 파일만 올릴 수 있습니다.");
    return;
  }
  if (file.size > 24 * 1024 * 1024) return fail('24MB 이하 이미지를 올려 주세요.');
  state.uploadController?.abort();
  const controller = new AbortController();
  state.uploadController = controller;
  state.job = null;
  state.uploadFile = file;
  state.rendered = false;
  state.showOriginal = false;
  show("loading");
  $("load-title").textContent = "악보를 읽고 있어요";
  $("load-step").textContent = "오선과 코드를 찾는 중…";

  // 원본을 화면에 띄우기 위해 로컬에서만 URL을 만든다 (서버 저장 없음)
  const url = URL.createObjectURL(file);
  try {
    const original = await loadImage(url);
    if (original.naturalWidth * original.naturalHeight > 20000000) throw new Error('이미지 크기를 2천만 화소 이하로 줄여 주세요.');
    const job = await readScore(file, {
      signal: controller.signal, key: $('source-key').value, time: $('source-time').value,
      onProgress: (p) => {
        const stages = { queued: '처리 순서를 기다리는 중…', running: '음표와 리듬을 확인하는 중…', done: '판독을 마쳤습니다' };
        $('load-step').textContent = p.cached ? '이전에 읽은 결과를 불러오는 중…' : (stages[p.status] || '악보를 확인하는 중…');
        const progress = Number(p.progress);
        $('job-progress').value = Number.isFinite(progress) ? (progress <= 1 ? progress * 100 : progress) : 0;
      },
    });
    if (controller.signal.aborted) return;
    // 잔액은 **판독에서** 바뀐다 — 끝난 그 자리에서 다시 읽는다.
    refreshAccount().catch(() => {});
    state.image = original;
    state.job = job;
    state.extraction = job.result;
    const scale = Number(job.result.geometry?.scale) || 1;
    if (scale > 1.01) {
      const c = document.createElement('canvas');
      c.width = Math.round(original.naturalWidth * scale);
      c.height = Math.round(original.naturalHeight * scale);
      c.getContext('2d').drawImage(original, 0, 0, c.width, c.height);
      state.image = await loadImage(c.toDataURL('image/png'));
    }
    enterKeyScreen();
  } catch (err) {
    if (!controller.signal.aborted) fail(err.message);
  } finally {
    URL.revokeObjectURL(url);
  }
}

function fail(msg) {
  show("upload");
  alert(msg);
}

const loadImage = (src) => new Promise((ok, no) => {
  const img = new Image();
  img.onload = () => ok(img);
  img.onerror = () => no(new Error("이미지를 열 수 없습니다."));
  img.src = src;
});

/* ─────────────────────────── 키 선택 ─────────────────────────── */

const SEMI_RANGE = [-5, -4, -3, -2, -1, 0, 1, 2, 3, 4, 5];
const ALL_KEYS = ["C", "Db", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B",
                  "Am", "Bbm", "Bm", "Cm", "C#m", "Dm", "Ebm", "Em", "Fm",
                  "F#m", "Gm", "G#m"];

/**
 * 코드 목록으로 원조성을 추정한다.
 *
 * 조표를 읽어내는 건 저해상도에서 실패했으므로(README 참고) 코드에서 역산한다.
 * 마지막 코드가 으뜸음일 확률이 가장 높고, 그 다음이 첫 코드, 그 다음이 빈도다.
 * 추정이므로 사용자가 언제든 바꿀 수 있게 셀렉트를 함께 둔다.
 */
function guessKey(texts) {
  const score = new Map();
  const bump = (k, n) => score.set(k, (score.get(k) || 0) + n);

  texts.forEach((t, i) => {
    const c = parseChord(t);
    if (!c) return;
    const root = formatChord({ ...c, quality: "", bass: null, open: "", close: "" });
    const minor = /^m(?!aj)/.test(c.quality);
    const key = minor ? `${root}m` : root;
    bump(key, 1);
    if (i === texts.length - 1) bump(key, 4);
    if (i === 0) bump(key, 2);
  });

  let best = null;
  for (const [k, v] of score) if (!best || v > best[1]) best = [k, v];
  return best ? best[0] : "C";
}

/**
 * 곡 중간에 조가 바뀌는지 본다.
 *
 * 실제 사용자 악보에서 전반부는 G키(G/B C Em7 Am7 D/C), 후반부는 Bb키
 * (Bb F/A Gm7 Eb Cm7)였다. 추정기는 마지막 코드에 가중치를 크게 주므로 Bb를
 * 골랐고, 그 기준으로 **전체를 한 간격으로** 옮겨 전반부가 통째로 어긋났다.
 * 한 키로만 변환하는 지금 구조에서는 고칠 수 없으니 **알려는 줘야 한다.**
 */
function detectModulation(texts) {
  if (texts.length < 8) return null;
  const third = Math.max(3, Math.floor(texts.length / 3));
  const head = guessKey(texts.slice(0, third));
  const tail = guessKey(texts.slice(-third));
  return head === tail ? null : { head, tail };
}

function enterKeyScreen() {
  const ex = state.extraction;
  const texts = flatChords().map((f) => f.chord.text);
  // **서버의 조표 판정을 우선한다.** 서버는 검출기로 조표의 ♯/♭ 개수를 세는데,
  // 그게 코드 통계보다 확실하다(실측: 위싱 콘티의 `Bb C F Gm F/A`를 코드로는
  // Bb키로 추정했으나 조표는 ♭ 하나 — 실제는 F키다. 원조성이 틀리면 모든
  // 코드가 틀린다). 서버가 못 냈으면 브라우저가 코드로 추정한다.
  const fromServer = ex.keyGuess?.key || ex.meta?.key;
  const basis = ex.keyGuess?.basis || "";
  const guessed = fromServer || guessKey(texts);
  ex.meta = ex.meta || {};
  ex.meta.key = guessed;

  const sel = $("key-from");
  sel.innerHTML = "";
  for (const k of ALL_KEYS) {
    const o = document.createElement("option");
    o.value = k; o.textContent = `${k}키`;
    if (k === guessed) o.selected = true;
    sel.appendChild(o);
  }
  sel.onchange = () => {
    ex.meta.key = sel.value;
    // A changed source key must be checked by the server before credit use.
    ex.qualityGate = { status: 'needs_review', issues: ['원본 정보를 바꿨습니다. 다시 검사해 주세요.'] };
    $('quality').textContent = '원본 조성을 바꿨습니다. 아래에서 박자도 확인한 뒤 다시 검사해 주세요.';
    $('quality').hidden = false;
    refreshKeyScreen();
  };
  const how = basis.includes("조표") ? "조표와 코드로"
    : basis === "코드" ? "코드 진행으로" : "코드 진행으로";
  const conf = Number(ex.keyGuess?.confidence);
  const shaky = Number.isFinite(conf) && conf < 0.5;
  $("key-guess").textContent =
    (basis === '사용자 지정' ? `지정한 ${guessed}키를 사용합니다. ` : `${how} ${guessed}키로 추정했습니다. `)
    + (shaky ? "확실하지 않으니 꼭 확인해 주세요." : "다르면 바꿔주세요.");

  // 조가 바뀌는 악보는 한 키로 변환하면 절반이 어긋난다 — 반드시 알린다.
  $('key-hint').hidden = true;
  $('review-time').value = $('source-time').value;
  const mod = detectModulation(texts);
  if (mod) {
    const el = $("key-hint");
    if (el) {
      el.hidden = false;
      el.className = "alert";
      el.textContent =
        `이 악보는 중간에 조가 바뀌는 것 같습니다 (${mod.head}키 → ${mod.tail}키). ` +
        `지금은 한 키로만 변환하므로 절반은 어긋납니다. ` +
        `바뀌는 지점 전후를 나눠서 올려주세요.`;
    }
  }

  const key = guessed;
  $("orig-img").src = state.image.src;
  $("orig-badge").textContent = `원본 · ${key}키`;

  // 사진 품질 경고 — 조용히 일부만 처리하지 않고 알린다
  const q = ex.quality || {};
  const warn = $("quality");
  const gate = ex.qualityGate;
  // **막는 것과 알리는 것을 섞지 않는다.**
  //   blocking — 다시 그리지 못한 단이 있다. 상품이 안 나왔으니 보류한다.
  //   notes     — 다시 그려는 줬고 안내할 것이 있다(조표 추정 등).
  //                알리되 막지 않는다. 음가를 지어낸 것은 여기가 아니라
  //                blocking 이다 — 지어내면 돈을 받지 않는다.
  // 섞어 두면 "조표를 추정했습니다" 한 줄이 저장과 과금을 통째로 막는다.
  const txt = (v) => typeof v === 'string' ? v : v.message || v.reason || JSON.stringify(v);
  const blocking = (gate?.blocking || gate?.issues || []).map(txt);
  const notes = (gate?.notes || []).map(txt);
  const stuck = gate?.status !== 'ready';
  if (q.warning || stuck || notes.length) {
    // **지원하지 않는 악보는 "확인이 필요합니다"로 뭉뚱그리지 않는다.**
    // 고치면 될 것처럼 들리면 사용자가 계속 시도하게 된다.
    const unsupported = (gate?.twoVoice ?? 0) >= 0.35;
    const head = !stuck
      ? '읽었습니다. 아래는 확인하실 곳입니다.'
      : unsupported
        ? '이 악보는 아직 지원하지 않습니다. 크레딧은 차감되지 않았습니다.'
        : '원본 확인이 필요합니다. 저장 및 크레딧 차감은 보류됩니다.';
    const lines = stuck ? blocking : notes;
    warn.textContent = [q.warning, head, ...lines.slice(0, 8)].filter(Boolean).join('\n');
    warn.style.whiteSpace = 'pre-line';
    warn.classList.toggle('soft', !stuck);
    warn.hidden = false;
  } else {
    warn.hidden = true;
  }

  refreshKeyScreen();
  show("key");
}

function refreshKeyScreen() {
  const key = state.extraction.meta.key;
  $("orig-badge").textContent = `원본 · ${key}키`;
  buildChips(key);
  buildDirectSelect(key);
  selectSemitones(state.semitones, key);
}

function buildChips(fromKey) {
  const box = $("chips");
  box.innerHTML = "";
  for (const n of SEMI_RANGE) {
    let label;
    try {
      label = formatKey(planBySemitones(fromKey, n).toKey);
    } catch {
      continue;
    }
    const b = document.createElement("button");
    b.className = "chip";
    b.dataset.semi = String(n);
    b.innerHTML = `${n === 0 ? "원키" : (n > 0 ? `+${n}` : n)}<small>${label}</small>`;
    b.addEventListener("click", () => selectSemitones(n, fromKey));
    box.appendChild(b);
  }
}

function buildDirectSelect(fromKey) {
  const sel = $("key-direct");
  sel.innerHTML = "";
  for (const n of SEMI_RANGE) {
    let label;
    try {
      label = formatKey(planBySemitones(fromKey, n).toKey);
    } catch {
      continue;
    }
    const o = document.createElement("option");
    o.value = String(n);
    o.textContent = `${label}키로`;
    sel.appendChild(o);
  }
  sel.onchange = () => selectSemitones(Number(sel.value), fromKey);
}

function selectSemitones(n, fromKey) {
  state.semitones = n;
  for (const c of $("chips").children) {
    c.classList.toggle("on", Number(c.dataset.semi) === n);
  }
  $("key-direct").value = String(n);
}

/* ─────────────────────── 코드 확인 (낮은 신뢰도) ─────────────────────── */

// Haiku의 신뢰도는 잘 보정돼 있지 않다. 애매하면 0.85를, 확실하면 1.0을 준다.
// 그래서 유의미한 경계는 0.9인데, 그러면 43개 중 19개가 걸려 확인 화면이
// 고문이 된다(실측). 임계값은 0.9로 두고 **낮은 순 상한**으로 개수를 자른다.
// 0.8로 낮추면 0.85가 전부 통과해 확인 화면이 아예 안 뜬다 — 둘 다 실측했다.
const CONF_THRESHOLD = 0.9;
const CONF_MAX = 5;

function startConfirmOrRender() {
  state.showOriginal = false;
  state.pending = flatChords()
    .map((f, i) => ({ ...f, i }))
    .filter((f) => (f.chord.confidence ?? 1) < CONF_THRESHOLD)
    .sort((a, b) => (a.chord.confidence ?? 1) - (b.chord.confidence ?? 1))
    .slice(0, CONF_MAX);
  state.pendingAt = 0;

  if (state.pending.length === 0) {
    safeRender();
  } else {
    showConfirm();
  }
}

/* ── 코드 확인 화면 ───────────────────────────
   설계 이유(실측 제보): 예전 화면은 "인식된 텍스트" 입력칸을 먼저 보여줬다.
   그런데 코드는 대부분 맞으므로, 맞는 경우에도 편집 도구를 마주하게 되어
   "뭐 눌러?"가 됐다. 그래서 **맞음/수정만 먼저 묻고**, 수정할 때만 조각
   버튼을 펼친다. 휴대폰에서 코드를 타이핑하는 것보다 조각을 고르는 게 빠르다. */

const ED_ROOTS = ["C", "D", "E", "F", "G", "A", "B"];
const ED_ACCS = [["", "없음"], ["b", "♭"], ["#", "♯"]];
// 실제 찬양 악보에서 나온 순서대로. 실측: m7·maj7·sus4·2 가 가장 잦다.
const ED_QUALS = [["", "메이저"], ["m", "m"], ["7", "7"], ["m7", "m7"],
                  ["maj7", "maj7"], ["sus", "sus"], ["sus4", "sus4"],
                  ["2", "2"], ["add9", "add9"], ["dim", "dim"],
                  ["aug", "aug"], ["7+5", "7+5"], ["m7b5", "m7b5"],
                  ["6", "6"], ["9", "9"]];

/** 편집기 상태 — 조각을 합쳐 코드 글자를 만든다 */
const ed = { root: "C", acc: "", qual: "", bass: "" };

function edText() {
  return ed.root + ed.acc + ed.qual + (ed.bass ? `/${ed.bass}` : "");
}

/** 읽은 글자를 조각으로 분해한다. 못 알아보면 근음만 세운다. */
function edLoad(text) {
  const m = /^([A-G])([#b]?)([^/]*)(?:\/([A-G][#b]?))?$/.exec((text || "").trim());
  if (m) {
    ed.root = m[1]; ed.acc = m[2]; ed.qual = m[3] || ""; ed.bass = m[4] || "";
  } else {
    ed.root = "C"; ed.acc = ""; ed.qual = ""; ed.bass = "";
  }
}

function edChip(label, on, onClick) {
  const b = document.createElement("button");
  b.className = "chip flat" + (on ? " on" : "");
  b.textContent = label;
  b.addEventListener("click", onClick);
  return b;
}

function edRender() {
  const fill = (id, items, cur, set) => {
    const box = $(id);
    box.innerHTML = "";
    for (const [val, label] of items) {
      box.appendChild(edChip(label, val === cur, () => { set(val); edRender(); }));
    }
  };
  fill("ed-root", ED_ROOTS.map((r) => [r, r]), ed.root, (v) => { ed.root = v; });
  fill("ed-acc", ED_ACCS, ed.acc, (v) => { ed.acc = v; });
  fill("ed-qual", ED_QUALS, ed.qual, (v) => { ed.qual = v; });
  // 베이스는 "없음" + 12음. 분수코드는 근음과 다른 음이 오는 게 보통이다.
  const bassItems = [["", "없음"]].concat(
    ED_ROOTS.flatMap((r) => [[r, r], [`${r}b`, `${r}♭`]]));
  fill("ed-bass", bassItems, ed.bass, (v) => { ed.bass = v; });
  $("ed-preview").textContent = edText();
  $("conf-input").value = edText();
}

function showConfirm() {
  const total = state.pending.length;
  const at = state.pendingAt;
  if (at >= total) {
    // **오류를 삼키지 않는다.** 여기서 예외가 나면 마지막 "맞음"을 눌러도
    // 아무 일도 일어나지 않는 것처럼 보인다 — 사용자는 버튼이 고장 났다고
    // 판단할 수밖에 없다(실측 제보). 무엇이 실패했는지 화면에 알린다.
    safeRender();
    return;
  }

  const item = state.pending[at];
  const flat = flatChords();
  const auto = flat.length - total;

  $("confirm-sub").textContent =
    `${total}개만 확인해 주세요. 나머지 ${auto}개는 자동으로 읽었습니다.`;
  $("confirm-bar").style.width = `${(at / total) * 100}%`;
  $("conf-badge").textContent =
    `신뢰도 ${Math.round((item.chord.confidence ?? 1) * 100)}%`;
  $("conf-read").textContent = item.chord.text;
  $("conf-input").value = item.chord.text;

  // 처음엔 묻기만 한다
  $("conf-ask").hidden = false;
  $("conf-editor").hidden = true;
  $("conf-input").hidden = true;

  drawCrop(item.chord.box);
  show("confirm");
}

/** "수정"을 누르면 조각 버튼을 펼친다 */
function openEditor() {
  const item = state.pending[state.pendingAt];
  if (!item) return;
  edLoad(item.chord.text);
  edRender();
  $("conf-ask").hidden = true;
  $("conf-editor").hidden = false;
}

/** 흔한 오독 후보 — maj/m 혼동이 실측에서 가장 잦았다 */
function altGuesses(text) {
  const out = new Set([text]);
  if (text.includes("maj")) out.add(text.replace("maj", "m"));
  else if (/m\d/.test(text)) out.add(text.replace(/m(\d)/, "maj$1"));
  return [...out];
}

function drawCrop(box) {
  const pad = Math.max(2, Math.round(box.h * 0.2));
  const sx = Math.max(0, box.x - pad);
  const sy = Math.max(0, box.y - pad);
  const sw = Math.min(state.image.naturalWidth - sx, box.w + pad * 2);
  const sh = Math.min(state.image.naturalHeight - sy, box.h + pad * 2);

  const scale = Math.min(8, Math.max(3, 120 / sh));
  const cv = $("crop");
  cv.width = Math.round(sw * scale);
  cv.height = Math.round(sh * scale);
  const ctx = cv.getContext("2d");
  ctx.imageSmoothingQuality = "high";
  ctx.fillStyle = "#fff";
  ctx.fillRect(0, 0, cv.width, cv.height);
  ctx.drawImage(state.image, sx, sy, sw, sh, 0, 0, cv.width, cv.height);
}

/**
 * 렌더 진입점. **새로 그리는 경로를 먼저 쓴다.**
 *
 * 새로 그리기(MusicXML → Verovio)는 픽셀 이동의 문제군을 통째로 없앤다 —
 * 회색 띠·코드 잔상·음표 손상·못 고치는 임시표. 구조 데이터가 없거나
 * 새로 그리다 실패하면 예전 픽셀 경로로 물러난다(아무것도 안 보여주는 것보다
 * 코드만 변환된 악보라도 주는 편이 낫다).
 *
 * 오류를 삼키지 않는다 — 여기서 조용히 실패하면 사용자에게는 "마지막
 * 맞아요를 눌러도 아무 일도 안 일어난다"로 보인다(실측 제보).
 */
async function safeRender() {
  state.rendered = false;
  try {
    if (!state.showOriginal) {
      const why = whyNoRedraw(state.extraction);
      if (why === null) {
        try {
          await redrawPath();
          return;
        } catch (err) {
          show('key');
          const box = $('quality');
          box.textContent = err.message || '악보를 다시 그리지 못했습니다';
          box.style.whiteSpace = 'pre-line';
          box.hidden = false;
          return;
        }
      } else {
        show('key');
        $('quality').textContent = `원본 확인이 필요합니다: ${why}`;
        $('quality').hidden = false;
        return;
      }
    }
    renderResult();
  } catch (err) {
    console.error("렌더 실패:", err);
    fail(`변환 중 오류가 발생했습니다.\n\n${err && err.message ? err.message : err}`);
  }
}

/** MusicXML로 다시 조판해서 결과 화면을 채운다. */
async function redrawPath() {
  const ex = state.extraction;
  const fromKey = ex.meta?.key || "C";
  const plan = planBySemitones(fromKey, state.semitones);
  const live = flatChords().filter((f) => !f.chord.dropped);
  const mapped = transposeChords(
    live.map((f) => f.chord.text), plan, { simplify: true });

  const r = await redraw($("out"), ex, plan, mapped, state.image);
  // **검사를 통과 못 한 미리보기에는 표시를 남긴다.** 그 판독은 크레딧을
  // 돌려줬으므로 값을 안 받은 결과다 — 캔버스는 우클릭으로 저장되니
  // 표시가 없으면 "실패로 만들고 화면에서 가져가기"가 공짜 경로가 된다.
  // 통과한 결과에는 붙이지 않는다. 값을 치렀으면 깨끗한 악보를 받아야 한다.
  markUnverified($("out"), ex);
  // **안 맞는 마디는 사람이 고칠 수 있게 한다.** 자동 역산이 포기한 것만
  // 남으므로(rebuild.fitdur), 여기서 막히면 사용자가 손쓸 방법이 없다.
  const fix = $("fix-beats");
  fix.replaceChildren();
  const panel = fixPanel(ex.struct, () => { redrawPath(); });
  if (panel) fix.append(panel);
  state.rendered = true;
  updateExportState();

  $("res-title").textContent =
    `${formatKey(plan.fromKey)}키 → ${formatKey(plan.toKey)}키 미리보기`;
  $("res-sub").textContent =
    `${r.report.systems}단 · ${r.report.measures}마디 — ` +
    `원본과 대조한 뒤 저장해 주세요`;

  const warn = $("res-warn");
  const bad = r.notes.filter((t) => t.startsWith("⚠️"));
  const summary = r.notes[r.notes.length - 1];
  warn.className = bad.length ? "alert" : "alert info";
  // **요약을 늘 보여준다.** 경고만 띄우면 무엇이 몇 개 됐는지 알 수 없다.
  // **경고는 줄을 나눈다.** 박자 경고는 어느 마디인지까지 적어 두 줄이라,
  // 가운뎃점으로 이어 붙이면 다른 경고와 뒤엉켜 읽히지 않는다.
  warn.textContent = bad.length
    ? `${bad.join("\n")}\n${summary}`
    : `악보를 새로 그렸습니다 — ${summary}`;
  warn.style.whiteSpace = "pre-line";
  warn.hidden = false;

  $("copyright-line").textContent = copyrightNote(ex);
  $("t-orig").classList.toggle("on", state.showOriginal);
  $("t-new").classList.toggle("on", !state.showOriginal);
  show("result");
}

function commitConfirm() {
  // 마지막 항목을 확정한 뒤 한 번 더 눌리면 인덱스가 범위를 넘는다.
  // 그때 죽으면 "버튼이 고장 났다"로 보인다 — 조용히 무시한다.
  if (state.pendingAt >= state.pending.length) return;
  const item = state.pending[state.pendingAt];
  const text = $("conf-input").value.trim();
  // 원본 구조 데이터를 직접 수정한다 — 확인이 끝나면 신뢰도를 1로 올린다
  item.chord.text = text;
  item.chord.confidence = 1;
  if (!text) item.chord.dropped = true;
  state.pendingAt += 1;
  showConfirm();
}

function wireConfirm() {
  // "맞음" 은 읽은 글자를 그대로 확정한다
  $("conf-ok").addEventListener("click", () => {
    const item = state.pending[state.pendingAt];
    if (item) $("conf-input").value = item.chord.text;
    commitConfirm();
  });
  $("conf-edit").addEventListener("click", openEditor);
  $("ed-save").addEventListener("click", () => {
    $("conf-input").value = edText();
    commitConfirm();
  });
  $("ed-none").addEventListener("click", () => {
    $("conf-input").value = "";      // 빈 값 = 코드 아님 (아래에서 dropped 처리)
    commitConfirm();
  });
  // 조각으로 안 되는 형태(예: C6/9, Bsus2add4)는 직접 입력
  $("ed-typed").addEventListener("click", () => {
    const inp = $("conf-input");
    inp.hidden = !inp.hidden;
    if (!inp.hidden) inp.focus();
  });
  $("conf-input").addEventListener("input", () => {
    $("ed-preview").textContent = $("conf-input").value || "—";
  });
  $("conf-skip").addEventListener("click", () => { state.pendingAt += 1; showConfirm(); });
  $("conf-all").addEventListener("click", () => {
    for (const p of state.pending) p.chord.confidence = 1;
    state.pendingAt = state.pending.length;
    safeRender();
  });
}

/* ─────────────────────── 렌더 (파이썬 overlay.py의 canvas 포팅) ─────────────────────── */

/** 미검증 미리보기에 사선 표시를 얹는다. 통과한 결과는 그대로 둔다. */
function markUnverified(canvas, ex) {
  if (ex?.qualityGate?.status === 'ready') return;
  const g = canvas.getContext('2d');
  const step = Math.max(180, Math.round(canvas.width / 5));
  g.save();
  g.globalAlpha = 0.16;
  g.fillStyle = '#a8362b';
  g.font = `600 ${Math.round(step / 7)}px "Pretendard Variable", sans-serif`;
  g.textAlign = 'center';
  g.textBaseline = 'middle';
  g.translate(canvas.width / 2, canvas.height / 2);
  g.rotate(-Math.PI / 9);
  const label = '검사 미통과 · mut';
  for (let y = -canvas.height; y < canvas.height; y += step * 0.55) {
    for (let x = -canvas.width; x < canvas.width; x += step * 1.5) {
      g.fillText(label, x, y);
    }
  }
  g.restore();
}

function renderResult() {
  // Only the original-image toggle uses this path. Transformed output always
  // goes through canonical MusicXML assembly and its unresolved-score gate.
  if (!state.showOriginal) throw new Error('변환 미리보기를 다시 만들어 주세요.');
  state.rendered = false;
  const originalCanvas = $('out');
  originalCanvas.width = state.image.naturalWidth;
  originalCanvas.height = state.image.naturalHeight;
  originalCanvas.getContext('2d').drawImage(state.image, 0, 0);
  $('res-title').textContent = '원본 악보';
  $('res-sub').textContent = '변환 탭에서 미리보기를 확인해 주세요';
  $('res-warn').hidden = true;
  $('t-orig').classList.add('on');
  $('t-new').classList.remove('on');
  updateExportState();
  show('result');
}

/**
 * PDF에 넣을 페이지 캔버스를 만든다: 변환된 악보 + 아래쪽 고지 띠.
 *
 * 고지가 한글이라 PDF 표준 폰트(Helvetica)로는 못 그린다. 폰트를 임베딩하는
 * 대신 캔버스에 그려 이미지로 넣는다 — 어차피 페이지 전체가 이미지 한 장이다.
 *
 * 고지는 저작권 설계상 필수다: 출력물이 개인 연습용임을 명시하고 원본
 * 저작권 표기를 보존한다.
 */
/**
 * 결과물에 붙일 **저작권 문구**.
 *
 * 설계상 원본 표기는 두 경로로 보존된다:
 *   · 머리글(제목·부제·작곡자·ⓒ)은 **원본 픽셀 그대로** 오려 붙인다
 *     (server/serve.py 의 head_cut). 다시 조판해 만들 수 없는 정보다.
 *   · 판독에서 ⓒ 문자열을 따로 얻으면 meta.copyright 로 들어온다.
 *
 * 예전엔 meta.copyright 만 찍었는데 **그걸 채우는 코드가 없어서** 늘 빈
 * 줄이었다. 실제로 출력물이 무엇을 담고 있는지를 쓰는 게 맞다.
 */
function copyrightNote(ex) {
  const c = ex?.meta?.copyright;
  if (c) return c;
  return "원본의 제목·작곡자·저작권 표기는 이미지 그대로 옮겨집니다";
}


function buildPageCanvas(plan) {
  const src = $("out");
  const scale = src.width / 640;          // 고지 글씨를 악보 폭에 맞춘다
  const pad = Math.round(10 * scale);
  const line = Math.round(13 * scale);
  const notice = [
    `${formatKey(plan.fromKey)}키 → ${formatKey(plan.toKey)}키 · 개인 연습용 · 재배포 금지`,
  ];
  notice.push(copyrightNote(state.extraction));

  const stripH = pad * 2 + line * notice.length;
  const page = document.createElement("canvas");
  page.width = src.width;
  page.height = src.height + stripH;

  const ctx = page.getContext("2d");
  // 종이색으로 배경을 깐다 — PDF는 투명을 검게 합성할 수 있다
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, page.width, page.height);
  ctx.drawImage(src, 0, 0);

  ctx.fillStyle = "#6b6b78";
  ctx.textAlign = "center";
  ctx.textBaseline = "top";

  // 폰트 크기를 줄여 폭에 맞춘다. fillText의 maxWidth 인자는 글자를 가로로
  // 찌그러뜨리므로 쓰지 않는다 — 원본 저작권 표기는 읽을 수 있어야 한다.
  const avail = page.width - pad * 2;
  const base = Math.max(7, Math.round(9.5 * scale));
  notice.forEach((t, i) => {
    let size = base;
    ctx.font = `${size}px Manrope, "Pretendard Variable", sans-serif`;
    while (size > 5 && ctx.measureText(t).width > avail) {
      size -= 1;
      ctx.font = `${size}px Manrope, "Pretendard Variable", sans-serif`;
    }
    ctx.fillText(t, page.width / 2, src.height + pad + i * line);
  });
  return page;
}

function download(blob, name) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 60000);
}

function wireResult() {
  $("t-orig").addEventListener("click", () => { state.showOriginal = true; renderResult(); });
  $("t-new").addEventListener("click", () => { state.showOriginal = false; safeRender(); });
  $("again").addEventListener("click", () => { state.showOriginal = false; show("key"); });

  $('dl-png').addEventListener('click', () => exportScore('png'));
  $('dl-pdf').addEventListener('click', () => exportScore('pdf'));

  $("back").addEventListener("click", () => {
    const cur = SCREENS.find((s) => !$(`s-${s}`).hidden);
    if (["account", "faq", "contact", "terms", "privacy", "oss"].includes(cur)) { go("/"); return; }
    if (cur === "result") show("key");
    else if (cur === "confirm") show("key");
    else show("upload");
  });
}

/**
 * 악보를 화면에서 **끌어가거나 우클릭으로 저장**하는 경로를 막는다.
 *
 * 솔직히 적어 둔다: 이건 **작정한 사람은 못 막는다.** 개발자도구·캔버스
 * toDataURL·화면 캡처가 그대로 남는다. 진짜 방어선은 따로 있다 —
 * 과금을 판독 시점으로 옮겼으므로(server/jobs.py) 미리보기를 가져가도
 * 이미 값을 치른 결과다. 여기서 막는 건 "무심코 끌어가기" 정도다.
 *
 * 업로드 드롭존은 **살려야 한다.** dragover/drop 을 통째로 막으면 파일을
 * 끌어다 놓는 길이 사라진다. 그래서 끌어**내기**(dragstart)만 막는다.
 */
function guardContent() {
  const isMedia = (el) => el instanceof HTMLImageElement
    || el instanceof HTMLCanvasElement
    || (el?.closest?.('.sheet-wrap, .crop-wrap') != null);

  document.addEventListener('contextmenu', (e) => {
    if (isMedia(e.target)) e.preventDefault();
  });
  // 끌어내기 금지. 드롭존으로 끌어**오는** 것은 건드리지 않는다.
  document.addEventListener('dragstart', (e) => {
    if (isMedia(e.target)) e.preventDefault();
  });
  // 페이지 밖으로 떨어뜨렸을 때 브라우저가 파일로 여는 것도 막는다
  for (const ev of ['dragover', 'drop']) {
    document.addEventListener(ev, (e) => {
      if (!e.target.closest?.('#drop')) e.preventDefault();
    });
  }
}

function updateExportState() {
  const ready = state.extraction?.qualityGate?.status === 'ready';
  for (const id of ['dl-png', 'dl-pdf']) $(id).disabled = !ready || !state.rendered || state.exportBusy;
  // 차감은 **판독**에서 이미 끝났다. 저장은 값을 치른 결과를 받아 가는
  // 것이므로 공짜다 — 저장에서 깎으면 미리보기를 화면에서 가져가는 쪽이
  // 이득이 되어 구조가 어긋난다.
  // **지어낸 자리가 있으면 애초에 차감되지 않는다**(local_reader.quality_gate).
  // 그러니 여기서 "짐작했지만 받았습니다"를 말할 일이 없다 — 통과했다면
  // 지어낸 곳이 없다는 뜻이다. 약속을 한 줄로 유지한다.
  $('credit-notice').textContent = ready
    ? '이 판독에 크레딧 1개를 사용했습니다 · 키 변경과 저장은 몇 번이든 추가 차감 없음'
    : '확인이 필요한 결과라 차감하지 않았습니다 — 화면은 그대로 쓰실 수 있습니다.';
}

function initProfile() {
  const f = $('profile');
  if (!f) return;
  f.addEventListener('submit', async (e) => {
    e.preventDefault();
    const msg = $('pf-msg');
    msg.textContent = '저장 중…';
    try {
      await request('/api/profile', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          email: $('pf-email').value, label: $('pf-label').value }),
      });
      await refreshAccount();
      renderAccount();
      msg.textContent = '저장했습니다';
    } catch (err) {
      msg.textContent = err.message || '저장하지 못했습니다';
    }
    setTimeout(() => { msg.textContent = ''; }, 4000);
  });
}

function initLogin() {
  const out = $('logout');
  if (out) out.addEventListener('click', async () => {
    out.disabled = true;
    try { await request('/api/logout', { method: 'POST' }); } catch (e) { /* 그래도 홈으로 */ }
    // 잔액·잠금 표시가 전부 계정에 딸려 있어서, 통째로 다시 읽는 게 확실하다
    location.href = '/';
  });
  for (const b of document.querySelectorAll('[data-sso]')) {
    b.addEventListener('click', () => { location.href = '/auth/' + b.dataset.sso; });
  }
  // 회원가입 — 필수 항목을 다 체크해야 버튼이 열린다
  const boxes = [...document.querySelectorAll('.agree .ag')];
  const all = $('ag-all');
  const sync = () => {
    const ok = boxes.every((c) => c.checked);
    if (all) all.checked = ok;
    // 간편가입은 묶지 않는다 — 카카오·네이버 동의 화면을 거치고 돌아와
    // 우리 약관 동의를 따로 받는다. 여기 체크박스는 **아이디 가입 폼의 것**이다.
    if ($('su-go')) $('su-go').disabled = !ok;
  };
  for (const c of boxes) c.addEventListener('change', sync);
  if (all) all.addEventListener('change', () => {
    for (const c of boxes) c.checked = all.checked;
    sync();
  });
  sync();
  // 로그인 실패 안내는 주소에 실려 돌아온다
  const p = new URLSearchParams(location.search).get('login');
  if (p && $('kakao-msg')) {
    $('kakao-msg').textContent = p;
    history.replaceState({}, '', location.pathname);
  }
  const f = $('login');
  if (!f) return;
  f.addEventListener('submit', async (e) => {
    e.preventDefault();
    const msg = $('login-msg');
    msg.textContent = '확인하는 중…';
    try {
      const r = await fetch('/api/login', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: $('login-id').value, pw: $('login-pw').value }),
      });
      if (!r.ok) {
        msg.textContent = (await r.json().catch(() => ({}))).error || '로그인하지 못했습니다.';
        return;
      }
      msg.textContent = '';
      await refreshAccount();
      go('/');
    } catch (err) {
      msg.textContent = '로그인하지 못했습니다.';
    }
  });

  // 회원가입 — 간편 로그인으로 처음 들어온 사람은 동의만 받으면 된다
  const su = $('signup');
  if (su) su.addEventListener('submit', async (e) => {
    e.preventDefault();
    const msg = $('su-msg');
    msg.textContent = '처리하는 중…';
    const welcome = !!state.account?.needsAgree;
    try {
      await request(welcome ? '/api/agree' : '/api/signup', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          id: $('su-id').value, pw: $('su-pw').value,
          email: $('su-email').value, agree: true }),
      });
      msg.textContent = '';
      await refreshAccount();
      go('/');
    } catch (err) {
      msg.textContent = err.message || '가입하지 못했습니다.';
    }
  });
}

// 간편 로그인으로 **처음** 들어온 사람은 아이디·비밀번호를 만들 필요가
// 없다. 약관 동의만 받는다.
function applyWelcome() {
  const welcome = !!state.account?.needsAgree;
  const on = (id, show) => { const el = $(id); if (el) el.hidden = !show; };
  on('su-welcome', welcome);
  on('su-intro', !welcome);
  on('su-or', !welcome);
  on('su-sso', !welcome);
  for (const id of ['su-id', 'su-pw', 'su-email']) {
    const el = $(id);
    if (el) { el.closest('.field').hidden = welcome; el.disabled = welcome; }
  }
  if ($('su-go')) $('su-go').textContent = welcome ? '동의하고 시작하기' : '가입하고 시작하기';
}

function applyLock() {
  // 계정 잠금 중이면 업로드 자리를 안내로 바꾼다. 마스터는 그대로 쓴다.
  const a = state.account;
  const locked = !!a?.authRequired && !a?.authed;
  const box = $('locked'), drop = $('drop');
  if (box) box.hidden = !locked;
  if (drop) drop.hidden = locked;
  // 간편 로그인 버튼은 서버가 준비됐다고 할 때만 보여 준다
  let any = false;
  for (const b of document.querySelectorAll('[data-sso]')) {
    b.hidden = !state.health?.[b.dataset.sso];
    any = any || !b.hidden;
  }
  if ($('sso-none')) $('sso-none').hidden = any;
  applyWelcome();
  for (const id of ['file', 'file-cam']) {
    const el = $(id); if (el) el.disabled = locked;
  }
}

async function refreshAccount() {
  const account = await request('/api/account');
  state.account = account;
  const locked = !!account.authRequired && !account.authed;
  $('balance').textContent = account.master ? '마스터 · 무제한'
    : locked ? '로그인 필요'
    : `체험 ${account.balance}크레딧`;
  // 로그인 전에는 신원을 안 보여 준다 — 보여 줄 신원이 없다
  const av = $('who');
  if (av) {
    av.hidden = locked;
    paintAvatar(av, $('who-photo'),
                account.master ? { name: '마스터' } : account);
  }
  if (!$('s-account').hidden) renderAccount();
  applyLock();
  return account;
}

async function exportScore(format) {
  if (state.exportBusy || !state.rendered || state.extraction?.qualityGate?.status !== 'ready') return;
  state.exportBusy = true;
  updateExportState();
  // Prevent changing the preview while its export is being prepared.
  for (const id of ['t-orig', 't-new', 'again', 'back']) $(id).disabled = true;
  try {
    const plan = planBySemitones(state.extraction.meta.key, state.semitones);
    const canvas = buildPageCanvas(plan);
    const blob = format === 'pdf' ? buildPdf([await canvasToJpeg(canvas)])
      : await new Promise((resolve, reject) => canvas.toBlob(b => b ? resolve(b) : reject(new Error('이미지를 만들지 못했습니다.')), 'image/png'));
    // 판독에서 이미 정산됐다. 저장은 서버 장부를 건드리지 않는다.
    state.job.committed = true;
    download(blob, `mut_${formatKey(plan.toKey)}키.${format}`);
  } catch (err) {
    alert(`저장하지 못했습니다: ${err.message}`);
  } finally {
    state.exportBusy = false;
    for (const id of ['t-orig', 't-new', 'again', 'back']) $(id).disabled = false;
    updateExportState();
  }
}

/* ─────────────────────────── 시작 ─────────────────────────── */

$("go").addEventListener("click", startConfirmOrRender);
wireUpload();
wireConfirm();
wireResult();
void parseKey;
// **주소를 따른다.** 예전엔 무조건 upload 를 띄워서, /account 로 새로고침하면
// 주소만 계정이고 화면은 변환이었다.
go(location.pathname, false);
for (const key of ALL_KEYS) {
  const option = document.createElement('option');
  option.value = key; option.textContent = `${key}키`;
  $('source-key').appendChild(option);
}
/**
 * **첫 화면 덮개를 걷는다.** 계정·서버 상태를 알기 전에 화면을 보여 주면
 * 크레딧·아바타·잠금이 뒤늦게 끼어들어 레이아웃이 튄다. 두 번 불러도
 * 안전하고, 요청이 실패해도 반드시 걷는다 — 덮개가 남으면 아무것도
 * 못 하는 화면이 된다.
 */
function hideBoot() {
  const el = $('boot');
  if (!el || el.classList.contains('gone')) return;
  el.classList.add('gone');
  // transition 이 끝나면 접근성 트리에서도 치운다
  setTimeout(() => el.remove(), 400);
}
// 서버가 늦거나 멈춰도 덮개에 갇히지 않는다
setTimeout(hideBoot, 4000);

request('/api/health').then(async health => {
  state.health = health;
  applyLock();
  $('service-mode').textContent = health.mode === 'local' ? '로컬 자동 판독 · 외부 API 0회' : 'AI 판독 모드';
  // **어디까지 나가는지 정확히 적는다.** ai 모드는 단별 개수를 물으려고
  // 오선 조각을 보낸다 — "외부 API를 호출하지 않습니다"는 거짓이 된다.
  const pn = $('privacy-note');
  if (pn) {
    pn.textContent = health.mode === 'local'
      ? '이미지는 로컬 메모리에서 처리 후 해제됩니다. 외부 AI API를 호출하지 않습니다'
      : '이미지는 저장하지 않습니다. 단별 음표 수를 세기 위해 오선 조각만 AI에 보냅니다';
  }
  await refreshAccount();
  hideBoot();
}).catch(() => {
  $('service-mode').textContent = '판독 서버 연결 필요';
  $('balance').textContent = '오프라인';
  hideBoot();
});
$('recheck').addEventListener('click', () => {
  $('source-key').value = $('key-from').value;
  $('source-time').value = $('review-time').value;
  if (state.uploadFile) upload(state.uploadFile);
});
