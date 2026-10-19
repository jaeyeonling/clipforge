import { useState } from "react";
import type { Episode } from "../api/types";
import { Button, Card, cx } from "../components/ui";
import { inShell, shell } from "../shell";
import { TIP } from "../api/tips";
import { useApp } from "../state/store";

/** 처음 쓰는 사람을 위한 세 조각: 시작 화면(회차 없음) · 진행 띠(다음 할 일) · 도움말 탭 */

export type Tab = "candidates" | "editpoints" | "pipeline" | "calibration" | "metrics" | "live" | "settings" | "help";

const STEPS_EDITED = [
  { key: "add", label: "영상 넣기", tab: "pipeline" as Tab, tip: TIP.stepAdd },
  { key: "run", label: "분석 실행", tab: "pipeline" as Tab, tip: TIP.stepRun },
  { key: "review", label: "초안 보고 판정", tab: "candidates" as Tab, tip: TIP.stepReview },
  { key: "take", label: "Premiere 로 가져가기", tab: "candidates" as Tab, tip: TIP.stepTake },
];
const STEPS_ORIGINAL = [
  { key: "add", label: "원본 넣기", tab: "pipeline" as Tab, tip: "방송 녹화 원본(수 시간)을 넣어요. 복사하지 않아요." },
  { key: "run", label: "분석 실행", tab: "pipeline" as Tab, tip: "'편집 포인트 뽑기' 한 번. 원본 길이의 약 1/8 시간." },
  { key: "review", label: "편집 포인트 확인", tab: "editpoints" as Tab, tip: "후보를 재생해 보고 정답 구간에 종류를 붙여요." },
];

/** 선택한 회차가 어느 단계인지와 다음 할 일 */
export function stepOf(e: Episode | null): { idx: number; next: string; steps: typeof STEPS_EDITED } {
  const steps = e?.kind === "original" ? STEPS_ORIGINAL : STEPS_EDITED;
  if (!e) return { idx: 0, next: "왼쪽 아래에서 영상을 고르거나 끌어다 놓으세요.", steps };
  const s = e.stages || {};
  if (e.kind === "original") {
    if (!s.candidates) return { idx: 1, next: "'편집 포인트 뽑기'를 누르세요. 원본 길이에 따라 수십 분 걸려요.", steps };
    return { idx: 2, next: "편집 포인트 탭에서 후보를 재생해 보고 정답 구간에 종류를 붙이세요.", steps };
  }
  if (!s.export) return { idx: 1, next: "'쇼츠 초안 만들기'를 누르세요. 4K 10분이면 약 10분 걸려요.", steps };
  return { idx: 2, next: "초안을 재생해 보고 쓸 만함 / 안 씀을 누르세요. 쓸 초안은 초안 폴더나 Premiere XML로 가져가면 돼요.", steps };
}

export function Stepper({ onTab }: { onTab: (t: Tab) => void }) {
  const { selected } = useApp();
  const { idx, next, steps } = stepOf(selected);
  return (
    <div className="stepper">
      <div className="next"><b>다음</b>{next}</div>
      <ol>
        {steps.map((st, i) => (
          <li key={st.key} className={cx(i < idx && "done", i === idx && "now")} onClick={() => onTab(st.tab)} data-tip={st.tip}>
            <span className="n">{i < idx ? "✓" : i + 1}</span><span>{st.label}</span>
          </li>
        ))}
      </ol>
    </div>
  );
}

export function Welcome({ onTab }: { onTab: (t: Tab) => void }) {
  const { registerVideos, fail } = useApp();
  const [path, setPath] = useState("");
  const pick = async () => { if (!shell) return; try { const ps = await shell.shell.pickVideos(); if (ps.length) await registerVideos(ps, {}); } catch (e) { fail(e); } };
  return (
    <div className="welcome">
      <h2>편집본 하나 넣으면<br />쇼츠 초안이 나와요</h2>
      <p className="muted">세 단계면 끝나요. 쓸 만함 / 안 씀을 누를수록 다음 회차부터 취향에 맞춰 가요.</p>
      <ol className="welcome-steps">
        <li><b>1. 영상 넣기</b><span>편집본 mp4 를 고르거나 이 창에 끌어다 놓아요. 복사하지 않아요.</span></li>
        <li><b>2. 분석 실행</b><span>'쇼츠 초안 만들기' 한 번. 4K 10분 기준 약 10분, 끝나면 알림이 와요.</span></li>
        <li><b>3. 초안 보고 판정</b><span>세로 초안을 재생해 보고 쓸 만함 / 안 씀. 쓸 것은 폴더와 Premiere XML 로 가져가요.</span></li>
      </ol>
      <div className="row" style={{ gap: 8, marginTop: 14 }}>
        {inShell ? <Button variant="primary" onClick={pick}>영상 넣기</Button> : (
          <>
            <input className="field" style={{ minWidth: 320 }} placeholder="영상 파일 경로 (C:\...\ep60.mp4)" value={path} onChange={(e) => setPath(e.target.value)} />
            <Button variant="primary" onClick={() => path.trim() && registerVideos([path.trim()], {}).catch(fail)}>등록</Button>
          </>
        )}
        <Button variant="ghost" onClick={() => onTab("help")}>도움말 보기</Button>
      </div>
      <p className="muted xs" style={{ marginTop: 14 }}>원본 녹화(수 시간짜리)로 편집 포인트를 뽑는 모드와, 방송 중 득템 배너를 돕는 라이브 탭도 있어요. 먼저 편집본 하나로 시작해 보세요.</p>
    </div>
  );
}

