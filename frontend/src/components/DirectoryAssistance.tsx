import { useEffect, useRef, useState } from "react";
import { useGSAP } from "@gsap/react";
import { FIND, PRESETS, money } from "../lib/directory";
import { gsap, prefersReducedMotion } from "../lib/motion";
import type { GrayDecision, LayaMode, SessionEntry, Ticket, TicketStep } from "../lib/types";
import "../styles/assist.css";

export interface AssistanceProps {
  ticket: Ticket | null;
  busy: boolean;
  error: string;
  online: boolean;
  mode: LayaMode;
  serverMode: string | null;
  log: SessionEntry[];
  grayLog: GrayDecision[];
  onPlace: (name: string, company: string) => void;
}

const LEGEND: { no: string; q: string }[] = [
  { no: "01", q: "In the bucket?" },
  { no: "02", q: "House style known?" },
  { no: "03", q: "Ask Treg to find" },
  { no: "04", q: "Pencil it in" },
];

function stepColors(kind: TicketStep["kind"]): { no: string; q: string; a: string } {
  return {
    no: kind === "hit" ? "var(--vermilion)" : kind === "guess" ? "var(--pencil)" : "var(--ink-3)",
    q: kind === "idle" || kind === "skip" ? "var(--ink-4)" : "var(--ink)",
    a:
      kind === "miss"
        ? "var(--ink-3)"
        : kind === "guess"
          ? "var(--pencil)"
          : kind === "skip"
            ? "var(--ink-4)"
            : "var(--ink)",
  };
}

