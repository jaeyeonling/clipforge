// 화면 문구 규칙 검사: 모든 단계에 이름·기술명·설명이 있고, 사용자에게 보이는 설명은 '~해요'체를 쓴다.
import { describe, expect, it } from "vitest";
import { STAGE_TIP, TIP } from "./tips";
import { STAGES, STAGE_LABEL, STAGE_TECH } from "./types";

describe("단계 문구", () => {
  it.each(STAGES)("%s 단계는 이름·기술명·설명을 모두 갖는다", (s) => {
    expect(STAGE_LABEL[s]?.trim()).toBeTruthy();
    expect(STAGE_TECH[s]?.trim()).toBeTruthy();
    expect(STAGE_TIP[s]?.trim()).toBeTruthy();
  });
});

describe("툴팁 문구", () => {
  const all = [...Object.values(STAGE_TIP), ...Object.values(TIP)];

  it("빈 설명이 없다", () => {
    for (const t of all) expect(t.trim().length).toBeGreaterThan(0);
  });

  it("딱딱한 '~습니다/~ㅂ니다' 대신 '~해요'체를 쓴다", () => {
    const formal = all.filter((t) => /[가-힣](습니다|ㅂ니다)/.test(t) || /(합|됩|입|봅|줍|냅)니다/.test(t));
    expect(formal).toEqual([]);
  });
});
