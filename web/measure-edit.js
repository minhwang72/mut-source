// **확인할 마디를 짚고, 사람이 고친다.**
//
// 자동 판독은 마디 몇 개를 꾸준히 틀리고, 시판 앱 중 1등도 "애매한 곳은 묻는다"로
// 판다. 그래서 판독이 자신 없는 마디(rebuild.assemble 의 report.flags)를 악보 위에
// 노랗게 짚고, 누르면 원본 조각과 고친 모습을 나란히 보며 음표·코드·마디를
// 고친다. 고친 것은 struct 에 그대로 적고 다시 그린다 — 렌더 경로는 하나다.
//
// 고친 내용이 struct 에 남기는 표시:
//   n.base       사람이 정한 오선 위 자리('G4'). 머리 좌표보다 앞선다
//   sysd.confirmed  사람이 원본과 대 본 마디 번호들 — 확인할 마디에서 빠진다
//
// 편집기 화면은 **원조(원본 키)** 로 보여 준다. 원본 조각과 같은 키여야 한 음씩
// 대 볼 수 있다. 변환은 다시 그릴 때 한다.

import { DUR, build } from './musicxml.js';
import { assemble, chordsByStaff, fullOf, measureEdges } from './rebuild.js';
import { toolkit } from './verovio-page.js';
import { fifths, parseChord, planBySemitones } from './engine/index.js';

const STEPS = 'CDEFGAB';
const LENGTHS = [['whole', '온음표'], ['half', '2분'], ['quarter', '4분'], ['eighth', '8분'], ['16th', '16분']];
const WORD = { whole: '온', half: '2분', quarter: '4분', eighth: '8분', '16th': '16분' };
const ACCS = [['key', '조표대로'], ['sharp', '♯ 올림'], ['flat', '♭ 내림'], ['natural', '♮ 제자리']];
// 오선 아래 덧줄 셋(F3)부터 위 덧줄 넷(C7)까지 — 그 밖은 멜로디 악보에 없다
const LOW = STEPS.indexOf('F') + 7 * 3, HIGH = STEPS.indexOf('C') + 7 * 7;

const absOf = (base) => {
  const m = /^([A-G])(-?\d+)$/.exec(base || '');
  return m ? STEPS.indexOf(m[1]) + 7 * Number(m[2]) : null;
};
const baseOf = (abs) => STEPS[((abs % 7) + 7) % 7] + Math.floor(abs / 7);
const len = (n) => (DUR[n.duration] ?? DUR.quarter) * (n.dotted ? 1.5 : 1);
const pretty = (p) => String(p || '').replace(/#/g, '♯').replace(/b(?=-?\d)/g, '♭');
const el = (tag, cls, text) => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
};
const fmtBeats = (v) => String(+v.toFixed(2));

export class Review {
  /**
   * layer   악보 캔버스 위에 겹친 div — 마디 버튼을 여기 단다
   * dialog  <dialog id="medit">
   * get     () => ({ ex, image }) 지금 판독 결과와 원본 이미지
   * rerender  () => Promise — 고친 struct 로 큰 악보를 다시 그린다
   * onChange  () => void — 남은 확인 수가 바뀌었다
   */
  constructor({ layer, dialog, get, rerender, onChange }) {
    this.layer = layer;
    this.dlg = dialog;
    this.get = get;
    this.rerender = rerender;
    this.onChange = onChange || (() => {});
    this.flags = new Map();
    this.boxes = [];
    this.cur = null;
    this.sel = 0;
    this.stale = false;        // 큰 악보가 struct 보다 뒤처졌나
    this.busy = false;
    this.q = (sel) => this.dlg.querySelector(sel);
    this.wire();
  }

  /* ── 큰 악보 위 마디 버튼 ── */

  /** 다시 그릴 때마다 부른다. boxes: redraw 의 마디 상자, flags: report.flags */
  update({ boxes, flags, width, height }) {
    this.boxes = boxes || [];
    this.flags = new Map((flags || []).map((f) => [`${f.system}:${f.measure}`, f]));
    this.W = width; this.H = height;
    this.paint();
    this.onChange();
  }

  paint() {
    const { ex } = this.get();
    const order = [...this.flags.keys()];
    this.layer.replaceChildren();
    for (const b of this.boxes) {
      const [si, mi] = b.src;
      const k = `${si}:${mi}`;
      const btn = el('button', 'mbox');
      btn.type = 'button';
      Object.assign(btn.style, {
        left: `${(b.x / this.W) * 100}%`, top: `${(b.y / this.H) * 100}%`,
        width: `${(b.w / this.W) * 100}%`, height: `${(b.h / this.H) * 100}%`,
      });
      const f = this.flags.get(k);
      const done = (ex.struct.systems[si]?.confirmed || []).includes(mi);
      if (f) {
        btn.classList.add('flag');
        const no = el('span', 'mbox-no', String(order.indexOf(k) + 1));
        no.setAttribute('aria-hidden', 'true');
        btn.append(no);
        btn.setAttribute('aria-label', `${si + 1}단 ${mi}마디 — 확인 필요: ${f.reasons[0].text}`);
      } else {
        if (done) btn.classList.add('done');
        btn.setAttribute('aria-label', `${si + 1}단 ${mi}마디${done ? ' — 확인함' : ''} 고치기`);
      }
      btn.addEventListener('click', () => this.open(si, mi));
      this.layer.append(btn);
    }
  }

