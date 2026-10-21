import { describe, expect, it } from "vitest";
import { isAnalyzed, quickRunStages, subtitleRunStages } from "./plan";
import { DEFAULT_STAGES } from "./types";

const ep = (stages: Record<string, boolean>) => ({ stages });

describe("isAnalyzed", () => {
  it("영상 읽기·전사·신호가 모두 있어야 분석된 회차로 본다", () => {
    expect(isAnalyzed(ep({ prep: true, transcribe: true, signals: true }))).toBe(true);
    expect(isAnalyzed(ep({ prep: true, transcribe: true }))).toBe(false);
    expect(isAnalyzed(ep({ prep: true }))).toBe(false);
    expect(isAnalyzed(null)).toBe(false);
  });
});

describe("quickRunStages", () => {
  it("처음 처리하는 회차는 종류별 기본 단계를 전부 돈다", () => {
    expect(quickRunStages(ep({}), "edited")).toEqual(DEFAULT_STAGES.edited);
    expect(quickRunStages(ep({}), "original")).toEqual(DEFAULT_STAGES.original);
  });

  it("영상 읽기만 끝난 회차도 처음부터 돈다 (캐시가 반쪽이면 재사용하지 않는다)", () => {
    expect(quickRunStages(ep({ prep: true }), "edited")).toEqual(DEFAULT_STAGES.edited);
  });

  it("분석이 끝난 편집본은 초안·XML·점수만 다시 만든다", () => {
    const analyzed = ep({ prep: true, transcribe: true, signals: true, shorts: true, export: true });
    expect(quickRunStages(analyzed, "edited")).toEqual(["shorts", "export", "xml", "eval"]);
  });

  it("분석이 끝난 원본은 편집 포인트·점수만 다시 뽑는다", () => {
    expect(quickRunStages(ep({ prep: true, transcribe: true, signals: true }), "original")).toEqual([
      "candidates",
      "eval",
    ]);
  });
});

describe("subtitleRunStages", () => {
  it("아무것도 안 된 회차는 영상 읽기 → 전사 → 자막", () => {
    expect(subtitleRunStages(ep({}))).toEqual(["prep", "transcribe", "subtitles"]);
  });

  it("전사까지 된 회차는 자막 파일만 쓴다", () => {
    expect(subtitleRunStages(ep({ prep: true, transcribe: true }))).toEqual(["subtitles"]);
  });

  it("영상만 읽은 회차는 전사부터", () => {
    expect(subtitleRunStages(ep({ prep: true }))).toEqual(["transcribe", "subtitles"]);
  });
});
