/**
 * 판독 결과 스키마 — 서버(AI 판독)와 클라이언트(변환·렌더) 사이의 계약.
 *
 * 저작권 설계상 서버가 돌려주는 것은 **표현물이 아니라 구조 데이터**여야 한다.
 * 좌표와 텍스트는 사실 정보이고, 이걸 악보 이미지로 합성하는 일은
 * 사용자 브라우저에서 일어난다.
 */

export interface BoundingBox {
  /** 원본 이미지 픽셀 좌표. 좌상단 원점 */
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface ChordPlacement {
  /** 원본에 인쇄된 표기 그대로. "Bb", "Ebmaj7", "Bb/D", "D7+5" … */
  text: string;
  box: BoundingBox;
  /** 판독 신뢰도 0~1. 낮으면 사용자에게 확인을 요청한다 */
  confidence: number;
}

export interface SystemExtraction {
  /** 몇 번째 단(줄)인지. 0부터 */
  index: number;
  /** 이 단이 몇 번째 페이지에 있는지. 0부터 */
  page: number;
  /** 오선의 상단·하단 y좌표 — 코드 배치 밴드를 정하는 기준 */
  staffTop: number;
  staffBottom: number;
  chords: ChordPlacement[];
  /** 가사 한 줄. 이조와 무관하므로 손대지 않는다 */
  lyric?: string;
}

export interface SheetMeta {
  title?: string;
  subtitle?: string;
  composer?: string;
  /** 원조성. parseKey가 읽을 수 있는 형식 */
  key: string;
  timeSignature?: string;
  /** 원본 저작권 표기. 출력물에 반드시 그대로 보존한다 */
  copyright?: string;
  /** 입력 이미지 장수 = 출력 장수 */
  pageCount: number;
}

export interface SheetExtraction {
  meta: SheetMeta;
  systems: SystemExtraction[];
  /** 원본 이미지 크기 (좌표계 기준) */
  imageSize: { w: number; h: number };
}

/** 신뢰도가 이 값 미만이면 사용자 확인을 붙인다 */
export const CONFIDENCE_THRESHOLD = 0.9;

/** 판독 전체에서 코드를 등장 순서대로 평탄화 */
export function flattenChords(ex: SheetExtraction): ChordPlacement[] {
  return ex.systems.flatMap((s) => s.chords);
}

/** 사용자 확인이 필요한 코드 */
export function lowConfidence(
  ex: SheetExtraction,
  threshold = CONFIDENCE_THRESHOLD,
): ChordPlacement[] {
  return flattenChords(ex).filter((c) => c.confidence < threshold);
}

/** 판독에 쓰인 서로 다른 코드 표기 목록 */
export function uniqueChordTexts(ex: SheetExtraction): string[] {
  return [...new Set(flattenChords(ex).map((c) => c.text))];
}
