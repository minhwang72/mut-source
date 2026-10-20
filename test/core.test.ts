import { describe, it } from "node:test";
import assert from "node:assert/strict";

import { formatNote, midi, parseNote, transposeNote } from "../src/pitch.ts";
import { accidentalCount, fifths, formatKey, parseKey } from "../src/key.ts";
import { formatChord, parseChord } from "../src/chord.ts";
import {
  describeCapo,
  planBySemitones,
  planByKey,
  rangeFeasible,
  suggestCapo,
  suggestKeysForRange,
  transposeChords,
  transposeNoteNames,
} from "../src/transpose.ts";

const key = (s: string) => {
  const k = parseKey(s);
  assert.ok(k, `조성 파싱 실패: ${s}`);
  return k;
};

describe("음높이", () => {
  it("MIDI 번호가 표준과 일치한다", () => {
    assert.equal(midi(parseNote("C4")!), 60);
    assert.equal(midi(parseNote("A4")!), 69);
    assert.equal(midi(parseNote("C-1")!), 0);
    // 이명동음은 같은 MIDI
    assert.equal(midi(parseNote("C#4")!), midi(parseNote("Db4")!));
  });

  it("음이름을 왕복 변환한다", () => {
    for (const s of ["C", "Bb", "F#", "Ebb", "G##", "A"]) {
      assert.equal(formatNote(parseNote(s)!), s);
    }
    assert.equal(formatNote(parseNote("F#3")!, { octave: true }), "F#3");
  });

  it("이조가 옥타브 경계를 넘어도 맞다", () => {
    // B4 + 단2도 = C5
    assert.equal(
      formatNote(transposeNote(parseNote("B4")!, { steps: 1, semitones: 1 }), { octave: true }),
      "C5",
    );
    // C4 - 장2도 = Bb3
    assert.equal(
      formatNote(transposeNote(parseNote("C4")!, { steps: -1, semitones: -2 }), { octave: true }),
      "Bb3",
    );
  });

  it("온음계 단계를 지켜 올바른 이명동음을 만든다", () => {
    // Eb + 장3도 = G (G가 아니라 F##이 되면 안 된다)
    assert.equal(formatNote(transposeNote(parseNote("Eb")!, { steps: 2, semitones: 4 })), "G");
    // E# + 단2도 = F#
    assert.equal(formatNote(transposeNote(parseNote("E#")!, { steps: 1, semitones: 1 })), "F#");
  });
});

describe("조성", () => {
  it("조표 개수가 5도권과 일치한다", () => {
    const cases: [string, number][] = [
      ["C", 0], ["G", 1], ["D", 2], ["A", 3], ["E", 4], ["B", 5], ["F#", 6], ["C#", 7],
      ["F", -1], ["Bb", -2], ["Eb", -3], ["Ab", -4], ["Db", -5], ["Gb", -6], ["Cb", -7],
      ["Am", 0], ["Em", 1], ["Bm", 2], ["F#m", 3], ["Dm", -1], ["Gm", -2], ["Cm", -3],
    ];
    for (const [name, expected] of cases) {
      assert.equal(fifths(key(name)), expected, `${name} 조표`);
    }
  });

  it("장·단조 표기를 파싱한다", () => {
    assert.equal(formatKey(key("Bb")), "Bb");
    assert.equal(formatKey(key("Am")), "Am");
    assert.equal(formatKey(key("f# minor")), "F#m");
    assert.equal(formatKey(key("Eb장조")), "Eb");
  });
});

describe("코드 심볼", () => {
  it("근음 직후의 b를 임시표로 본다", () => {
    const c = parseChord("Bb9")!;
    assert.equal(formatNote(c.root), "Bb");
    assert.equal(c.quality, "9");
  });

  it("성질 문자열을 해석하지 않고 보존한다", () => {
    for (const s of ["Cmaj7#11", "C7b5", "Csus4", "Cm7b5", "C13(b9)", "CmM7"]) {
      const c = parseChord(s)!;
      assert.equal(formatChord(c), s, s);
    }
  });

  it("분수코드와 괄호를 다룬다", () => {
    assert.equal(formatChord(parseChord("Am7/G")!), "Am7/G");
    assert.equal(formatChord(parseChord("(Am)")!), "(Am)");
    assert.equal(formatChord(parseChord("F#m7/C#")!), "F#m7/C#");
  });

  it("코드가 아닌 표기는 null을 반환한다", () => {
    for (const s of ["N.C.", "%", "", "  ", "|"]) {
      assert.equal(parseChord(s), null, JSON.stringify(s));
    }
  });
});

