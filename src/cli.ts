/**
 * 코어 엔진을 직접 두드려보는 CLI.
 * 제품 코드가 아니라 검증용 도구다 — 실제 변환은 브라우저에서 돈다.
 *
 *   node --experimental-strip-types src/cli.ts key C -3 "C Am F G7"
 *   node --experimental-strip-types src/cli.ts capo F
 *   node --experimental-strip-types src/cli.ts range C C4 A5 G3 E5
 */

import { fifths, formatKey, parseKey } from "./key.ts";
import { formatChord, parseChord } from "./chord.ts";
import {
  describeCapo,
  describePlan,
  planByKey,
  planBySemitones,
  rangeFeasible,
  suggestCapo,
  suggestKeysForRange,
  transposeChords,
} from "./transpose.ts";

const USAGE = `뮤트 코어 검증 CLI

  key   <원조성> <반음(+/-)> ["코드 코드 …"]   조성 이조
  capo  <조성>                                  카포 해법
  range <원조성> <멜로디최저> <멜로디최고> <음역하한> <음역상한>
                                                음역에 맞는 조성 추천

예)
  key C -3 "C Am F G7 Em7"
  capo F
  range C C4 A5 G3 E5`;

function cmdKey(args: string[]): void {
  const [from, semis, chordText] = args;
  if (!from || semis === undefined) throw new Error("원조성과 반음 수가 필요합니다.");
  const plan = planBySemitones(from, Number.parseInt(semis, 10));
  console.log(describePlan(plan));

  const capo = suggestCapo(plan.toKey);
  if (capo.length > 0) {
    console.log(`기타  : ${capo.map(describeCapo).join(" · ")}`);
  }

  if (chordText) {
    const chords = chordText.split(/\s+/).filter(Boolean);
    // 보여주는 값이므로 실용 표기를 쓴다 (E#maj7 → Fmaj7)
    const out = transposeChords(chords, plan, { simplify: true });
    const width = Math.max(...chords.map((c) => c.length), ...out.map((c) => c.length));
    console.log(`\n원본  : ${chords.map((c) => c.padEnd(width)).join(" ")}`);
    console.log(`변환  : ${out.map((c) => c.padEnd(width)).join(" ")}`);
  }
}

function cmdCapo(args: string[]): void {
  const [k] = args;
  if (!k) throw new Error("조성이 필요합니다.");
  const suggestions = suggestCapo(k);
  if (suggestions.length === 0) {
    console.log(`${k}: 카포 7프렛 안에서 오픈 코드 해법이 없습니다.`);
    return;
  }
  console.log(`${formatKey(readKey(k))} 연주법`);
  for (const s of suggestions) console.log(`  · ${describeCapo(s)}`);
}

/** 입력 조성을 그대로(이명동음 정규화 없이) 표기한다 */
function readKey(s: string) {
  const k = parseKey(s);
  if (!k) throw new Error(`조성을 해석할 수 없습니다: "${s}"`);
  return k;
}

function cmdRange(args: string[]): void {
  const [from, mLow, mHigh, sLow, sHigh] = args;
  if (!from || !mLow || !mHigh || !sLow || !sHigh) {
    throw new Error("원조성, 멜로디 최저·최고음, 음역 하한·상한이 필요합니다.");
  }
  const req = {
    fromKey: from,
    melodyLow: mLow,
    melodyHigh: mHigh,
    singerLow: sLow,
    singerHigh: sHigh,
  };

  if (!rangeFeasible(req)) {
    console.log(
      `⚠️  멜로디 음역(${mLow}~${mHigh})이 부를 수 있는 음역(${sLow}~${sHigh})보다 넓습니다.` +
        `\n    어떤 키로도 완전히 들어오지 않습니다. 벗어남이 가장 적은 순으로 보여줍니다.\n`,
    );
  }

  const ranked = suggestKeysForRange(req);
  console.log(`원조성 ${formatKey(readKey(from))} · 추천 순위\n`);
  for (const c of ranked.slice(0, 5)) {
    const n = c.semitones;
    const shift = n === 0 ? "원키" : `${n > 0 ? "+" : ""}${n}반음`;
    const status = c.fits
      ? `여유 아래 ${c.headroomLow} / 위 ${c.headroomHigh} 반음`
      : `음역 초과 ${c.overflow}반음`;
    const capo = c.capo.length > 0 ? ` — ${describeCapo(c.capo[0])}` : "";
    console.log(
      `  ${c.fits ? "✅" : "  "} ${formatKey(c.key).padEnd(4)} ${shift.padEnd(8)}` +
        ` 조표 ${String(c.accidentals).padStart(1)}개  ${status}${capo}`,
    );
  }
}