export function DirectoryAssistance(props: AssistanceProps) {
  const { ticket, busy, error, online, mode, serverMode, log, onPlace } = props;
  const [name, setName] = useState("");
  const [company, setCompany] = useState("");
  const [reveal, setReveal] = useState<{ no: string | null; n: number }>({ no: null, n: 0 });
  const sectionRef = useRef<HTMLElement | null>(null);

  const revealed = reveal.no === (ticket?.no ?? null) ? reveal.n : 0;

  useEffect(() => {
    if (!ticket) return;
    const no = ticket.no;
    setReveal({ no, n: 0 });
    const timers: number[] = [];
    for (let i = 1; i <= 5; i += 1) {
      timers.push(window.setTimeout(() => setReveal({ no, n: i }), 300 + i * 520));
    }
    return () => {
      timers.forEach((timer) => window.clearTimeout(timer));
    };
  }, [ticket]);

  useGSAP(
    () => {
      const root = sectionRef.current;
      if (!root || revealed === 0 || prefersReducedMotion()) return;
      if (revealed <= 4) {
        const row = root.querySelector(`[data-row="${revealed - 1}"]`);
        if (row) gsap.from(row, { autoAlpha: 0.2, y: 6, duration: 0.45, ease: "power2.out" });
        return;
      }
      const stamp = root.querySelector("[data-stamp]");
      if (stamp) {
        gsap.fromTo(
          stamp,
          { scale: 1.6, autoAlpha: 0, rotate: -16 },
          { scale: 1, autoAlpha: 1, rotate: -6, duration: 0.4, ease: "power3.out" },
        );
      }
    },
    { scope: sectionRef, dependencies: [revealed] },
  );

  const submit = () => onPlace(name, company);

  const pick = (presetName: string, presetCo: string) => {
    setName(presetName);
    setCompany(presetCo);
    onPlace(presetName, presetCo);
  };

  const rows: { no: string; q: string; step: TicketStep | null; shown: boolean }[] = ticket
    ? ticket.steps.map((step, index) => ({ no: step.no, q: step.q, step, shown: index < revealed }))
    : LEGEND.map((entry) => ({ no: entry.no, q: entry.q, step: null, shown: false }));

  const countOf = (code: SessionEntry["code"]) => log.filter((entry) => entry.code === code).length;
  const billed = log.reduce((sum, entry) => sum + entry.cost, 0);
  const every = log.length * FIND;
  const statement: { label: string; value: string }[] = [
    { label: "Calls placed", value: String(log.length) },
    { label: "From the bucket", value: String(countOf("KN")) },
    { label: "Built & verified", value: String(countOf("VF")) },
    { label: "Found by Treg", value: String(countOf("FD")) },
    { label: "Pencilled in", value: String(countOf("PG")) },
    { label: "Billed", value: money(billed) },
    { label: "Every call a find", value: money(every) },
    {
      label: "Saved",
      value: log.length ? `${money(every - billed)} · ${Math.round(((every - billed) / every) * 100)}%` : "—",
    },
  ];

  const done = Boolean(ticket) && revealed >= 5;

  return (
    <section
      ref={sectionRef}
      id="assist"
      data-sec=""
      data-folio="pp. 10–11"
      data-screen-label="Directory Assistance"
      className="assist"
    >
      <div className="assist-inner">
        <div className="pagehead">
          <span>Directory assistance</span>
          <span className="ph-mid">Bucket.io directory</span>
          <span>10–11</span>
        </div>

        <div className="assist-head">
          <h2 className="display-lg" data-reveal>
            Place
            <br />a call
          </h2>
          <p className="assist-lede" data-reveal>
            Type a name and a company. The bucket answers first; Treg only when it must. Every call is placed against{" "}
            {online ? "this bucket" : "a simulated bucket in the browser"}, and it remembers.
          </p>
        </div>

        <div className="assist-cols">
          <div className="assist-left">
            <label className="field">
              <span className="micro">Party’s name</span>
              <input
                className="field-input"
                value={name}
                onChange={(event) => setName(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") submit();
                }}
                placeholder="Iris Calloway"
                autoComplete="off"
              />
            </label>

            <label className="field">
              <span className="micro">Company</span>
              <input
                className="field-input"
                value={company}
                onChange={(event) => setCompany(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") submit();
                }}
                placeholder="Meridian Freight"
                autoComplete="off"
              />
            </label>

            {error ? <div className="assist-error">{error}</div> : null}

            <div>
              <button type="button" className="btn btn-ink assist-submit" onClick={submit} disabled={busy}>
                {busy ? "Placing…" : "Place the call →"}
              </button>
            </div>

            <div className="assist-presets">
              <div className="micro assist-presets-title">Or try these, in order</div>
              <div className="assist-preset-list">
                {PRESETS.map((preset) => (
                  <button
                    type="button"
                    className="assist-preset"
                    key={preset.n}
                    onClick={() => pick(preset.name, preset.co)}
                  >
                    <span className="assist-preset-no">{preset.n}</span>
                    <span className="assist-preset-name">
                      {preset.name} <span className="assist-preset-co">· {preset.co}</span>
                    </span>
                    <span className="assist-preset-note">{preset.note}</span>
                  </button>
                ))}
              </div>
            </div>
          </div>

          <div className="assist-ticket">
            <div className="assist-ticket-head">
              <span className="assist-ticket-no">
                Toll ticket No. {ticket?.no ?? String(log.length + 1).padStart(4, "0")}
              </span>
              <span className="micro micro-sm">
                {ticket?.when ?? "—"} · Laya {mode.toLowerCase()}
              </span>
            </div>

            {!online ? (
              <div className="micro assist-ticket-note">Offline demo — the bucket is simulated in the browser.</div>
            ) : null}
            {online && serverMode ? <div className="micro assist-ticket-note">Server Laya: {serverMode}</div> : null}

            <div className="assist-party">
              <div className="assist-party-name">{ticket?.party ?? "Awaiting a call"}</div>
              <div className="assist-party-co">{ticket?.coName ?? "The line is open."}</div>
            </div>

            {rows.map((row, index) => {
              const kind: TicketStep["kind"] = row.shown && row.step ? row.step.kind : "idle";
              const colors = stepColors(kind);
              const costText = row.shown && row.step ? (kind === "skip" ? "—" : money(row.step.cost)) : "";
              const costColor = row.step && row.step.cost ? "var(--ink)" : "var(--ink-3)";
              return (
                <div className="assist-step" data-row={String(index)} key={row.no}>
                  <span className="assist-step-no" style={{ color: colors.no }}>
                    {row.no}
                  </span>
                  <div className="assist-step-body">
                    <div className="assist-step-q" style={{ color: colors.q }}>
                      {row.q}
                    </div>
                    {row.shown && row.step ? (
                      <>
                        <div className="assist-step-a" style={{ color: colors.a }}>
                          {row.step.a}
                        </div>
                        {row.step.lines.map((line, lineIndex) => (
                          <div className="assist-step-line" key={lineIndex}>
                            <span>{line.t}</span>
                            <span>{line.c}</span>
                          </div>
                        ))}
                        {row.step.cands ? (
                          <div className="assist-cands">
                            <div className="assist-cand-grid assist-cand-head">
                              <span>Candidate</span>
                              <span>Rules</span>
                              <span>Laya</span>
                            </div>
                            {row.step.cands.map((candidate) => (
                              <div
                                className="assist-cand-grid assist-cand-row"
                                key={candidate.email}
                                style={{ color: candidate.color }}
                              >
                                <span>
                                  {candidate.email} <b className="assist-cand-mark">{candidate.mark}</b>
                                </span>
                                <span style={{ fontWeight: candidate.rw }}>{candidate.rules}</span>
                                <span style={{ fontWeight: candidate.lw }}>{candidate.laya}</span>
                              </div>
                            ))}
                            {row.step.candNote ? (
                              <div className="micro micro-sm assist-cand-note">{row.step.candNote}</div>
                            ) : null}
                          </div>
                        ) : null}
                      </>
                    ) : null}
                  </div>
                  <span className="assist-step-cost" style={{ color: costColor }}>
                    {costText}
                  </span>
                </div>
              );
            })}

            {ticket && done ? (
              <>
                <div className="assist-charged">
                  <span className="assist-charged-label">Charged</span>
                  <span className="assist-charged-total">{money(ticket.total)}</span>
                  <span className="assist-charged-cold">A cold find would have cost</span>
                  <span className="assist-charged-coldv">{money(FIND)}</span>
                </div>
                <div className="assist-listed">
                  <div className="assist-listed-main">
                    <div className="micro assist-listed-label">Listed as</div>
                    <div className="assist-listed-name">
                      <b>{ticket.last}</b> {ticket.first} <span>{ticket.coName}</span>
                    </div>
                    <div className="rowline assist-listed-mail">
                      <span className="leader-tight" />
                      <span className={`push assist-listed-email${ticket.guess ? " pencil" : ""}`}>{ticket.email}</span>
                      <b className={`assist-listed-code${ticket.guess ? " is-guess" : ""}`}>{ticket.code}</b>
                    </div>
                  </div>
                  <div className="stamp" data-stamp>
                    {ticket.stamp}
                  </div>
                </div>
              </>
            ) : null}

            {!ticket ? (
              <div className="micro assist-idle">Nothing on the line yet. Place a call, or pick one on the left.</div>
            ) : null}
          </div>
        </div>

        <div className="assist-statement" data-reveal>
          <div className="assist-statement-head">
            <span className="assist-statement-title">Statement of charges</span>
            <span className="micro">This session</span>
          </div>
          <div className="assist-statement-grid">
            {statement.map((cell) => (
              <div className="assist-statement-cell" key={cell.label}>
                <div className="micro micro-sm">{cell.label}</div>
                <div className="assist-statement-v">{cell.value}</div>
              </div>
            ))}
          </div>
        </div>

        <div className="folio">— 10 · 11 —</div>
      </div>
    </section>
  );
}