describe("이조 — 코드 진행", () => {
  it("C → D (+2)", () => {
    const plan = planBySemitones("C", 2);
    assert.equal(formatKey(plan.toKey), "D");
    assert.deepEqual(
      transposeChords(["C", "Am", "F", "G7", "Em7", "Dm7"], plan),
      ["D", "Bm", "G", "A7", "F#m7", "Em7"],
    );
  });

  it("C → A (-3)", () => {
    const plan = planBySemitones("C", -3);
    assert.equal(formatKey(plan.toKey), "A");
    assert.deepEqual(
      transposeChords(["C", "Am", "F", "G7"], plan),
      ["A", "F#m", "D", "E7"],
    );
  });

  it("Eb → E (+1) — 겹임시표를 만들지 않는다", () => {
    const plan = planBySemitones("Eb", 1);
    assert.equal(formatKey(plan.toKey), "E");
    assert.deepEqual(
      transposeChords(["Eb", "Bb", "Cm", "Ab", "Bb7"], plan),
      ["E", "B", "C#m", "A", "B7"],
    );
  });

  it("C# → D (+1)", () => {
    const plan = planBySemitones("C#", 1);
    assert.equal(formatKey(plan.toKey), "D");
    assert.deepEqual(transposeChords(["C#", "E#m", "A#"], plan), ["D", "F#m", "B"]);
  });

  it("분수코드·괄호·비코드가 섞여도 안전하다", () => {
    const plan = planBySemitones("C", 2);
    assert.deepEqual(
      transposeChords(["C", "Am7/G", "(F)", "N.C.", "G7sus4", "%"], plan),
      ["D", "Bm7/A", "(G)", "N.C.", "A7sus4", "%"],
    );
  });

  it("이명동음 동수일 때 선호 방향을 따른다", () => {
    assert.equal(formatKey(planBySemitones("C", 6).toKey), "F#");
    assert.equal(formatKey(planBySemitones("C", 6, { prefer: "flat" }).toKey), "Gb");
  });

  it("요청한 방향을 지킨다 (최단거리로 뒤집지 않는다)", () => {
    const down = planBySemitones("C", -5);
    assert.equal(formatKey(down.toKey), "G");
    assert.equal(down.semitones, -5);
    assert.equal(down.interval.semitones, -5);
    // 같은 목표 조성이지만 위로 올리면 +7
    const up = planBySemitones("C", 7);
    assert.equal(formatKey(up.toKey), "G");
    assert.equal(up.interval.semitones, 7);
  });

  it("단조끼리 이조한다", () => {
    const plan = planBySemitones("Am", 2);
    assert.equal(formatKey(plan.toKey), "Bm");
    assert.deepEqual(transposeChords(["Am", "Dm", "E7", "F"], plan), ["Bm", "Em", "F#7", "G"]);
  });

  it("장조 → 단조 지정은 거부한다", () => {
    assert.throws(() => planByKey("C", "Am"), /장·단조/);
  });

  it("멜로디 음이름도 이조한다", () => {
    const plan = planBySemitones("C", 2);
    assert.deepEqual(
      transposeNoteNames(["C4", "E4", "G4", "B4", "C5"], plan),
      ["D4", "F#4", "A4", "C#5", "D5"],
    );
  });
});

