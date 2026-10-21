// 부팅 · 업데이트 · 오류 화면. 문구는 주소의 쿼리로 받아 textContent 로만 넣는다 (경로 · 예외 문구가 HTML 로 해석되지 않게).
"use strict";
(function () {
  const q = new URLSearchParams(location.search);
  document.getElementById("title").textContent = q.get("title") || "";
  document.getElementById("detail").textContent = q.get("detail") || "";
  document.getElementById("spin").hidden = q.get("spin") !== "1";
})();