  remaining() { return this.flags.size; }

  confirmedCount() {
    const { ex } = this.get();
    return (ex?.struct?.systems || []).reduce((a, s) => a + (s.confirmed?.length || 0), 0);
  }

  /** 다음 확인할 마디(지금 것 뒤에서 먼저, 없으면 처음부터) */
  nextFlag(from = this.cur, dir = 1) {
    const keys = [...this.flags.values()];
    if (!keys.length) return null;
    if (!from) return keys[0];
    const after = keys.filter((f) => dir > 0
      ? (f.system > from.si || (f.system === from.si && f.measure > from.mi))
      : (f.system < from.si || (f.system === from.si && f.measure < from.mi)));
    return dir > 0 ? (after[0] || keys[0]) : (after[after.length - 1] || keys[keys.length - 1]);
  }

  openNext() {
    const f = this.nextFlag(null);
    if (f) this.open(f.system, f.measure);
  }

  /* ── 편집기 ── */

  sysd() { return this.get().ex.struct.systems[this.cur.si]; }
  geoSys() { return this.get().ex.geometry.systems[this.cur.si]; }
  chordSys(create = false) {
    const { ex } = this.get();
    let sd = ex.systems.find((s, i) => (s.index ?? i) === this.cur.si);
    if (!sd && create) {
      sd = { index: this.cur.si, chords: [] };
      ex.systems.push(sd);
      ex.systems.sort((a, b) => a.index - b.index);
    }
    return sd;
  }
  notesHere() { return (this.sysd().notes || []).filter((n) => n.measure === this.cur.mi); }
  /** 큰 악보 조립과 같은 마디 경계(어긋난 막대선은 머리에 맞춘 것) */
  edges() { return measureEdges(this.geoSys(), this.sysd()); }

  /** 막대선을 바꾸기 전에 맞춘 경계를 판독 결과에 적어 둔다 — 옛 값 위에 끼우면 다시 어긋난다 */
  barsForEdit() {
    const g = this.geoSys();
    g.bars = this.edges().slice(1, -1);
    return g.bars;
  }
  /** 이 마디 가로 구간(원본 좌표). 막대선을 못 찾은 단은 단 전체 */
  span(mi = this.cur.mi) {
    const e = this.edges();
    const n = this.sysd().measures || 1;
    if (e.length - 1 !== n) return [e[0], e[e.length - 1], false];
    return [e[mi - 1], e[mi], true];
  }

  /**
   * 보여 줄 구간 — 막대선 구간에 이 마디 음표 머리가 다 들어오도록 넓힌다.
   * 막대선을 잘못 잡은 단이 있다(실측 t009-3 단4: 첫 막대선이 조표 바로 뒤라
   * 마디1 구간에 음자리표만 보였다). 막대선 자체는 그대로 둔다.
   */
  viewSpan() {
    const [x0, x1, exact] = this.span();
    if (!exact) return [x0, x1, false];
    const sp = this.geoSys().spacing;
    const hs = this.notesHere().map((n) => n.head).filter(Boolean);
    if (!hs.length) return [x0, x1, true];
    const lo = Math.min(...hs.map((h) => h.x)) - sp, hi = Math.max(...hs.map((h) => h.x + h.w)) + sp;
    return [Math.min(x0, lo), Math.max(x1, hi), true];
  }

  open(si, mi) {
    const { ex } = this.get();
    if (!ex?.struct?.systems?.[si]) return;
    this.cur = { si, mi };
    this.sel = 0;
    this.editingChord = null;
    // **되돌리기는 이 마디를 연 때로.** 마디를 넣고 빼면 단의 번호·막대선이 함께
    // 움직이므로 단을 통째로 담아 둔다
    this.snapshot();
    this.dirty = false;
    this.render();
    if (!this.dlg.open) this.dlg.showModal();
    this.q('.me-body').scrollTop = 0;
  }

  snapshot() {
    const sd = this.chordSys();
    this.snap = {
      si: this.cur.si,
      sys: structuredClone(this.sysd()),
      bars: structuredClone(this.geoSys().bars || null),
      chords: sd ? structuredClone(sd.chords) : null,
    };
  }

  undo() {
    if (!this.snap || this.snap.si !== this.cur.si) return;
    const { ex } = this.get();
    ex.struct.systems[this.cur.si] = structuredClone(this.snap.sys);
    const g = this.geoSys();
    if (this.snap.bars) g.bars = structuredClone(this.snap.bars); else delete g.bars;
    const sd = this.chordSys();
    if (sd && this.snap.chords) sd.chords = structuredClone(this.snap.chords);
    this.cur.mi = Math.min(this.cur.mi, this.sysd().measures || 1);
    this.dirty = false;
    this.stale = true;
    this.sel = 0;
    this.render();
  }

