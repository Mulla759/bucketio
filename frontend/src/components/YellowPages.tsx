import { useMemo } from "react";
import { FIND, SEE, SEE_PATTERN, VERIFY, money, sc } from "../lib/directory";
import { fmtInt } from "../lib/format";
import type { Company } from "../lib/types";
import "../styles/yellow.css";

export interface YellowPagesProps {
  companies: Company[];
  groupBy: "pattern" | "trade";
  online: boolean;
  onNav: (id: string) => void;
}

interface CompanyGroup {
  name: string;
  companies: Company[];
}

interface PatternCount {
  pattern: string;
  n: number;
}

function titleCase(value: string): string {
  return value.replace(/\S+/g, (word) => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase());
}

function CompanyCard({ company }: { company: Company }) {
  const gray = company.confidence !== null && company.confidence < 0.8;
  const meta = [`${fmtInt(company.seen)} seen`];
  if (company.confidence !== null) {
    meta.push(gray ? `gray zone · ${sc(company.confidence)}` : `conf. ${sc(company.confidence)}`);
  }
  if (company.is_catch_all) meta.push("catch-all");

  return (
    <div className="yp-card" data-new={company.isNew ? "true" : "false"}>
      <div className="yp-card-name">{company.name}</div>
      <div className="rowline yp-card-addr">
        <span>{company.domain ?? "—"}</span>
        <span className="leader leader-ink" aria-hidden="true" />
        {company.pattern ? (
          <span className="push yp-card-pattern">{company.pattern}@</span>
        ) : (
          <span className="push yp-card-pattern yp-none">no format yet</span>
        )}
      </div>
      <div className={gray ? "yp-card-conf yp-gray" : "yp-card-conf"}>{meta.join(" · ")}</div>
    </div>
  );
}

export function YellowPages({ companies, groupBy, online, onNav }: YellowPagesProps) {
  const groups = useMemo<CompanyGroup[]>(() => {
    const buckets = new Map<string, Company[]>();
    companies.forEach((company) => {
      const name =
        groupBy === "trade" ? (company.trade ?? "Other trades") : (company.pattern ?? "No format yet");
      const bucket = buckets.get(name);
      if (bucket) bucket.push(company);
      else buckets.set(name, [company]);
    });
    return Array.from(buckets, ([name, list]) => ({ name, companies: list })).sort(
      (a, b) => b.companies.length - a.companies.length || a.name.localeCompare(b.name),
    );
  }, [companies, groupBy]);

  const dist = useMemo<PatternCount[]>(() => {
    const counts = new Map<string, number>();
    companies.forEach((company) => {
      if (!company.pattern) return;
      counts.set(company.pattern, (counts.get(company.pattern) ?? 0) + 1);
    });
    return Array.from(counts, ([pattern, n]) => ({ pattern, n })).sort(
      (a, b) => b.n - a.n || a.pattern.localeCompare(b.pattern),
    );
  }, [companies]);

  const grayCount = useMemo(
    () => companies.filter((company) => company.confidence !== null && company.confidence < 0.8).length,
    [companies],
  );

  const top = dist[0] ?? null;
  const guide = groups.length
    ? `${titleCase(groups[0].name)} — ${titleCase(groups[groups.length - 1].name)}`
    : "";

  return (
    <section className="sheet-wide yp" data-sec="" id="yellow" data-folio="pp. 8–9" data-screen-label="Yellow Pages">
      <div className="frame-wide">
        <div className="pagehead yp-pagehead">
          <span>{guide}</span>
          <span className="ph-mid">Yellow pages</span>
          <span>8–9</span>
        </div>

        <h2 className="display-xl yp-title" data-reveal>
          Yellow pages
        </h2>

        <p className="yp-intro" data-reveal>
          Companies in the bucket, by {groupBy === "pattern" ? "format" : "trade"}, with the format of their addresses.
          One find teaches BucketIO the format; everyone after is a {money(VERIFY)} check instead of a {money(FIND)} find.
        </p>

        {companies.length === 0 ? (
          <div className="yp-empty" data-reveal>
            <div className="yp-empty-title">No formats learned yet.</div>
            <p className="yp-empty-note">Place a call and the house style is written down here.</p>
            <button type="button" className="btn btn-ink" onClick={() => onNav("assist")}>
              Place a call →
            </button>
          </div>
        ) : (
          <div className="yp-columns" data-reveal>
            <div className="adbox yp-usual">
              <div className="micro micro-ink">The usual format</div>
              <div className="yp-usual-pattern">{top ? `${top.pattern}@` : "—"}</div>
              <p className="yp-usual-note">
                Used by {top ? fmtInt(top.n) : "0"} of {fmtInt(companies.length)} companies in this directory. Learned
                once; checked ever after.
              </p>
            </div>

            {groups.map((group) => {
              const see = groupBy === "trade" ? SEE[group.name] : SEE_PATTERN[group.name];
              return (
                <div className="yp-group" key={group.name}>
                  <div className="labelbar-sm yp-group-head">{group.name}</div>
                  {see ? <div className="yp-see">See also {see}</div> : null}
                  {group.companies.map((company) => (
                    <CompanyCard key={company.id} company={company} />
                  ))}
                </div>
              );
            })}

            <div className="yp-under">
              <div className="yp-under-title">Under .80?</div>
              <p className="yp-under-note">
                When a company’s format is unsure, Laya weighs the candidates before Treg is asked. {fmtInt(grayCount)}{" "}
                companies are unsure today.
              </p>
            </div>

            <div className="yp-dist">
              <div className="yp-dist-title">Formats, by count</div>
              {dist.map((entry) => (
                <div className="rowline yp-dist-row" key={entry.pattern}>
                  <span>{entry.pattern}@</span>
                  <span className="leader leader-ink" aria-hidden="true" />
                  <span className="yp-dist-count">{fmtInt(entry.n)}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {online ? null : (
          <p className="micro yp-offline">Offline demo — the sample directory, simulated in the browser.</p>
        )}

        <div className="folio">— 8 · 9 —</div>
      </div>
    </section>
  );
}
