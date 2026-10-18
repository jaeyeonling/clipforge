import type { ReactNode } from "react";

export const cx = (...xs: (string | false | null | undefined)[]) => xs.filter(Boolean).join(" ");

export const fmtTime = (t: number | undefined | null): string => {
  if (t == null || !isFinite(t)) return "-";
  const s = Math.max(0, Math.floor(t));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  return h ? `${h}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}` : `${m}:${String(sec).padStart(2, "0")}`;
};
export const fmtWhen = (unix: number | undefined): string =>
  unix ? new Date(unix * 1000).toLocaleString("ko-KR", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "";
export const fmtDur = (sec: number): string => (sec >= 60 ? `${Math.floor(sec / 60)}분 ${Math.round(sec % 60)}초` : `${Math.round(sec)}초`);

export function Button({ variant, size, className, ...rest }: React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "ghost" | "danger"; size?: "sm" }) {
  return <button className={cx("btn", variant, size, className)} {...rest} />;
}

export function Badge({ tone, mono, children, title }: { tone?: string; mono?: boolean; children: ReactNode; title?: string }) {
  return <span className={cx("badge", tone, mono && "mono")} title={title}>{children}</span>;
}

export function Card({ title, right, children, className }: { title?: ReactNode; right?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={cx("card", className)}>
      {(title || right) && <div className="card-title"><span>{title}</span><span className="grow" />{right}</div>}
      {children}
    </section>
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return <div className="empty"><b>{title}</b>{children && <span className="small">{children}</span>}</div>;
}

export function Progress({ pct, state, indeterminate }: { pct: number; state?: "error" | "done" | ""; indeterminate?: boolean }) {
  return <div className={cx("progress", state)}><div className={cx("bar", indeterminate && "indeterminate")} style={{ width: indeterminate ? undefined : `${Math.max(0, Math.min(100, pct))}%` }} /></div>;
}

export function Spinner() { return <span className="spinner" aria-label="loading" />; }

export function Toasts({ items }: { items: { id: number; text: string; bad: boolean; action?: { label: string; onClick: () => void } }[] }) {
  return (
    <div className="toasts">
      {items.map((t) => (
        <div key={t.id} className={cx("toast", t.bad && "bad", t.action && "with-action")}>
          <span>{t.text}</span>
          {t.action && <button className="btn sm primary" onClick={t.action.onClick}>{t.action.label}</button>}
        </div>
      ))}
    </div>
  );
}

export function Tabs<T extends string>({ value, onChange, items }: { value: T; onChange: (v: T) => void; items: { key: T; label: string; count?: number | string; tip?: string }[] }) {
  return (
    <nav className="tabs" role="tablist">
      {items.map((it) => (
        <button key={it.key} role="tab" aria-selected={value === it.key} className={cx("tab", value === it.key && "active")} onClick={() => onChange(it.key)} data-tip={it.tip}>
          {it.label}{it.count != null && <span className="count">{it.count}</span>}
        </button>
      ))}
    </nav>
  );
}