  /** 고친다 → 빔 묶음을 새로 매기게 하고 다시 보여 준다 */
  edit(fn, { beams = true } = {}) {
    fn();
    if (beams) for (const n of this.notesHere()) delete n.beamGroup;
    this.dirty = true;
    this.stale = true;
    this.render();
  }

  /** 원조로 다시 조립 — 편집기 미리보기·음이름·남은 사유가 모두 여기서 나온다 */
  assembleSource() {
    const { ex } = this.get();
    const texts = [];
    for (const s of ex.systems) for (const c of (s.chords || [])) if (!c.dropped) texts.push(c.text);
    const from = planBySemitones(ex.meta?.key || 'C', 0).fromKey;
    return assemble({ ...ex.struct, sourceFifths: fifths(from) }, ex.geometry,
      chordsByStaff(ex.systems, texts));
  }

  render() {
    const { si, mi } = this.cur;
    const { ex } = this.get();
    const sysd = this.sysd();
    const a = this.assembleSource();
    const flag = a.report.flags.find((f) => f.system === si && f.measure === mi);
    const order = [...this.flags.keys()];
    const at = order.indexOf(`${si}:${mi}`);

    // 머리글
    this.q('#me-title').textContent = `${si + 1}단 ${mi}마디`;
    this.q('#me-count').textContent = this.flags.size
      ? `${at >= 0 ? '확인할 마디 · ' : ''}남은 확인 ${this.flags.size}개`
      : '확인할 마디를 모두 봤습니다';
    const why = this.q('#me-why');
    why.replaceChildren();
    const reasons = flag?.reasons || [];
    for (const r of reasons) why.append(el('li', r.wide ? 'wide' : '', r.text));
    if (!reasons.length) {
      const done = (sysd.confirmed || []).includes(mi);
      why.append(el('li', 'calm', done ? '확인한 마디입니다. 더 고칠 곳이 있으면 고쳐 주세요'
        : '자동 판독이 자신 있는 마디입니다. 원본과 다르면 고쳐 주세요'));
    }

    // 원본 조각
    this.drawCrop();

    // 박자
    const notes = this.notesHere();
    const full = fullOf(ex.struct) / DUR.quarter;
    const only = notes.filter((n) => !n.chord);
    const sum = only.length === 1 && only[0].rest && only[0].duration === 'whole' && !only[0].dotted
      ? full : only.reduce((s, n) => s + len(n), 0) / DUR.quarter;
    const meter = this.q('#me-beats');
    meter.textContent = notes.length ? `${fmtBeats(sum)} / ${full}박` : `비어 있음 / ${full}박`;
    meter.dataset.state = !notes.length ? 'under'
      : Math.abs(sum - full) < 1e-6 ? 'ok' : sum > full ? 'over' : 'under';
    meter.title = meter.dataset.state === 'ok' ? '박자가 맞습니다'
      : '박자 합이 한 마디와 다릅니다 — 못갖춘마디라면 그대로 두세요';

    // 음표 칩 — 이름은 조립된 결과(조표·임시표가 반영된 실제 음)로
    const pieces = a.measures.filter((m) => m.src?.[0] === si && m.src?.[1] === mi);
    const played = notes.length ? pieces.flatMap((m) => m.notes) : [];
    if (this.sel >= notes.length) this.sel = Math.max(0, notes.length - 1);
    const strip = this.q('#me-notes');
    strip.replaceChildren();
    notes.forEach((n, j) => {
      const b = el('button', 'nchip');
      b.type = 'button';
      if (n.chord) b.classList.add('member');
      if (j === this.sel) b.classList.add('on');
      b.setAttribute('aria-pressed', j === this.sel ? 'true' : 'false');
      const name = n.rest ? '쉼표' : pretty(played[j]?.pitch);
      b.append(el('b', '', (n.chord ? '+' : '') + name),
        el('small', '', `${WORD[n.duration] || n.duration}${n.dotted ? '·점' : ''}${n.tie ? ' ⌒' : ''}`));
      b.addEventListener('click', () => { this.sel = j; this.render(); });
      strip.append(b);
    });
    if (!notes.length) strip.append(el('p', 'me-empty', '이 마디에 읽은 음표가 없습니다. 아래에서 넣어 주세요.'));

    // 고르개 상태
    const n = notes[this.sel];
    this.q('#me-tools').hidden = !n;
    this.q('#me-first').hidden = !!n;
    if (n) {
      const acc = n.natural ? 'natural' : n.accidental > 0 ? 'sharp' : n.accidental < 0 ? 'flat' : 'key';
      this.seg('#me-acc', ACCS, acc, n.rest);
      this.seg('#me-len', LENGTHS, n.duration, n.chord);
      this.toggle('#me-dot', !!n.dotted, n.chord);
      this.toggle('#me-tie', !!n.tie, n.rest);
      this.toggle('#me-rest', !!n.rest, n.chord);
      this.q('#me-up').disabled = !!n.rest;
      this.q('#me-down').disabled = !!n.rest;
      this.q('#me-member').disabled = !!n.rest;
      this.q('#me-split').disabled = this.sel === 0 || !!n.chord || !this.span()[2];
    }

    // 코드
    this.renderChords();

    // 마디 단위
    const [, , hasBars] = this.span();
    this.q('#me-insert').disabled = !hasBars;
    this.q('#me-drop').disabled = !hasBars || (sysd.measures || 1) <= 1;

    // 아래 단추
    const ok = this.q('#me-ok');
    ok.textContent = this.dirty ? '고친 대로 확정' : '원본과 같아요';
    ok.disabled = this.busy;
    const wide = reasons.length && reasons.every((r) => r.wide);
    const sysLeft = [...this.flags.values()].filter((f) => f.system === si
      && f.reasons.every((r) => r.wide)).length;
    const all = this.q('#me-ok-sys');
    all.hidden = !(wide && sysLeft > 1);
    all.textContent = `이 단 ${sysLeft}마디 모두 같아요`;
    this.q('#me-undo').disabled = !this.dirty;
    this.q('#me-prev').disabled = !this.flags.size;
    this.q('#me-next').disabled = !this.flags.size;

    this.preview(pieces, sysd, notes.length);
  }

