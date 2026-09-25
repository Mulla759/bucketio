import { useMemo, useRef } from "react";
import type { ChangeEvent } from "react";
import { fmtInt, fmtPct, statusLabel } from "../lib/format";
import { scrollToId } from "../lib/motion";
import type { DirectoryRow } from "../lib/types";
import "../styles/white.css";

export interface WhitePagesProps {
  rows: DirectoryRow[];
  total: number;
  online: boolean;
  loading: boolean;
  query: string;
  onQuery: (value: string) => void;
  status: string;
  onStatus: (value: string) => void;
  onImport: (file: File) => void;
  exportUrl: string;
  onNav: (id: string) => void;
}

const LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ".split("");

const STATUSES = [
  "valid",
  "invalid",
  "catch_all",
  "risky",
  "pattern_guess",
  "unverified",
  "unknown",
  "no_domain",
  "not_found",
];

interface WhiteGroup {
  letter: string;
  anchor: string;
  rows: DirectoryRow[];
}

interface WhitePage {
  folio: string;
  ad: boolean;
  guide: string;
  groups: WhiteGroup[];
}

function fold(value: string): string {
  return String(value ?? "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "");
}

function letterOf(row: DirectoryRow): string {
  const letter = fold(row.last).trim().charAt(0).toUpperCase();
  return /^[A-Z]$/.test(letter) ? letter : "";
}

/** Guide words are a printing mark, not the record: keep them one line long. */
function clipGuide(value: string, max = 24): string {
  const text = fold(String(value ?? "").trim()).toUpperCase();
  return text.length > max ? `${text.slice(0, max - 1).trimEnd()}…` : text;
}

export function WhitePages({
  rows,
  total,
  online,
  loading,
  query,
  onQuery,
  status,
  onStatus,
  onImport,
  exportUrl,
  onNav,
}: WhitePagesProps) {
  const fileRef = useRef<HTMLInputElement>(null);

  const { pages, index, guide } = useMemo(() => {
    const sorted = rows.slice().sort((a, b) => {
      const byLast = fold(a.last).localeCompare(fold(b.last));
      return byLast !== 0 ? byLast : fold(a.first).localeCompare(fold(b.first));
    });

    const byLetter = new Map<string, DirectoryRow[]>();
    for (const row of sorted) {
      const letter = letterOf(row);
      if (!letter) continue;
      const list = byLetter.get(letter);
      if (list) list.push(row);
      else byLetter.set(letter, [row]);
    }

    const page = (from: string, to: string, folio: string, ad: boolean): WhitePage => {
      const groups = Array.from(byLetter.keys())
        .filter((letter) => letter >= from && letter <= to)
        .sort()
        .map((letter) => ({ letter, anchor: `wp-${letter}`, rows: byLetter.get(letter) ?? [] }));
      const people = groups.flatMap((group) => group.rows);
      const words = people.length
        ? `${clipGuide(people[0].last)} — ${clipGuide(people[people.length - 1].last)}`
        : "";
      return { folio, ad, guide: words, groups };
    };

    const pageViews = [page("A", "L", "6", false), page("M", "Z", "7", true)];
    const indexViews = LETTERS.map((letter) => ({ letter, hasRows: byLetter.has(letter) }));
    const everyone = pageViews.flatMap((view) => view.groups.flatMap((group) => group.rows));
    const guideWords = everyone.length
      ? `${clipGuide(everyone[0].last)} — ${clipGuide(everyone[everyone.length - 1].last)}`
      : "";

    return { pages: pageViews, index: indexViews, guide: guideWords };
  }, [rows]);

  const onFile = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (file) onImport(file);
    event.target.value = "";
  };

  return (
    <section
      id="white"
      data-sec=""
      data-folio="pp. 6–7"
      data-screen-label="White Pages"
      className="wp-section sheet-wide"
    >
      <div className="frame-wide">
        <div className="pagehead">
          <span>{guide || "—"}</span>
          <span className="ph-mid">White pages</span>
          <span>6–7</span>
        </div>

        <div className="labelbar" data-reveal="">
          White pages
        </div>

        <p className="wp-intro" data-reveal="">
          Everyone in the bucket, alphabetically — {fmtInt(total)} listings. After each address: <b>FD</b> found by
          Treg, <b>VF</b> verified,{" "}
          <span className="wp-pg">
            <b>PG</b> pencilled in
          </span>
          .
        </p>

        {online ? (
          <div className="wp-tools" data-reveal="">
            <label className="visually-hidden" htmlFor="wp-search">
              Search name, company, email
            </label>
            <input
              id="wp-search"
              className="wp-search"
              type="search"
              placeholder="Search name, company, email…"
              value={query}
              onChange={(event) => onQuery(event.target.value)}
            />
            <label className="visually-hidden" htmlFor="wp-status">
              Verification status
            </label>
            <select
              id="wp-status"
              className="wp-status"
              value={status}
              onChange={(event) => onStatus(event.target.value)}
            >
              <option value="">All statuses</option>
              {STATUSES.map((value) => (
                <option key={value} value={value}>
                  {statusLabel(value)}
                </option>
              ))}
            </select>
            <label className="visually-hidden" htmlFor="wp-csv">
              Import a CSV
            </label>
            <input
              id="wp-csv"
              ref={fileRef}
              className="visually-hidden"
              type="file"
              accept=".csv,text/csv"
              tabIndex={-1}
              onChange={onFile}
            />
            <button type="button" className="wp-import" onClick={() => fileRef.current?.click()}>
              Import
            </button>
            <a className="btn-outline" href={exportUrl} download="contacts.csv">
              Export CSV
            </a>
          </div>
        ) : null}

        {loading ? <p className="micro wp-state">Setting the type…</p> : null}
        {!online ? (
          <p className="micro wp-state">Offline demo — the sample directory, simulated in the browser.</p>
        ) : null}
        {!loading && rows.length === 0 ? (
          <p className="wp-empty">
            {online
              ? "No listings match. Try another search, or place a call."
              : "The demo directory is empty — place a call from Directory Assistance."}
          </p>
        ) : null}

        <nav className="wp-az" aria-label="White pages index" data-reveal="">
          {index.map(({ letter, hasRows }) => (
            <button
              key={letter}
              type="button"
              className="wp-az-btn"
              aria-disabled={hasRows ? undefined : true}
              tabIndex={hasRows ? undefined : -1}
              onClick={hasRows ? () => scrollToId(`wp-${letter}`, -80) : undefined}
            >
              {letter}
            </button>
          ))}
        </nav>

        <div className="wp-pages" data-reveal="">
          {pages.map((page) => (
            <div className="wp-page" key={page.folio}>
              <div className="wp-pagehead">
                <span className="wp-guide">{page.guide || "—"}</span>
                <span className="wp-folio">{page.folio}</span>
              </div>
              <div className="wp-columns">
                {page.groups.map((group) => (
                  <div className="wp-group" key={group.letter}>
                    <div
                      className="wp-grouphead"
                      id={group.anchor}
                      style={{ scrollMarginTop: 80 }}
                      aria-hidden="true"
                    >
                      <span className="wp-giant">{group.letter}</span>
                      <span className="wp-grouprule" />
                    </div>
                    <ul className="wp-list">
                      {group.rows.map((row) => (
                        <li className="wp-listing" key={row.id} data-new={row.isNew ? "true" : "false"}>
                          <div className="wp-name">
                            <b>{row.last.toUpperCase()}</b> {row.first}{" "}
                            <span className="wp-company">{row.company}</span>
                          </div>
                          <div className="rowline wp-line">
                            <span className="leader-tight" />
                            <span
                              className={row.code === "PG" ? "push pencil" : "push"}
                              style={
                                row.email
                                  ? row.code === "PG"
                                    ? { fontSize: 12.5 }
                                    : { fontSize: 11.5, fontFamily: "var(--serif)", color: "var(--ink)" }
                                  : { fontSize: 12.5, fontFamily: "var(--pencil-face)", color: "var(--pencil)" }
                              }
                            >
                              {row.email || "no address yet"}
                            </span>
                            <span
                              className="wp-code"
                              style={{ color: row.code === "PG" ? "var(--pencil)" : "var(--ink-3)" }}
                              title={`${statusLabel(row.status)}${
                                row.confidence != null ? ` · ${fmtPct(row.confidence)} confidence` : ""
                              }`}
                            >
                              {row.code}
                            </span>
                          </div>
                        </li>
                      ))}
                    </ul>
                  </div>
                ))}
                {page.ad ? (
                  <aside
                    className="adbox wp-ad"
                    style={{ borderWidth: 2, padding: "12px 14px", marginTop: 16, breakInside: "avoid" }}
                  >
                    <div className="display-sm wp-ad-title">Not listed?</div>
                    <p className="wp-ad-body">
                      Dial 4-1-1. Directory Assistance places the call and writes the answer in these pages.
                    </p>
                    <button type="button" className="micro micro-verm wp-ad-btn" onClick={() => onNav("assist")}>
                      pp. 10–11 →
                    </button>
                  </aside>
                ) : null}
              </div>
            </div>
          ))}
        </div>

        <div className="folio">— 6 · 7 —</div>
      </div>
    </section>
  );
}
