// 버튼 하나가 어떤 단계를 돌릴지 정하는 규칙. 화면과 분리해 두면 규칙만 따로 테스트할 수 있다.
import { DEFAULT_STAGES, type Episode, type EpisodeKind, type StageName } from "./types";

/** 다시 쓸 수 있는 분석 결과(영상 읽기·전사·신호)가 모두 있는 회차인가. prep 만 끝난 회차는 처음부터 다시 돈다. */
export function isAnalyzed(e: Pick<Episode, "stages"> | null | undefined): boolean {
  return (["prep", "transcribe", "signals"] as StageName[]).every((s) => !!e?.stages?.[s]);
}

/** '쇼츠 초안 만들기' / '편집 포인트 뽑기': 처음이면 전체, 분석이 끝난 회차면 뒷단만 다시. */
export function quickRunStages(e: Pick<Episode, "stages"> | null | undefined, kind: EpisodeKind): StageName[] {
  if (!isAnalyzed(e)) return DEFAULT_STAGES[kind];
  return kind === "edited" ? ["shorts", "export", "xml", "eval"] : ["candidates", "eval"];
}

/** '자막 만들기': 영상 읽기·전사가 안 됐으면 그것부터, 됐으면 자막 파일만 쓴다. */
export function subtitleRunStages(e: Pick<Episode, "stages"> | null | undefined): StageName[] {
  return [
    ...(e?.stages?.prep ? [] : (["prep"] as const)),
    ...(e?.stages?.transcribe ? [] : (["transcribe"] as const)),
    "subtitles",
  ];
}