  seg(sel, items, cur, disabled) {
    const box = this.q(sel);
    box.replaceChildren();
    for (const [v, label] of items) {
      const b = el('button', 'seg', label);
      b.type = 'button';
      b.dataset.v = v;
      b.disabled = !!disabled;
      b.setAttribute('aria-pressed', v === cur ? 'true' : 'false');
      box.append(b);
    }
  }

  toggle(sel, on, disabled) {
    const b = this.q(sel);
    b.setAttribute('aria-pressed', on ? 'true' : 'false');
    b.disabled = !!disabled;
  }

  /** 원본 조각: 이 마디를 밝게, 앞뒤 1.5칸은 흐리게 */
  drawCrop() {
    const { image } = this.get();
    const g = this.geoSys();
    const sp = g.spacing;
    const [x0, x1, exact] = this.viewSpan();
    const W = image.naturalWidth, H = image.naturalHeight;
    const pad = exact ? sp * 3 : 0;
    const sx = Math.max(0, Math.floor(x0 - pad)), ex = Math.min(W, Math.ceil(x1 + pad));
    const sy = Math.max(0, Math.floor(g.staffTop - sp * 5)), ey = Math.min(H, Math.ceil(g.staffBottom + sp * 4));
    const cv = this.q('#me-crop');
    const scale = Math.min(4, Math.max(1, 300 / (ey - sy)));
    cv.width = Math.max(1, Math.round((ex - sx) * scale));
    cv.height = Math.max(1, Math.round((ey - sy) * scale));
    const c = cv.getContext('2d');
    c.imageSmoothingQuality = 'high';
    c.fillStyle = '#fff';
    c.fillRect(0, 0, cv.width, cv.height);
    c.drawImage(image, sx, sy, ex - sx, ey - sy, 0, 0, cv.width, cv.height);
    if (exact) {
      c.fillStyle = 'rgba(255,255,255,.68)';
      const a = (x0 - sx) * scale, b = (x1 - sx) * scale;
      c.fillRect(0, 0, a, cv.height);
      c.fillRect(b, 0, cv.width - b, cv.height);
      c.fillStyle = 'rgba(217,154,0,.9)';
      c.fillRect(Math.max(0, a - 1.5), 0, 3, cv.height);
      c.fillRect(Math.max(0, b - 1.5), 0, 3, cv.height);
    }
    this.q('#me-crop-note').textContent = exact ? '' : '이 단은 마디 경계를 못 찾아 한 줄 전체를 보여 드립니다';
  }

