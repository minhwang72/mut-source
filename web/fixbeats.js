// **박자가 안 맞는 마디를 사람이 고친다.**
//
// 왜 필요한가: 자동 판독은 마디 몇 개를 꾸준히 틀린다(음가 한 단계 차이가
// 대부분). fitdur 가 역산으로 메우지만 후보가 여럿이면 포기한다 — 찍느니
// 남겨 두는 게 낫다는 설계다. 그 남은 것을 처리할 방법이 지금까지 없었다.
//
// 재조판은 struct 에서 그리므로, struct 의 음가 한 칸만 고치고 다시 그리면
// 된다. 새 렌더 경로도, 픽셀 이동도 필요 없다.

import { DUR } from './musicxml.js';
import { checkBeats, fullOf } from './rebuild.js';

const NAMES = [['whole', '온'], ['half', '2분'], ['quarter', '4분'],
               ['eighth', '8분'], ['16th', '16분']];

const val = (n) => (DUR[n.duration] ?? 0) * (n.dotted ? 1.5 : 1);

/** 이 마디의 합(4분음표 단위). */
function sum(struct, si, mi) {
  return struct.systems[si].notes
    .filter((n) => n.measure === mi)
    .reduce((a, n) => a + val(n), 0) / DUR.quarter;
}

/**
 * 안 맞는 마디마다 음가 고르개를 만든다.
 * onApply: 고친 뒤 다시 그리라는 신호.
 */
export function fixPanel(struct, onApply) {
  const cb = checkBeats(struct);
  const broken = [...cb.over, ...cb.under].map(([si, mi]) => [si, mi, false]);
  // **찍어서 맞춘 마디도 보여준다.** 박자 역산이 후보가 여럿일 때 하나를
  // 골라 채우므로(fitdur.fit_measure guess), 합은 맞지만 틀렸을 수 있다.
  // 깨진 채로 두는 것보다 낫지만, 어디를 찍었는지는 알려야 한다.
  const guessed = [];
  struct.systems.forEach((sys, si) => {
    const ms = new Set((sys.notes || []).filter((n) => n.guessed).map((n) => n.measure));
    for (const mi of ms) {
      if (!broken.some(([a, b]) => a === si && b === mi)) guessed.push([si, mi, true]);
    }
  });
  const bad = [...broken, ...guessed].sort((a, b) => (a[0] - b[0]) || (a[1] - b[1]));
  if (!bad.length) return null;

  const full = fullOf(struct) / DUR.quarter;
  const box = document.createElement('div');
  box.className = 'fixbeats';
  // 답이 하나뿐이라 고친 마디는 줄로 띄우지 않고 수만 알린다 — 전부 띄우면
  // 장당 8.6줄이 되어 정작 봐야 할 것이 묻힌다.
  let nFitted = 0;
  struct.systems.forEach((sys, si) => {
    const ms = new Set((sys.notes || [])
      .filter((n) => n.fitted && !n.guessed).map((n) => n.measure));
    for (const mi of ms) {
      if (!bad.some(([a, b]) => a === si && b === mi)) nFitted += 1;
    }
  });

  const h = document.createElement('p');
  h.className = 'fixbeats-head';
  h.textContent = [
    broken.length ? `박자가 안 맞는 마디 ${broken.length}개` : '',
    guessed.length ? `여럿 중 골라 채운 마디 ${guessed.length}개` : '',
    nFitted ? `박자로 바로잡은 마디 ${nFitted}개` : '',
  ].filter(Boolean).join(' · ') + ' — 음가를 고치면 바로 다시 그립니다';
  box.append(h);

  for (const [si, mi, isGuess] of bad) {
    const row = document.createElement('div');
    row.className = 'fixbeats-row';

    const tag = document.createElement('span');
    tag.className = 'fixbeats-tag';
    row.append(tag);
    if (isGuess) row.classList.add('guessed');

    const notes = struct.systems[si].notes.filter((n) => n.measure === mi);
    // 합을 다시 재서 꼬리표를 갱신한다 — 고르개를 바꿀 때마다 부른다
    const retag = () => {
      const s = sum(struct, si, mi);
      tag.textContent = `단${si + 1} 마디${mi} — ${s}/${full}박`
        + (isGuess ? ' (자동)' : '');
      tag.classList.toggle('ok', Math.abs(s - full) < 1e-6);
    };

    for (const n of notes) {
      const wrap = document.createElement('label');
      wrap.className = 'fixbeats-note';

      const sel = document.createElement('select');
      if (n.guessed) sel.classList.add('guessed');
      for (const [v, label] of NAMES) {
        const o = document.createElement('option');
        o.value = v;
        o.textContent = label + (n.rest ? '쉼' : '');
        if (v === n.duration) o.selected = true;
        sel.append(o);
      }
      sel.addEventListener('change', () => { n.duration = sel.value; retag(); });

      const dot = document.createElement('input');
      dot.type = 'checkbox';
      dot.checked = !!n.dotted;
      dot.title = '붙임점';
      dot.addEventListener('change', () => { n.dotted = dot.checked; retag(); });

      wrap.append(sel, dot);
      row.append(wrap);
    }
    retag();
    box.append(row);
  }

  const btn = document.createElement('button');
  btn.className = 'btn';
  btn.textContent = '고쳐서 다시 그리기';
  btn.addEventListener('click', onApply);
  box.append(btn);
  return box;
}
