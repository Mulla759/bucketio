import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Contact } from "./components/Contact";
import { Cover } from "./components/Cover";
import { DirectoryAssistance } from "./components/DirectoryAssistance";
import { Docs } from "./components/Docs";
import { Features } from "./components/Features";
import { Header } from "./components/Header";
import { Setup } from "./components/Setup";
import { WhitePages } from "./components/WhitePages";
import { YellowPages } from "./components/YellowPages";
import { FILE_MODE, FILE_MODE_MESSAGE, api, probeHealth } from "./lib/api";
import * as directory from "./lib/directory";
import { codeForContact, splitName } from "./lib/format";
import {
  refreshTriggers,
  scrollToId,
  scrollToTop,
  useHeaderReveal,
  useLenis,
  usePageTurns,
  useReveals,
  useSectionTracking,
  washNew,
} from "./lib/motion";
import { ticketFromResult } from "./lib/ticket";
import type {
  Company,
  Contact as ContactRow,
  DirectoryRow,
  GrayDecision,
  Health,
  LayaMode,
  Report,
  SessionEntry,
  Ticket,
} from "./lib/types";

const REPO_URL = "https://github.com/Mulla759/bucketio";
const AGENT_PROMPT = "set up bucketio — https://bucketio.vercel.app/llms.txt";
const INSTALL_COMMAND = `git clone ${REPO_URL} && uv sync --extra dev && uv run bucketio init`;
const CONNECT_COMMAND = "treg login";
const ASK_COMMAND = 'uv run bucketio fetch "Iris Calloway" "Meridian Freight"';
const GRAVATAR_URL = "https://gravatar.com/tremendousdelectablye2bab3e728";
const EMAIL = "abdullahiabdi5600@gmail.com";
const GITHUB_URL = "https://github.com/Mulla759";
const LINKEDIN_URL = "https://linkedin.com/in/abdull-abdi5";
const X_URL = "https://x.com/AAbdallahDev";

function healthMode(health: Health | null): string | null {
  return health ? health.laya.mode : null;
}

