import { useEffect } from "react";

/** data-tip 툴팁: 하나의 고정 박스를 body 에 두고 마우스가 올라간 요소 옆에 옮긴다. 아래가 모자라면 위로. */
export function useTooltips() {
  useEffect(() => {
    const box = document.createElement("div");
    box.className = "tipbox";
    box.hidden = true;
    document.body.appendChild(box);
    let cur: Element | null = null;
    const hide = () => {
      cur = null;
      box.hidden = true;
    };
    const show = (el: Element) => {
      const t = el.getAttribute("data-tip");
      if (!t) return hide();
      cur = el;
      box.textContent = t;
      box.hidden = false;
      const r = el.getBoundingClientRect();
      const bw = box.offsetWidth,
        bh = box.offsetHeight;
      const x = Math.min(Math.max(8, r.left), window.innerWidth - bw - 8);
      let y = r.bottom + 6;
      if (y + bh > window.innerHeight - 8) y = Math.max(8, r.top - bh - 6);
      box.style.left = `${x}px`;
      box.style.top = `${y}px`;
    };
    const over = (e: MouseEvent) => {
      const el = (e.target as Element | null)?.closest?.("[data-tip]") ?? null;
      if (el === cur) return;
      if (el) show(el);
      else hide();
    };
    const out = (e: MouseEvent) => {
      if (cur && !(e.relatedTarget as Element | null)?.closest?.("[data-tip]")) hide();
    };
    document.addEventListener("mouseover", over);
    document.addEventListener("mouseout", out);
    document.addEventListener("mousedown", hide, true);
    document.addEventListener("scroll", hide, true);
    window.addEventListener("blur", hide);
    return () => {
      document.removeEventListener("mouseover", over);
      document.removeEventListener("mouseout", out);
      document.removeEventListener("mousedown", hide, true);
      document.removeEventListener("scroll", hide, true);
      window.removeEventListener("blur", hide);
      box.remove();
    };
  }, []);
}
