// Resolve staff positions to sounding pitches before transposition. A key signature
// changes every octave; an explicit accidental lasts only for this octave/measure.
// `measureId` identifies the measure an accidental is scoped to. It defaults to
// the reading's measure number, which only counts within one system — a caller
// that stitches systems together must pass an id that stays the same when one
// measure runs across a system break.
export function sourcePitch(base, note, sourceFifths, state, measureId = note.measure) {
  if (!/^[A-G]-?\d+$/.test(base)) throw new Error('음표 위치를 확인할 수 없습니다');
  if (!Number.isInteger(sourceFifths) || Math.abs(sourceFifths) > 7) {
    throw new Error('원조표를 확인할 수 없습니다');
  }
  if (state.measure !== measureId) {
    state.measure = measureId;
    state.accidentals = new Map();
  }
  const explicit = note.natural ? 0 : note.accidental;
  if (explicit != null) {
    if (!Number.isInteger(explicit) || Math.abs(explicit) > 2) {
      throw new Error('임시표를 확인할 수 없습니다');
    }
    state.accidentals.set(base, explicit);
  }
  let alter = state.accidentals.get(base);
  if (alter == null && state.tie?.base === base) alter = state.tie.alter;
  if (alter == null) {
    const order = sourceFifths >= 0 ? 'FCGDAEB' : 'BEADGCF';
    alter = order.slice(0, Math.abs(sourceFifths)).includes(base[0])
      ? Math.sign(sourceFifths) : 0;
  }
  state.tie = note.tie ? {base, alter} : null;
  return base[0] + (alter > 0 ? '#'.repeat(alter) : 'b'.repeat(-alter)) + base.slice(1);
}

export class UnresolvedScoreError extends Error {
  constructor(issues) {
    super('원본 확인이 필요한 구간이 있어 변환을 멈췄습니다.\n' + issues.map(i =>
      `${i.system + 1}단${i.measure != null ? ` ${i.measure}마디` : ''}: ${i.reason}`).join('\n'));
    this.name = 'UnresolvedScoreError';
    this.issues = issues;
  }
}

/**
 * **못 그리는 것과 확인이 필요한 것을 가른다.**
 *
 * 음높이를 못 정하면 음표를 찍을 자리가 없으므로 멈춰야 한다. 하지만 마디
 * 합이 안 맞거나 개수가 다른 것은 **그릴 수는 있다** — 멈추면 사용자는
 * 아무것도 못 받고, 고칠 화면도 못 본다(실측 7장: 6장이 이 게이트에 막혔다).
 * 그리되 표시하고, 저장·차감은 qualityGate 가 계속 막는다.
 *
 * 반환: 그려도 되지만 확인이 필요한 항목들
 */
export function assertResolved(measures, report) {
  const issues = report?.unresolved || [];
  if (measures.some(m => m.notes.some(n => n.unresolved))) {
    throw new UnresolvedScoreError([
      ...issues, {system: 0, reason: '음높이가 미확정입니다'}]);
  }
  return issues;
}