  /** 고친 모습 — 이 마디만 Verovio 로(원조) */
  async preview(pieces, sysd, nNotes) {
    const box = this.q('#me-prev-svg');
    const ticket = (this.ticket = (this.ticket || 0) + 1);
    const { ex } = this.get();
    const from = planBySemitones(ex.meta?.key || 'C', 0).fromKey;
    const f = sysd.srcFifths ?? fifths(from);
    const m = /^(\d+)\/(\d+)$/.exec(String(ex.struct?.timeSignature || ''));
    const q = Number(ex.struct?.beats) || 4;
    const beats = m ? Number(m[1]) : (q === 3 ? 3 : q === 2 ? 2 : 4);
    const beatType = m ? Number(m[2]) : 4;
    const ms = pieces.map((p, i) => ({
      ...p, newSystem: i === 0, fifths: undefined,
      notes: p.notes.map((n, j) => (i === 0 && j === 0 ? { ...n, tie_stop: false } : { ...n })),
    }));
    let svg;
    try {
      const tk = await toolkit();
      if (ticket !== this.ticket) return;
      const xml = build(ms.length ? ms : [{ notes: [{ pitch: null, duration: 'whole' }] }], f,
        { beats, beatType });
      const units = ms.reduce((a, p) => a + p.notes.length, 0);
      tk.setOptions({
        pageWidth: Math.min(1500, 520 + units * 130), pageHeight: 2000, scale: 50,
        font: 'Leipzig', breaks: 'auto', adjustPageHeight: true, svgBoundingBoxes: false,
        header: 'none', footer: 'none', mnumInterval: 0, noJustification: true,
        adjustPageWidth: true,
      });
      try {
        if (!tk.loadData(xml)) throw new Error('미리보기를 그리지 못했습니다');
        svg = tk.renderToSVG(1);
      } finally {
        // 큰 악보 조판은 쪽 폭에 고르게 펴는 것이 기본이다 — 여기서 바꾼 것을 되돌린다
        tk.setOptions({ noJustification: false, adjustPageWidth: false });
      }
    } catch (err) {
      box.textContent = err.message || '미리보기를 그리지 못했습니다';
      return;
    }
    box.innerHTML = svg;
    const s = box.querySelector('svg');
    if (s) { s.removeAttribute('width'); s.removeAttribute('height'); s.setAttribute('role', 'img'); }
    // 미리보기의 음표를 눌러도 고른다 — 순서가 칩과 같다
    if (nNotes) {
      box.querySelectorAll('g.note').forEach((g, j) => {
        if (j === this.sel) g.classList.add('sel');
        g.addEventListener('click', () => { this.sel = j; this.render(); });
      });
    }
    s?.setAttribute('aria-label', `${this.cur.si + 1}단 ${this.cur.mi}마디 고친 모습`);
  }

  /* ── 코드 ── */

  chordsHere() {
    const sd = this.chordSys();
    if (!sd) return [];
    const e = this.edges();
    const sp = this.geoSys().spacing;
    const n = this.sysd().measures || 1;
    const [, , exact] = this.span();
    return (sd.chords || []).filter((c) => {
      if (c.dropped) return false;
      if (!exact) return true;
      const x = c.box ? c.box.x + (c.box.w || 0) / 2 : 0;
      let mi = 0;
      for (let i = 0; i < e.length - 1; i += 1) if (x >= e[i] - sp * 0.5) mi = i;
      return Math.min(mi, n - 1) + 1 === this.cur.mi;
    }).sort((a, b) => (a.box?.x ?? 0) - (b.box?.x ?? 0));
  }

  renderChords() {
    const box = this.q('#me-chords');
    box.replaceChildren();
    for (const c of this.chordsHere()) {
      if (this.editingChord === c) {
        box.append(this.chordForm(c.text, (t) => this.edit(() => {
          c.text = t; c.confidence = 1;
        }, { beams: false }), () => this.edit(() => { c.dropped = true; }, { beams: false })));
        continue;
      }
      const b = el('button', 'cchip', c.text);
      b.type = 'button';
      b.title = '눌러서 고치기';
      b.addEventListener('click', () => { this.editingChord = c; this.render(); this.q('#me-chords input')?.focus(); });
      box.append(b);
    }
    if (this.editingChord === 'new') {
      box.append(this.chordForm('', (t) => this.edit(() => this.addChord(t), { beams: false })));
    } else {
      const add = el('button', 'cchip add', '＋ 코드');
      add.type = 'button';
      add.addEventListener('click', () => { this.editingChord = 'new'; this.render(); this.q('#me-chords input')?.focus(); });
      box.append(add);
    }
  }

  chordForm(text, onSave, onDelete) {
    const f = el('form', 'cform');
    const inp = el('input', 'input cinput');
    inp.value = text;
    inp.placeholder = '예: G/B';
    inp.autocapitalize = 'off';
    inp.spellcheck = false;
    inp.setAttribute('aria-label', '코드');
    const err = el('span', 'cerr');
    const save = el('button', 'btn primary sm', '저장');
    const cancel = el('button', 'btn outline sm', '취소');
    cancel.type = 'button';
    cancel.addEventListener('click', () => { this.editingChord = null; this.render(); });
    f.append(inp, save);
    if (onDelete) {
      const del = el('button', 'btn outline sm', '지우기');
      del.type = 'button';
      del.addEventListener('click', () => { this.editingChord = null; onDelete(); });
      f.append(del);
    }
    f.append(cancel, err);
    f.addEventListener('submit', (e) => {
      e.preventDefault();
      const t = inp.value.trim().replace(/♯/g, '#').replace(/♭/g, 'b');
      if (!t || !parseChord(t)) { err.textContent = '코드로 읽을 수 없어요 (예: C, F#m7, G/B)'; inp.focus(); return; }
      this.editingChord = null;
      onSave(t);
    });
    return f;
  }

