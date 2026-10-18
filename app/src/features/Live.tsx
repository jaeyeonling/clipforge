import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import type { LiveEvent, LiveStatus } from "../api/types";
import { Badge, Button, Card, Empty, cx, fmtTime } from "../components/ui";
import { useApp } from "../state/store";
import { TIP } from "../api/tips";

const SOURCES = [{ key: "screen", label: "화면 캡처 (방송 중)" }, { key: "frames", label: "회차 프레임 재생 (테스트)" }, { key: "video", label: "영상 파일 재생 (테스트)" }];

/**
 * 라이브 탭: 캡처 소스·OBS 설정 → 시작 → 제안(승인/무시)·배너·북마크·이벤트.
 * 승인 모드 기본 ON: 감지한 아이템은 "배너에 추가?" 카드로만 뜨고 사람이 눌러야 OBS 로 나간다.
 */
export function Live() {
  const { liveStatus, liveEvents, refreshLive, selected, toast, fail } = useApp();
  const [source, setSource] = useState("screen");
  const [interval, setInterval_] = useState(1.0);
  const [approval, setApproval] = useState(true);
  const [grades, setGrades] = useState<string[]>(["set", "unique"]);
  const [obsOn, setObsOn] = useState(false);
  const [obsUrl, setObsUrl] = useState("ws://127.0.0.1:4455");
  const [obsPw, setObsPw] = useState("");
  const [obsSource, setObsSource] = useState("득템 배너");
  const [obsSources, setObsSources] = useState<string[] | null>(null);
  const [videoPath, setVideoPath] = useState("");
  const [note, setNote] = useState("");
  const [bannerEdit, setBannerEdit] = useState<string | null>(null);
  const [editText, setEditText] = useState<Record<string, string>>({});
  const [previewTick, setPreviewTick] = useState(0);
  useEffect(() => { if (!liveStatus?.active) return; const id = window.setInterval(() => { setPreviewTick((n) => n + 1); refreshLive().catch(() => {}); }, 2500); return () => window.clearInterval(id); }, [liveStatus?.active, refreshLive]);
  const [busy, setBusy] = useState(false);

  useEffect(() => { refreshLive().catch(() => {}); }, [refreshLive]);
  const st: LiveStatus | null = liveStatus;
  const active = !!st?.active;

  const start = async () => {
    setBusy(true);
    try {
      const config: Record<string, unknown> = { source, interval, approval, grades, game: selected?.game || "d2r" };
      if (source === "frames") { if (!selected) throw new Error("프레임 재생은 회차를 선택해야 합니다"); config.episode = selected.id; config.realtime = true; }
      if (source === "video") { if (!videoPath.trim()) throw new Error("영상 파일 경로가 필요합니다"); config.path = videoPath.trim(); config.realtime = true; }
      if (obsOn) config.obs = { url: obsUrl, password: obsPw, text_source: obsSource };
      await api.liveStart(config); toast("라이브 시작"); await refreshLive();
    } catch (e) { fail(e); } finally { setBusy(false); }
  };
  const stop = async () => { setBusy(true); try { await api.liveStop(); toast("라이브 정지"); await refreshLive(); } catch (e) { fail(e); } finally { setBusy(false); } };
  const mark = async () => { try { await api.liveMark(note); setNote(""); toast("북마크"); await refreshLive(); } catch (e) { fail(e); } };
  const probe = async () => {
    setObsSources(null);
    try { const r = await api.liveObsProbe(obsUrl, obsPw); setObsSources(r.text_sources); toast(`OBS ${r.obs.obs} 연결됨`); if (r.text_sources.length && !r.text_sources.includes(obsSource)) setObsSource(r.text_sources[0]); } catch (e) { fail(e); }
  };
  const approve = useCallback(async (id: string, text?: string) => { try { await api.liveApprove(id, text && text.trim() ? text.trim() : undefined); await refreshLive(); } catch (e) { fail(e); } }, [refreshLive, fail]);
  const dismiss = useCallback(async (id: string) => { try { await api.liveDismiss(id); await refreshLive(); } catch (e) { fail(e); } }, [refreshLive, fail]);
  const saveBanner = async () => {
    if (bannerEdit == null) return;
    try { await api.liveBanner(bannerEdit.split(",").map((x) => x.trim()).filter(Boolean)); setBannerEdit(null); toast("배너 갱신"); await refreshLive(); } catch (e) { fail(e); }
  };

  const pending = (st?.suggestions || []).filter((s) => s.status === "pending");
  const done = (st?.suggestions || []).filter((s) => s.status !== "pending").slice(-8).reverse();
  const sess = st?.session;

  return (
    <div className="live-layout">
      <div>
        <Card title="캡처 · OBS" right={active ? <Badge tone="running">실행 중</Badge> : <Badge>정지</Badge>}>
          <div className="row" style={{ gap: 10 }}>
            <label className="check" data-tip={TIP.liveSource}>화면 가져오기
              <select className="field sm" value={source} onChange={(e) => setSource(e.target.value)} disabled={active}>{SOURCES.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}</select>
            </label>
            {source === "video" && <input className="field sm" style={{ flex: 1, minWidth: 220 }} placeholder="영상 파일 경로" value={videoPath} onChange={(e) => setVideoPath(e.target.value)} disabled={active} />}
            {source === "frames" && <span className="muted xs">선택한 회차 {selected?.id || "-"} 의 1fps 프레임을 실시간처럼 재생</span>}
            <label className="check" data-tip={TIP.liveInterval}>확인 주기(초) <input className="field sm num" type="number" step={0.5} min={0.5} max={5} value={interval} onChange={(e) => setInterval_(Number(e.target.value) || 1)} disabled={active} /></label>
          </div>
          <div className="row" style={{ gap: 10, marginTop: 8 }}>
            <label className={cx("check", approval && "on")} data-tip={TIP.liveApproval}><input type="checkbox" checked={approval} onChange={(e) => setApproval(e.target.checked)} disabled={active} /> 물어보고 넣기 (승인 모드)</label>
            {(["set", "unique", "rare"] as const).map((g) => (
              <label key={g} className={cx("check", grades.includes(g) && "on")}><input type="checkbox" checked={grades.includes(g)} disabled={active} onChange={(e) => setGrades((cur) => (e.target.checked ? [...cur, g] : cur.filter((x) => x !== g)))} /> {{ set: "세트(초록)", unique: "유니크(금)", rare: "희귀(노랑)" }[g]}</label>
            ))}
          </div>
          <div className="row" style={{ gap: 10, marginTop: 8 }}>
            <label className={cx("check", obsOn && "on")} data-tip={TIP.liveObs}><input type="checkbox" checked={obsOn} onChange={(e) => setObsOn(e.target.checked)} disabled={active} /> OBS 연동</label>
            {obsOn && (
              <>
                <input className="field sm" style={{ width: 190 }} value={obsUrl} onChange={(e) => setObsUrl(e.target.value)} disabled={active} title="OBS → 도구 → WebSocket 서버 설정" />
                <input className="field sm" style={{ width: 130 }} type="password" placeholder="비밀번호" value={obsPw} onChange={(e) => setObsPw(e.target.value)} disabled={active} />
                <Button size="sm" variant="ghost" onClick={probe} disabled={active}>연결 확인</Button>
                <label className="check">텍스트 소스
                  {obsSources ? <select className="field sm" value={obsSource} onChange={(e) => setObsSource(e.target.value)} disabled={active}>{obsSources.map((s) => <option key={s}>{s}</option>)}</select>
                    : <input className="field sm" style={{ width: 120 }} value={obsSource} onChange={(e) => setObsSource(e.target.value)} disabled={active} />}
                </label>
              </>
            )}
            <span className="grow" style={{ flex: 1 }} />
            {active ? <Button variant="danger" onClick={stop} disabled={busy}>정지</Button> : <Button variant="primary" onClick={start} disabled={busy}>시작</Button>}
          </div>
          {active && (
            <div className="live-preview">
              {st?.preview_url ? <img src={`${st.preview_url}&t=${previewTick}`} alt="캡처 미리보기" /> : <div className="novideo" style={{ aspectRatio: "16/9" }}>첫 프레임 기다리는 중…</div>}
              <div className="muted xs" style={{ marginTop: 4 }}>지금 캡처되는 화면입니다. <b>게임이 보이지 않으면</b>(검은 화면·바탕화면) 게임을 창 모드/테두리 없는 전체화면으로 바꾸거나, 캡처 영역을 조정해야 합니다.</div>
            </div>
          )}
          {sess && (
            <p className="muted xs" style={{ marginTop: 8 }}>
              세션 {sess.id} · 프레임 {sess.frames} · {sess.obs_connected ? `OBS 연결됨 (${(sess.obs as { obs?: string })?.obs || ""})` : sess.obs && (sess.obs as { error?: string }).error ? `OBS 실패: ${(sess.obs as { error?: string }).error}` : "OBS 없음"} · 북마크 {sess.bookmarks}{sess.last_error ? ` · 오류: ${sess.last_error}` : ""}
            </p>
          )}
        </Card>

        <Card title={`배너 제안 · 대기 ${pending.length}`}>
          <div className="keys" style={{ marginBottom: 6 }}>게임 중엔 <kbd>Ctrl</kbd>+<kbd>Alt</kbd>+<kbd>Y</kbd> 최근 제안 추가 · <kbd>Ctrl</kbd>+<kbd>Alt</kbd>+<kbd>N</kbd> 무시 (데스크톱 앱, 알림으로도 알려줍니다)</div>
          {!pending.length ? <p className="muted small">{active ? "세트·유니크 아이템 라벨이 화면에 뜨면 여기 제안이 올라옵니다." : "라이브를 시작하면 감지된 아이템이 여기 뜹니다. 승인하면 배너 텍스트와 OBS 소스에 추가됩니다."}</p> : (
            <ul className="sug-list">
              {pending.map((s) => (
                <li key={s.id} className={cx("sug", s.grade)}>
                  <div className="grow">
                    <b>{s.head || s.text}</b> <Badge tone={s.grade === "set" ? "ok" : s.grade === "unique" ? "warn" : ""}>{({ set: "세트", unique: "유니크", rare: "희귀", magic: "매직" } as Record<string, string>)[s.grade] || s.grade}</Badge>
                    <div className="muted xs">화면에서 읽은 글자 "{s.text}" (확신 {Math.round(s.score * 100)}%) · {new Date(s.t_wall * 1000).toLocaleTimeString("ko-KR")}{s.t_rec != null ? ` · 녹화 ${fmtTime(s.t_rec)}` : ""}</div>
                  </div>
                  <input className="field sm" style={{ width: 150 }} placeholder={s.head || s.text} value={editText[s.id] ?? ""} onChange={(e) => setEditText((m) => ({ ...m, [s.id]: e.target.value }))} title="배너에 넣을 이름을 고쳐 쓸 수 있습니다 (예: 기드참(매찬34))" onKeyDown={(e) => { if (e.key === "Enter") approve(s.id, editText[s.id]); }} />
                  <Button size="sm" variant="primary" onClick={() => approve(s.id, editText[s.id])}>배너에 추가</Button>
                  <Button size="sm" variant="ghost" onClick={() => dismiss(s.id)}>무시</Button>
                </li>
              ))}
            </ul>
          )}
          {done.length > 0 && <div className="muted xs" style={{ marginTop: 8 }}>최근: {done.map((s) => `${s.head || s.text}(${s.status === "approved" ? "추가" : "무시"})`).join(" · ")}</div>}
        </Card>

        <Card title="득템 배너" right={bannerEdit == null ? <Button size="sm" variant="ghost" onClick={() => setBannerEdit((sess?.banner || "").replace(/^득템\s*:\s*/, ""))} disabled={!active}>편집</Button> : <span className="row"><Button size="sm" variant="primary" onClick={saveBanner}>저장</Button><Button size="sm" variant="ghost" onClick={() => setBannerEdit(null)}>취소</Button></span>}>
          {bannerEdit == null ? <div className="banner-text">{sess?.banner || <span className="muted">비어 있음</span>}</div>
            : <input className="field" value={bannerEdit} onChange={(e) => setBannerEdit(e.target.value)} placeholder="항목을 쉼표로 (예: 슬가,지존참)" />}
          <p className="muted xs" style={{ marginTop: 6 }}>승인한 아이템이 뒤에 붙습니다. 별표 강조(★)는 직접 넣으세요. OBS 연동이 켜져 있으면 텍스트 소스도 함께 바뀝니다.</p>
        </Card>
      </div>

      <div>
        <Card title="북마크" right={<span className="keys"><kbd>Ctrl</kbd>+<kbd>Alt</kbd>+<kbd>M</kbd> 전역 단축키 (데스크톱 앱)</span>}>
          <div className="row">
            <input className="field sm" style={{ flex: 1 }} placeholder="메모 (선택)" value={note} onChange={(e) => setNote(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") mark(); }} disabled={!active} />
            <Button size="sm" variant="primary" onClick={mark} disabled={!active} data-tip={TIP.bookmark}>지금 북마크</Button>
          </div>
          <ul className="bm-list">
            {(st?.bookmarks || []).slice().reverse().slice(0, 12).map((b) => (
              <li key={b.id}><span className="mono xs">{new Date(b.t_wall * 1000).toLocaleTimeString("ko-KR")}{b.t_rec != null ? ` · 녹화 ${fmtTime(b.t_rec)}` : ""}</span><Badge tone={b.kind === "drop" ? "ok" : b.kind === "chat" ? "accent" : ""}>{b.kind}</Badge><span className="small">{b.note}</span></li>
            ))}
            {!st?.bookmarks?.length && <li className="muted small">방송이 끝난 뒤 원본에서 편집 포인트를 찾을 때 이 시각들을 먼저 봅니다. 득템 승인·채팅 폭주·단축키가 북마크를 만듭니다.</li>}
          </ul>
        </Card>
        <Card title="이벤트">
          {!liveEvents.length ? <Empty title="아직 이벤트가 없습니다" /> : (
            <ul className="ev-list">
              {liveEvents.slice(-40).reverse().map((e: LiveEvent, i) => (
                <li key={i} className={cx("ev", e.type)}><span className="mono xs muted">{new Date(e.t * 1000).toLocaleTimeString("ko-KR")}</span><span className="type">{e.type}</span><span className="small">{describe(e)}</span></li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </div>
  );
}

function describe(e: LiveEvent): string {
  switch (e.type) {
    case "suggestion": return `${e.head || e.text} (${e.grade}) ${e.status}`;
    case "label": return `${e.text} (${e.grade}, 사전에 없음)`;
    case "bookmark": return `${e.kind} ${e.note || ""}`;
    case "banner": return String(e.text);
    case "started": return `시작 · 소스 ${e.source}`;
    case "stopped": return `정지 · 프레임 ${e.frames}`;
    case "heartbeat": return `프레임 ${e.frames}`;
    default: return String(e.message || "");
  }
}