export function Help() {
  return (
    <div className="help">
      <Card title="1. 영상 넣기"><p className="muted xs" style={{ marginTop: 0 }}>낯선 말에 마우스를 올리면 설명이 떠요.</p>
        <p>왼쪽 아래 <b>영상 파일 선택…</b> 또는 영상을 창에 끌어다 놓기. 여러 개 한 번에 돼요. 복사하지 않으므로 원본 파일을 옮기면 다시 등록해야 해요.</p>
        <p className="muted small">종류 선택은 <b>편집본 → 쇼츠</b> 그대로 두세요. 원본 녹화를 넣어 편집 포인트를 뽑을 때만 바꿔요. 유튜브 제목을 적어 두면 제목의 득템 이름을 정답으로 써요(선택).</p>
      </Card>
      <Card title="2. 분석 실행">
        <p><b>실행</b> 탭 → <b>쇼츠 초안 만들기</b>. 처음 처리하는 회차는 4K 10분 기준 약 10분, 다음부터는 1~2분. 남은 시간이 표시되고 창을 닫아도 트레이에서 계속 돌아요.</p>
        <p className="muted small">끝나면 쇼츠 초안 탭으로 넘어가요. 주의 표시(화면 영역 점검)가 뜨면 화면 영역 탭에서 미리보기를 한 번 보세요. 고급 설정을 열면 단계를 골라 돌릴 수 있어요.</p>
        <p className="muted small">자막만 필요하면 큰 버튼 옆 <b>자막만 만들기</b>. 영상 전체 자막 파일이 생겨요. Premiere 는 SRT 를 캡션으로, VEGAS Pro 는 .vegas.txt 를 삽입 → 파일에서 자막 삽입으로 가져가요(프로젝트 fps 는 영상과 같게).</p>
      </Card>
      <Card title="3. 초안 보고 판정">
        <p>세로 초안이 순위대로 나와요. 재생해 보고 <b>쓸 만함</b> / <b>안 씀</b>(이유 하나). 같은 버튼을 다시 누르면 취소.</p>
        <p className="muted small">키보드: ← → 이동 · K 쓸 만함 · N 다음 1~6 이유 · Space 재생 · C 두 개 비교 · Esc 닫기. 판정은 자동 저장되고 다음 회차 순위에 반영돼요.</p>
      </Card>
      <Card title="4. 가져가기">
        <p>쇼츠 초안 탭 위 <b>초안 폴더</b>(세로 mp4 + 자막) · <b>Premiere XML</b>(세로 시퀀스) · <b>리뷰 XML</b>(원본 전체 + 후보 트랙 + 마커). Premiere 에서 파일 → 가져오기로 열어요.</p>
      </Card>
      <Card title="업데이트 · 문제 해결">
        <p>새 버전이 있으면 위에 한 줄 떠요. <b>지금 적용</b>은 몇 초, 재설치 없음. 작업 중이면 끝난 뒤.</p>
        <p className="muted small">빨간 카드에 원인과 할 일이 적혀 있고 <b>같은 설정으로 다시 실행</b>으로 대부분 해결돼요. 안 되면 설정 → <b>피드백 zip 만들기</b> 해서 보내 주세요(영상은 안 들어가요).</p>
      </Card>
      <Card title="라이브 탭 (실험 기능)">
        <p>방송 중 화면에서 세트·유니크 템 이름을 읽어 "배너에 추가?"로 물어보고, 승인하면 득템 배너 텍스트(OBS 텍스트 소스)에 넣어요. 게임 중엔 <b>Ctrl+Alt+Y</b> 추가 · <b>Ctrl+Alt+N</b> 무시 · <b>Ctrl+Alt+M</b> 북마크.</p>
        <p className="muted small">아직 실방송 검증 전이라 승인 모드만 쓰세요. 자동으로 방송에 나가는 일은 없어요. 시작하면 캡처 미리보기가 보이니 게임 화면이 잡히는지 먼저 확인하세요.</p>
      </Card>
    </div>
  );
}