  /** 고른 음표 위(없으면 마디 첫머리)에 코드를 놓는다 */
  addChord(text) {
    const g = this.geoSys();
    const sp = g.spacing;
    const n = this.notesHere()[this.sel];
    const [x0] = this.span();
    const cx = n?.head ? n.head.x + n.head.w / 2 : x0 + sp * 1.5;
    const sd = this.chordSys(true);
    const ys = (sd.chords || []).map((c) => c.box?.y).filter(Number.isFinite).sort((a, b) => a - b);
    const y = ys.length ? ys[Math.floor(ys.length / 2)] : g.staffTop - sp * 3.5;
    sd.chords.push({ text, box: { x: cx - sp, y, w: sp * 2, h: sp * 1.4 }, confidence: 1, added: 'user' });
  }

  /* ── 음표 고치기 ── */

  baseOfNote(n) {
    if (n.base) return n.base;
    const a = this.assembleSource();
    return a.bases.get(n) || 'B4';
  }

  /** 고른 음표와 그 화음 구성음(바로 뒤 chord) 묶음 */
  group(j = this.sel) {
    const notes = this.sysd().notes;
    const here = this.notesHere();
    const n = here[j];
    if (!n) return [];
    const i = notes.indexOf(n);
    if (n.chord) return [n];
    const out = [n];
    for (let k = i + 1; k < notes.length && notes[k].chord; k += 1) out.push(notes[k]);
    return out;
  }

  move(d) {
    const n = this.notesHere()[this.sel];
    if (!n || n.rest) return;
    const abs = absOf(this.baseOfNote(n));
    if (abs == null) return;
    const to = Math.min(HIGH, Math.max(LOW, abs + d));
    if (to === abs) return;
    this.edit(() => { n.base = baseOf(to); }, { beams: false });
  }

  setAcc(v) {
    const n = this.notesHere()[this.sel];
    if (!n || n.rest) return;
    this.edit(() => {
      delete n.accidental; n.natural = false;
      if (v === 'sharp') n.accidental = 1;
      else if (v === 'flat') n.accidental = -1;
      else if (v === 'natural') n.natural = true;
    }, { beams: false });
  }

  setLen(v) {
    const g = this.group();
    if (!g.length) return;
    this.edit(() => { for (const n of g) n.duration = v; });
  }

  toggleDot() {
    const g = this.group();
    if (!g.length || g[0].chord) return;
    const on = !g[0].dotted;
    this.edit(() => { for (const n of g) n.dotted = on; });
  }

  toggleTie() {
    const n = this.notesHere()[this.sel];
    if (!n || n.rest) return;
    this.edit(() => { n.tie = !n.tie; }, { beams: false });
  }

  toggleRest() {
    const g = this.group();
    if (!g.length || g[0].chord) return;
    const n = g[0];
    this.edit(() => {
      const notes = this.sysd().notes;
      if (!n.rest) {
        // 쉼표가 되면 화음 구성음도 같이 사라진다
        for (const m of g.slice(1)) notes.splice(notes.indexOf(m), 1);
        n.rest = true; n.tie = false;
        delete n.accidental; n.natural = false;
      } else {
        n.rest = false;
        n.base = n.base || this.neighbourBase(n);
      }
    });
  }

  /** 새 음표의 출발 자리 — 앞 음표, 없으면 오선 가운데 */
  neighbourBase(n) {
    const notes = this.sysd().notes;
    for (let i = notes.indexOf(n) - 1; i >= 0; i -= 1) {
      if (!notes[i].rest) return this.baseOfNote(notes[i]);
    }
    return 'B4';
  }

  /** 고른 음표(화음이면 그 묶음) 앞이나 뒤에 같은 길이의 음표를 넣는다 */
  insert(where) {
    const notes = this.sysd().notes;
    const g = this.group(this.baseIndex());
    const cur = g[0];
    const fresh = {
      measure: this.cur.mi, duration: cur?.duration || 'quarter', dotted: false,
      rest: false, tie: false, base: 'B4',
    };
    this.edit(() => {
      let at;
      if (!cur) {
        // 빈 마디 — 단 안에서 이 마디 자리를 찾아 넣는다
        const after = notes.findIndex((x) => x.measure > this.cur.mi);
        at = after < 0 ? notes.length : after;
      } else {
        at = where === 'before' ? notes.indexOf(cur) : notes.indexOf(g[g.length - 1]) + 1;
      }
      fresh.base = cur && !cur.rest ? this.baseOfNote(cur) : this.neighbourAt(at);
      notes.splice(at, 0, fresh);
    });
    this.sel = this.notesHere().indexOf(fresh);
    this.render();
  }

  neighbourAt(at) {
    const notes = this.sysd().notes;
    for (let i = at - 1; i >= 0; i -= 1) if (!notes[i].rest) return this.baseOfNote(notes[i]);
    for (let i = at; i < notes.length; i += 1) if (!notes[i].rest) return this.baseOfNote(notes[i]);
    return 'B4';
  }