/**
 * 기계 판독용 출력. 오버레이 렌더러(tools/overlay.py)가 이걸 호출한다.
 * stdin으로 {fromKey, semitones, chords[]} JSON을 받아 결과 JSON을 낸다.
 */
async function cmdMap(): Promise<void> {
  const chunks: Buffer[] = [];
  for await (const c of process.stdin) chunks.push(c as Buffer);
  const req = JSON.parse(Buffer.concat(chunks).toString("utf8")) as {
    fromKey: string;
    semitones?: number;
    toKey?: string;
    prefer?: "sharp" | "flat";
    chords: string[];
  };

  const plan =
    req.toKey !== undefined
      ? planByKey(req.fromKey, req.toKey)
      : planBySemitones(req.fromKey, req.semitones ?? 0, { prefer: req.prefer });

  // 렌더러·서버가 그대로 그리는 값이므로 실용 표기를 쓴다.
  // 코어(transposeChords 기본값)는 왕복 불변을 위해 손대지 않는다.
  const out = transposeChords(req.chords, plan, { simplify: true });
  process.stdout.write(
    `${JSON.stringify(
      {
        fromKey: formatKey(plan.fromKey),
        toKey: formatKey(plan.toKey),
        semitones: plan.semitones,
        // 조표: 양수 = 올림표 개수, 음수 = 내림표 개수
        fifthsFrom: fifths(plan.fromKey),
        fifthsTo: fifths(plan.toKey),
        // 온음계 단계. 오선에서 음표를 옮길 픽셀 수를 이 값으로 정한다
        // (1단 = 오선 간격의 절반)
        steps: plan.interval.steps,
        summary: describePlan(plan),
        capo: suggestCapo(plan.toKey).map((s) => ({
          capo: s.capo,
          shapeKey: formatKey(s.shapeKey),
          label: describeCapo(s),
        })),
        chords: req.chords.map((text, i) => ({ from: text, to: out[i] })),
      },
      null,
      2,
    )}\n`,
  );
}

/**
 * 판독된 문자열이 실제 코드인지 결정론적으로 판정한다.
 *
 * AI에게 "이건 코드가 아니다"를 판단시키면 틀린다(실측: Haiku가 단독 `F`를
 * 코드가 아니라고 거부). 파서가 심판을 봐야 한다 — 파싱되면 코드다.
 */
async function cmdValidate(): Promise<void> {
  const chunks: Buffer[] = [];
  for await (const c of process.stdin) chunks.push(c as Buffer);
  const req = JSON.parse(Buffer.concat(chunks).toString("utf8")) as {
    chords: string[];
  };
  process.stdout.write(
    `${JSON.stringify(
      {
        results: req.chords.map((text) => {
          const parsed = parseChord(text);
          return {
            text,
            isChord: parsed !== null,
            // 정규화된 표기 — 파서가 이해한 대로 되돌려 준다
            normalized: parsed ? formatChord(parsed) : null,
          };
        }),
      },
      null,
      2,
    )}\n`,
  );
}

function main(): void {
  const [cmd, ...args] = process.argv.slice(2);
  try {
    switch (cmd) {
      case "key":
        cmdKey(args);
        break;
      case "validate":
        void cmdValidate().catch((err) => {
          console.error(`오류: ${err instanceof Error ? err.message : String(err)}`);
          process.exitCode = 1;
        });
        break;
      case "map":
        void cmdMap().catch((err) => {
          console.error(`오류: ${err instanceof Error ? err.message : String(err)}`);
          process.exitCode = 1;
        });
        break;
      case "capo":
        cmdCapo(args);
        break;
      case "range":
        cmdRange(args);
        break;
      default:
        console.log(USAGE);
        process.exitCode = cmd ? 1 : 0;
    }
  } catch (err) {
    console.error(`오류: ${err instanceof Error ? err.message : String(err)}`);
    process.exitCode = 1;
  }
}

main();