describe("기타 카포", () => {
  it("F장조의 표준 카포 해법을 낸다", () => {
    const got = suggestCapo(key("F")).map(describeCapo);
    assert.deepEqual(got, [
      "카포 1프렛 + E 폼",
      "카포 3프렛 + D 폼",
      "카포 5프렛 + C 폼",
    ]);
  });

  it("이미 편한 조성이면 카포 없음을 포함한다", () => {
    const got = suggestCapo(key("G"));
    assert.equal(got[0].capo, 0);
    assert.equal(formatKey(got[0].shapeKey), "G");
  });

  it("Bb장조도 해법이 있다", () => {
    const got = suggestCapo(key("Bb")).map(describeCapo);
    assert.ok(got.includes("카포 1프렛 + A 폼"), got.join(" / "));
    assert.ok(got.includes("카포 3프렛 + G 폼"), got.join(" / "));
  });
});

describe("음역 기반 키 추천", () => {
  const req = {
    fromKey: "C",
    melodyLow: "C4",   // 60
    melodyHigh: "A5",  // 81
    singerLow: "G3",   // 55
    singerHigh: "E5",  // 76
  };

  it("음역 폭이 되는지 먼저 판단한다", () => {
    assert.equal(rangeFeasible(req), true);
    assert.equal(rangeFeasible({ ...req, singerHigh: "C5" }), false);
  });

  it("정확히 들어맞는 유일한 조성을 1순위로 준다", () => {
    const ranked = suggestKeysForRange(req);
    assert.equal(ranked[0].semitones, -5);
    assert.equal(formatKey(ranked[0].key), "G");
    assert.equal(ranked[0].fits, true);
    assert.equal(ranked[0].overflow, 0);
    // 이 케이스는 폭이 딱 맞으므로 fits는 하나뿐이어야 한다
    assert.equal(ranked.filter((c) => c.fits).length, 1);
  });

  it("여유가 있으면 위아래 균형이 좋은 쪽을 먼저 준다", () => {
    const ranked = suggestKeysForRange({
      ...req,
      singerLow: "C3",
      singerHigh: "C6", // 넉넉한 음역
    });
    const top = ranked[0];
    assert.equal(top.fits, true);
    assert.ok(
      Math.abs(top.headroomLow - top.headroomHigh) <= 1,
      `균형: 아래 ${top.headroomLow} / 위 ${top.headroomHigh}`,
    );
  });

  it("맞는 조성이 없으면 벗어남이 가장 적은 순으로 준다", () => {
    const ranked = suggestKeysForRange({ ...req, singerLow: "C4", singerHigh: "C5" });
    assert.equal(ranked.every((c) => !c.fits), true);
    for (let i = 1; i < ranked.length; i++) {
      assert.ok(ranked[i - 1].overflow <= ranked[i].overflow, "overflow 정렬");
    }
  });

  it("추천 조성마다 카포 정보가 붙는다", () => {
    const ranked = suggestKeysForRange(req);
    assert.ok(Array.isArray(ranked[0].capo));
  });
});

describe("이조 불변식", () => {
  it("모든 조성 × 모든 반음 이조에서 겹임시표를 넘지 않는다", () => {
    const keys = ["C", "G", "D", "A", "E", "B", "F#", "F", "Bb", "Eb", "Ab", "Db", "Gb"];
    const chords = ["C", "Dm7", "Em", "F", "G7", "Am", "Bm7b5", "C/E", "Fmaj7", "Ab7"];
    for (const k of keys) {
      for (let n = -11; n <= 11; n++) {
        const plan = planBySemitones(k, n);
        assert.ok(
          accidentalCount(plan.toKey) <= 7,
          `${k} ${n}반음 → ${formatKey(plan.toKey)} 조표 과다`,
        );
        for (const out of transposeChords(chords, plan)) {
          assert.ok(
            !/###|bbb/.test(out),
            `${k} ${n}반음: ${out} 에 겹임시표 초과`,
          );
        }
      }
    }
  });

  it("이조 후 다시 되돌리면 원본과 같다", () => {
    const chords = ["C", "Am7", "F#m7b5", "Bb/D", "G7sus4"];
    for (let n = -7; n <= 7; n++) {
      const fwd = planBySemitones("C", n);
      const back = planByKey(fwd.toKey, fwd.fromKey, n >= 0 ? "down" : "up");
      const round = transposeChords(transposeChords(chords, fwd), back);
      assert.deepEqual(round, chords, `${n}반음 왕복`);
    }
  });
});
