import { fireEvent, render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { useTooltips } from "./useTooltips";

function Host() {
  useTooltips();
  return (
    <div>
      <button data-tip={"첫 줄\n둘째 줄"}>설명 있는 버튼</button>
      <span>설명 없는 글자</span>
    </div>
  );
}

const box = () => document.querySelector<HTMLDivElement>(".tipbox");

describe("useTooltips", () => {
  afterEach(() => document.body.replaceChildren());

  it("data-tip 이 있는 요소에 마우스를 올리면 body 의 툴팁 박스에 설명을 띄운다", () => {
    const { getByText } = render(<Host />);
    expect(box()?.hidden).toBe(true);
    fireEvent.mouseOver(getByText("설명 있는 버튼"));
    expect(box()?.hidden).toBe(false);
    expect(box()?.textContent).toBe("첫 줄\n둘째 줄");
  });

  it("설명이 없는 곳으로 나가거나 누르면 닫는다", () => {
    const { getByText } = render(<Host />);
    fireEvent.mouseOver(getByText("설명 있는 버튼"));
    fireEvent.mouseOut(getByText("설명 있는 버튼"), { relatedTarget: getByText("설명 없는 글자") });
    expect(box()?.hidden).toBe(true);
    fireEvent.mouseOver(getByText("설명 있는 버튼"));
    fireEvent.mouseDown(document.body);
    expect(box()?.hidden).toBe(true);
  });

  it("언마운트하면 박스를 치운다", () => {
    const { unmount } = render(<Host />);
    expect(box()).not.toBeNull();
    unmount();
    expect(box()).toBeNull();
  });
});