  /** 화음 구성음이 골라져 있으면 그 바탕음의 칩 번호 */
  baseIndex() {
    const here = this.notesHere();
    let j = this.sel;
    while (j > 0 && here[j].chord) j -= 1;
    return j;
  }

  addMember() {
    const g = this.group(this.baseIndex());
    const n = g[0];
    if (!n || n.rest) return;
    const top = Math.max(...g.map((m) => absOf(this.baseOfNote(m)) ?? 0));
    const fresh = { measure: n.measure, duration: n.duration, dotted: !!n.dotted, rest: false,
      tie: false, chord: true, base: baseOf(Math.min(HIGH, top + 2)) };
    const notes = this.sysd().notes;
    this.edit(() => { notes.splice(notes.indexOf(g[g.length - 1]) + 1, 0, fresh); });
    this.sel = this.notesHere().indexOf(fresh);
    this.render();
  }

  remove() {
    const g = this.group();
    if (!g.length) return;
    const notes = this.sysd().notes;
    this.edit(() => { for (const m of g) notes.splice(notes.indexOf(m), 1); });
    this.sel = Math.max(0, this.sel - 1);
    this.render();
  }

  /* ── 마디 넣기·나누기·지우기 ── */

  /** from 이상 마디 번호를 delta 만큼 민다 — 음표·확인·사유·도돌이·못갖춘마디 모두 */
  renumber(from, delta) {
    const s = this.sysd();
    const sh = (m) => (m >= from ? m + delta : m);
    for (const n of s.notes || []) n.measure = sh(n.measure);
    if (s.confirmed) s.confirmed = s.confirmed.map(sh);
    if (s.pickups) s.pickups = s.pickups.map(sh);
    for (const mk of s.marks || []) mk.measure = sh(mk.measure);
    if (s.review) {
      s.review = s.review.map((r) => r.replace(/^마디 (\d+):/, (_, m) => `마디 ${sh(Number(m))}:`));
    }
    s.measures = Math.max(1, (s.measures || 1) + delta);
  }

  /**
   * 이 마디 앞에 빈 마디 — 두 번째 판독기만 읽은 마디가 빠졌을 때.
   * 새 마디는 **이 마디 첫 음표 앞 빈자리**를 차지한다. 빠진 마디(대개 쉼표만 있는
   * 마디)는 거기 있었고, 그 위 코드도 새 마디로 와야 한다.
   */
  insertMeasure() {
    const mi = this.cur.mi;
    const e = this.edges();
    const sp = this.geoSys().spacing;
    const hs = this.notesHere().map((n) => n.head).filter(Boolean);
    const first = hs.length ? Math.min(...hs.map((h) => h.x)) : null;
    const x = first != null && first - sp > e[mi - 1] + sp ? first - sp : e[mi - 1] + 1;
    this.edit(() => {
      const bars = this.barsForEdit();          // 번호를 밀기 전에 — 개수가 맞을 때 맞춘다
      this.renumber(mi, 1);
      bars.splice(mi - 1, 0, x);
    });
    this.sel = 0;
    this.render();
  }

  /** 고른 음표부터 다음 마디로 — 마디 둘이 하나로 붙어 읽혔을 때 */
  splitMeasure() {
    const here = this.notesHere();
    const j = this.sel;
    if (j <= 0 || here[j]?.chord) return;
    const mi = this.cur.mi;
    const [x0, x1] = this.span();
    const a = here[j - 1].head, b = here[j].head;
    let x = a && b ? (a.x + a.w + b.x) / 2 : (x0 + x1) / 2;
    x = Math.min(x1 - 2, Math.max(x0 + 2, x));
    this.edit(() => {
      const bars = this.barsForEdit();
      this.renumber(mi + 1, 1);
      for (const n of here.slice(j)) n.measure = mi + 1;
      bars.splice(mi - 1, 0, x);
      for (const n of this.sysd().notes) if (n.measure === mi + 1) delete n.beamGroup;
    });
    this.sel = 0;
    this.render();
  }

  /** 없는 마디를 읽었을 때 — 음표와 막대선 하나를 없앤다 */
  dropMeasure() {
    const s = this.sysd();
    const mi = this.cur.mi;
    if ((s.measures || 1) <= 1) return;
    this.edit(() => {
      const bars = this.barsForEdit();
      s.notes = (s.notes || []).filter((n) => n.measure !== mi);
      if (s.confirmed) s.confirmed = s.confirmed.filter((m) => m !== mi);
      if (s.pickups) s.pickups = s.pickups.filter((m) => m !== mi);
      s.marks = (s.marks || []).filter((mk) => mk.measure !== mi);
      if (s.review) s.review = s.review.filter((r) => !r.startsWith(`마디 ${mi}:`));
      this.renumber(mi + 1, -1);
      if (mi - 1 < bars.length) bars.splice(mi - 1, 1);
      else bars.splice(mi - 2, 1);
    });
    this.cur.mi = Math.min(mi, s.measures || 1);
    this.sel = 0;
    this.render();
  }