export default function App() {
  const headerRef = useRef<HTMLElement | null>(null);
  const afterHeroRef = useRef<HTMLDivElement | null>(null);

  const [contacts, setContacts] = useState<ContactRow[]>([]);
  const [contactsTotal, setContactsTotal] = useState(0);
  const [companies, setCompanies] = useState<Company[]>([]);
  const [companiesTotal, setCompaniesTotal] = useState(0);
  const [report, setReport] = useState<Report | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [online, setOnline] = useState(false);
  const [loading, setLoading] = useState(true);
  const [mode, setMode] = useState<LayaMode>("Shadow");
  const [ticket, setTicket] = useState<Ticket | null>(null);
  const [log, setLog] = useState<SessionEntry[]>([]);
  const [grayLog, setGrayLog] = useState<GrayDecision[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("");
  const [toast, setToast] = useState("");

  const [simCompanies, setSimCompanies] = useState<directory.SeedCompany[]>(directory.SEED_COMPANIES);
  const [simPeople, setSimPeople] = useState<directory.SeedPerson[]>(() => directory.seedPeople());

  useLenis(0.08);
  const reveal = useReveals();
  usePageTurns();
  const { section, folio } = useSectionTracking();
  useHeaderReveal(headerRef, afterHeroRef);

  const onNav = useCallback((id: string) => {
    if (id === "top") {
      scrollToTop();
      return;
    }
    scrollToId(id);
  }, []);

  /* First contact with the server: health, then the whole directory. */
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const result = await probeHealth();
      if (cancelled) return;
      if (!result) {
        setOnline(false);
        setLoading(false);
        if (FILE_MODE) setToast(FILE_MODE_MESSAGE);
        return;
      }
      setHealth(result);
      setMode(result.laya.mode.toLowerCase() === "active" ? "Active" : "Shadow");
      try {
        const [contactsPage, companiesPage, reportBody] = await Promise.all([
          api.contacts({ limit: 500 }),
          api.companies(500),
          api.report(),
        ]);
        if (cancelled) return;
        setContacts(contactsPage.items);
        setContactsTotal(contactsPage.total);
        setCompanies(companiesPage.items);
        setCompaniesTotal(companiesPage.total);
        setReport(reportBody);
        setOnline(true);
      } catch {
        setOnline(false);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  /* Search and status filter, against the live bucket only. */
  useEffect(() => {
    if (!online) return;
    let cancelled = false;
    const handle = window.setTimeout(
      async () => {
        try {
          const page = await api.contacts({ q: query, status, limit: 500 });
          if (cancelled) return;
          setContacts(page.items);
          setContactsTotal(page.total);
        } catch {
          /* keep the page as it was */
        }
      },
      query ? 200 : 0,
    );
    return () => {
      cancelled = true;
      window.clearTimeout(handle);
    };
  }, [query, status, online]);

  useEffect(() => {
    if (document.fonts?.ready) void document.fonts.ready.then(() => refreshTriggers());
  }, []);

  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(""), 6000);
    return () => window.clearTimeout(timer);
  }, [toast]);

  const placeCall = useCallback(
    async (name: string, company: string) => {
      const parts = name.trim().split(/\s+/).filter(Boolean);
      if (parts.length < 2 || !company.trim()) {
        setError("A first name, a last name and a company, please.");
        return;
      }
      setBusy(true);
      setError("");
      try {
        if (online) {
          const result = await api.fetchPerson(name.trim(), company.trim());
          const built = ticketFromResult(result, mode, log.length);
          setTicket(built);
          setLog((entries) => entries.concat([{ code: built.code, cost: built.total, gray: null }]));
          const [contactsPage, companiesPage, reportBody] = await Promise.all([
            api.contacts({ q: query, status, limit: 500 }),
            api.companies(500),
            api.report(),
          ]);
          setContacts(contactsPage.items);
          setContactsTotal(contactsPage.total);
          setCompanies(companiesPage.items);
          setCompaniesTotal(companiesPage.total);
          setReport(reportBody);
        } else {
          const built = directory.trace({
            first: parts[0],
            last: parts.slice(1).join(" "),
            company: company.trim(),
            mode,
            companies: simCompanies,
            people: simPeople,
            logLength: log.length,
          });
          setTicket(built);
          setSimCompanies((current) => {
            let next = current.map((entry) => (entry.isNew ? { ...entry, isNew: false } : entry));
            if (built.mut.coNew && !next.some((entry) => entry.id === built.mut.coNew?.id)) {
              next = next.concat([{ ...built.mut.coNew, isNew: true }]);
            }
            if (built.mut.coUpdate) {
              const update = built.mut.coUpdate;
              next = next.map((entry) => (entry.id === update.id ? { ...entry, ...update } : entry));
            }
            return next;
          });
          setSimPeople((current) => {
            const cleared = current.map((entry) => (entry.isNew ? { ...entry, isNew: false } : entry));
            return built.mut.person
              ? cleared.concat([{ ...built.mut.person, isNew: true }]).sort(directory.cmp)
              : cleared;
          });
          setLog((entries) =>
            entries.concat([
              { code: built.code, cost: built.total, gray: built.mut.gray ? (built.mut.gray.agree ? "a" : "d") : null },
            ]),
          );
          if (built.mut.gray) {
            setGrayLog((entries) => [built.mut.gray as GrayDecision, ...entries].slice(0, 4));
          }
        }
        window.setTimeout(() => {
          washNew(document);
          refreshTriggers();
        }, 80);
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setBusy(false);
      }
    },
    [online, mode, log.length, query, status, simCompanies, simPeople],
  );

  const onImport = useCallback(async (file: File) => {
    try {
      const result = await api.importCsv(file);
      const created = Number(result.created) || 0;
      const updated = Number(result.updated) || 0;
      const skipped = Array.isArray(result.errors) ? result.errors.length : 0;
      setToast(
        `Imported ${file.name}: ${created} new, ${updated} updated${skipped ? `, ${skipped} skipped` : ""}.`,
      );
      const [contactsPage, companiesPage, reportBody] = await Promise.all([
        api.contacts({ limit: 500 }),
        api.companies(500),
        api.report(),
      ]);
      setContacts(contactsPage.items);
      setContactsTotal(contactsPage.total);
      setCompanies(companiesPage.items);
      setCompaniesTotal(companiesPage.total);
      setReport(reportBody);
    } catch (err) {
      setToast(`Import failed: ${err instanceof Error ? err.message : String(err)}`);
    }
  }, []);

  const rows: DirectoryRow[] = useMemo(() => {
    if (online) {
      return contacts.map((contact) => {
        const name = contact.name || contact.full_name || "";
        const { first, last } = splitName(name);
        return {
          id: `c${contact.id}`,
          name,
          first,
          last,
          company: contact.company,
          email: contact.email ?? contact.high_pattern_email ?? "",
          code: codeForContact(contact),
          confidence: contact.confidence,
          seen: contact.seen_count,
          status: contact.verification_status,
          isNew: false,
        };
      });
    }
    return simPeople.map((person) => ({
      id: person.id,
      name: `${person.first} ${person.last}`,
      first: person.first,
      last: person.last,
      company: person.coName,
      email: person.email,
      code: person.code,
      confidence: null,
      seen: 0,
      status: person.code === "PG" ? "pattern_guess" : "valid",
      isNew: Boolean(person.isNew),
    }));
  }, [online, contacts, simPeople]);

  const yellowCompanies: Company[] = useMemo(() => {
    if (online) return companies;
    return simCompanies.map((company) => ({
      id: company.id,
      name: company.name,
      domain: company.domain,
      pattern: company.pattern,
      confidence: company.conf,
      seen: company.seen,
      is_catch_all: false,
      trade: company.trade,
      isNew: company.isNew,
    }));
  }, [online, companies, simCompanies]);

  const peopleCount = online ? report?.contacts ?? contactsTotal : simPeople.length;
  const coCount = online ? companiesTotal : simCompanies.length;

  useEffect(() => {
    reveal();
    refreshTriggers();
  }, [reveal, rows.length, yellowCompanies.length]);

  return (
    <>
      <Header
        headerRef={headerRef}
        folio={folio || "No. 01"}
        active={section}
        repoUrl={REPO_URL}
        onNav={onNav}
      />

      <Cover
        agentPrompt={AGENT_PROMPT}
        peopleCount={peopleCount}
        coCount={coCount}
        year={new Date().getFullYear()}
        onNav={onNav}
      />

      <div data-after-hero ref={afterHeroRef}>
        <Setup agentPrompt={AGENT_PROMPT} askCommand={ASK_COMMAND} online={online} onNav={onNav} />

        <Features
          mode={mode}
          onMode={setMode}
          serverMode={healthMode(health)}
          grayLog={grayLog}
          online={online}
          onNav={onNav}
        />

        <WhitePages
          rows={rows}
          total={online ? contactsTotal : rows.length}
          online={online}
          loading={loading}
          query={query}
          onQuery={setQuery}
          status={status}
          onStatus={setStatus}
          onImport={onImport}
          exportUrl={api.exportUrl}
          onNav={onNav}
        />

        <YellowPages companies={yellowCompanies} groupBy={online ? "pattern" : "trade"} online={online} onNav={onNav} />

        <DirectoryAssistance
          ticket={ticket}
          busy={busy}
          error={error}
          online={online}
          mode={mode}
          serverMode={healthMode(health)}
          log={log}
          grayLog={grayLog}
          onPlace={placeCall}
        />

        <Docs
          installCommand={INSTALL_COMMAND}
          connectCommand={CONNECT_COMMAND}
          askCommand={ASK_COMMAND}
          agentPrompt={AGENT_PROMPT}
          repoUrl={REPO_URL}
          online={online}
          onNav={onNav}
        />

        <Contact
          gravatarUrl={GRAVATAR_URL}
          email={EMAIL}
          github={GITHUB_URL}
          linkedin={LINKEDIN_URL}
          x={X_URL}
          online={online}
        />
      </div>

      {toast ? (
        <div className="toast" role="status">
          <span>{toast}</span>
          <button type="button" onClick={() => setToast("")}>
            Dismiss
          </button>
        </div>
      ) : null}
    </>
  );
}
