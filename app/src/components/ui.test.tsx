import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Tabs, Toasts, cx, fmtDur, fmtTime } from "./ui";

describe("fmtTime", () => {
  it("1시간 미만은 m:ss, 이상은 h:mm:ss", () => {
    expect(fmtTime(0)).toBe("0:00");
    expect(fmtTime(65.9)).toBe("1:05");
    expect(fmtTime(3600 + 62)).toBe("1:01:02");
  });
  it("값이 없거나 숫자가 아니면 -", () => {
    expect(fmtTime(null)).toBe("-");
    expect(fmtTime(undefined)).toBe("-");
    expect(fmtTime(Number.NaN)).toBe("-");
  });
});

describe("fmtDur", () => {
  it("1분 미만은 초, 이상은 분·초", () => {
    expect(fmtDur(42)).toBe("42초");
    expect(fmtDur(125)).toBe("2분 5초");
  });
  it("반올림이 분 경계를 넘어도 '60초'가 나오지 않는다", () => {
    expect(fmtDur(59.6)).toBe("1분 0초");
    expect(fmtDur(119.6)).toBe("2분 0초");
  });
  it("음수는 0초", () => {
    expect(fmtDur(-3)).toBe("0초");
  });
});

describe("cx", () => {
  it("참인 클래스만 공백으로 잇는다", () => {
    expect(cx("a", false, null, undefined, "b")).toBe("a b");
  });
});

describe("Tabs", () => {
  it("선택된 탭을 aria-selected 로 알리고, 누르면 onChange 로 키를 넘긴다", () => {
    const onChange = vi.fn();
    render(
      <Tabs
        value="make"
        onChange={onChange}
        items={[
          { key: "make", label: "만들기" },
          { key: "shorts", label: "쇼츠 초안", count: 3, tip: "초안을 판정하는 곳" },
        ]}
      />,
    );
    expect(screen.getByRole("tab", { name: "만들기" }).getAttribute("aria-selected")).toBe("true");
    const shorts = screen.getByRole("tab", { name: /쇼츠 초안/ });
    expect(shorts.getAttribute("data-tip")).toBe("초안을 판정하는 곳");
    expect(shorts.textContent).toContain("3");
    fireEvent.click(shorts);
    expect(onChange).toHaveBeenCalledWith("shorts");
  });
});

describe("Toasts", () => {
  it("액션이 있는 토스트는 버튼을 보여주고 누르면 실행한다", () => {
    const onClick = vi.fn();
    render(
      <Toasts
        items={[
          { id: 1, text: "저장됐어요", bad: false },
          { id: 2, text: "자막을 만들었어요", bad: false, action: { label: "자막 파일 열기", onClick } },
        ]}
      />,
    );
    expect(screen.getByText("저장됐어요")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "자막 파일 열기" }));
    expect(onClick).toHaveBeenCalledOnce();
  });
});