  /* ── 확정·이동·닫기 ── */

  async confirm(scope = 'measure') {
    if (this.busy) return;
    const { si, mi } = this.cur;
    const s = this.sysd();
    const set = new Set(s.confirmed || []);
    if (scope === 'system') {
      for (const f of this.flags.values()) {
        if (f.system === si && f.reasons.every((r) => r.wide)) set.add(f.measure);
      }
    }
    set.add(mi);
    s.confirmed = [...set].sort((a, b) => a - b);
    this.stale = true;
    await this.sync();
    this.snap = null;
    const next = this.nextFlag({ si, mi });
    if (next) this.open(next.system, next.measure);
    else this.close(true);
  }

  /** 큰 악보를 struct 에 맞춘다 */
  async sync() {
    if (!this.stale) return;
    this.busy = true;
    this.dlg.classList.add('busy');
    try {
      await this.rerender();
      this.stale = false;
    } finally {
      this.busy = false;
      this.dlg.classList.remove('busy');
    }
  }

  async go(dir) {
    const f = this.nextFlag(this.cur, dir);
    if (!f) return;
    if (this.stale) await this.sync();
    this.open(f.system, f.measure);
  }

  async close(done = false) {
    if (this.dlg.open) this.dlg.close();
    this.snap = null;
    if (this.stale) await this.sync();
    // 방금 보던 마디를 악보에서 짚어 준다 — 어디까지 봤는지 잃지 않게
    const k = this.cur && `${this.cur.si}:${this.cur.mi}`;
    const i = this.boxes.findIndex((b) => b.src.join(':') === k);
    const btn = i >= 0 ? this.layer.children[i] : null;
    if (btn) {
      btn.scrollIntoView({ block: 'center', behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' });
      btn.classList.remove('ping'); void btn.offsetWidth; btn.classList.add('ping');
      btn.focus({ preventScroll: true });
    }
    if (done) this.onChange('done');
  }

  /* ── 단추 잇기 ── */

  wire() {
    const on = (sel, fn) => this.q(sel).addEventListener('click', fn);
    on('#me-close', () => this.close());
    on('#me-ok', () => this.confirm());
    on('#me-ok-sys', () => this.confirm('system'));
    on('#me-undo', () => this.undo());
    on('#me-prev', () => this.go(-1));
    on('#me-next', () => this.go(1));
    on('#me-up', () => this.move(1));
    on('#me-down', () => this.move(-1));
    on('#me-dot', () => this.toggleDot());
    on('#me-tie', () => this.toggleTie());
    on('#me-rest', () => this.toggleRest());
    on('#me-before', () => this.insert('before'));
    on('#me-after', () => this.insert('after'));
    on('#me-member', () => this.addMember());
    on('#me-del', () => this.remove());
    on('#me-first-note', () => this.insert('after'));
    on('#me-first-rest', () => {
      this.insert('after');
      const n = this.notesHere()[this.sel];
      if (n) this.edit(() => { n.rest = true; n.duration = 'whole'; delete n.base; });
    });
    on('#me-insert', () => this.insertMeasure());
    on('#me-split', () => this.splitMeasure());
    on('#me-drop', () => this.dropMeasure());
    this.q('#me-acc').addEventListener('click', (e) => {
      const v = e.target.closest('.seg')?.dataset.v;
      if (v) this.setAcc(v);
    });
    this.q('#me-len').addEventListener('click', (e) => {
      const v = e.target.closest('.seg')?.dataset.v;
      if (v) this.setLen(v);
    });
    // Esc 로 닫혀도 고친 것을 큰 악보에 반영한다
    this.dlg.addEventListener('cancel', (e) => { e.preventDefault(); this.close(); });
    // 바깥(어두운 막)을 누르면 닫는다
    this.dlg.addEventListener('click', (e) => { if (e.target === this.dlg) this.close(); });
    this.dlg.addEventListener('keydown', (e) => {
      if (e.target.closest('input, textarea, select') || e.metaKey || e.ctrlKey || e.altKey) return;
      const here = this.notesHere();
      const keys = {
        ArrowLeft: () => { this.sel = Math.max(0, this.sel - 1); this.render(); },
        ArrowRight: () => { this.sel = Math.min(here.length - 1, this.sel + 1); this.render(); },
        ArrowUp: () => this.move(1),
        ArrowDown: () => this.move(-1),
        Backspace: () => this.remove(),
        Delete: () => this.remove(),
        '.': () => this.toggleDot(),
        1: () => this.setLen('whole'), 2: () => this.setLen('half'), 3: () => this.setLen('quarter'),
        4: () => this.setLen('eighth'), 5: () => this.setLen('16th'),
      };
      const fn = keys[e.key];
      if (fn && here.length) { e.preventDefault(); fn(); }
    });
  }
}
