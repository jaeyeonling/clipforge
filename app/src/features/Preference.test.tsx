import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { Preference } from "../api/types";

const base: Preference = {
  weights: { payoff: 0.35, reaction: 0.25, chat: 0.15, completeness: 0.15, hook: 0.1 },
  default: { payoff: 0.35, reaction: 0.25, chat: 0.15, completeness: 0.15, hook: 0.1 },
  n_keep: 0,
  n_no: 0,
  learned: false,
  blend: 0,
  reason: "",
  updated: "",
};
const pref = vi.fn<() => Promise<Preference>>();
vi.mock("../api/client", () => ({ api: { preference: () => pref() } }));

const { PreferenceCard, PreferenceLine, preferenceSentence } = await import("./Preference");

describe("preferenceSentence", () => {
  it("판정이 없으면 누를수록 맞춰진다고 안내한다", () => {
    expect(preferenceSentence(base)).toContain("누를수록");
  });
  it("아직 반영 전이면 엔진이 준 이유를 그대로", () => {
    expect(preferenceSentence({ ...base, n_keep: 2, reason: "판정 2개예요. 6개부터 반영해요" })).toBe(
      "판정 2개예요. 6개부터 반영해요",
    );
  });
  it("반영 중이면 판정 수를 말한다", () => {
    expect(preferenceSentence({ ...base, n_keep: 5, n_no: 4, learned: true })).toBe(
      "판정 9개를 반영해 순위를 매기고 있어요",
    );
  });
});

describe("PreferenceLine / PreferenceCard", () => {
  it("한 줄 요약을 보여준다", async () => {
    pref.mockResolvedValue({ ...base, n_keep: 1, reason: "판정 1개예요. 6개부터 반영해요" });
    render(<PreferenceLine version={1} />);
    await waitFor(() => expect(screen.getByText("판정 1개예요. 6개부터 반영해요")).toBeTruthy());
  });

  it("반영 중이면 바뀐 축에 화살표와 차이를 표시한다", async () => {
    pref.mockResolvedValue({
      ...base,
      n_keep: 8,
      n_no: 8,
      learned: true,
      blend: 0.44,
      weights: { payoff: 0.3, reaction: 0.25, chat: 0.2, completeness: 0.15, hook: 0.1 },
    });
    render(<PreferenceCard version={1} />);
    await waitFor(() => expect(screen.getByText("채팅 반응")).toBeTruthy());
    expect(screen.getByText("44")).toBeTruthy();
    expect(screen.getByText("▲5", { exact: false })).toBeTruthy();
    expect(screen.getByText("▼5", { exact: false })).toBeTruthy();
  });
});
