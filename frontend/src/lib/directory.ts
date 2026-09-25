/* The offline directory: the design component's simulation, ported to a pure
   module. It powers the demo when `bucketio serve` is not reachable, and it is
   the fallback whenever the live API has nothing to show. No React, no DOM. */

import type {
  CandidateView,
  Code,
  GrayDecision,
  LayaMode,
  Ticket,
  TicketStep,
  TraceMutations,
} from "./types";

/** Prices: the backend's own defaults (config.py). */
export const FIND = 0.004834;
export const VERIFY = 0.0015;

export interface SeedCompany {
  id: string;
  name: string;
  domain: string;
  pattern: string;
  truth?: string;
  seen: number;
  conf: number;
  trade: string;
  isNew?: boolean;
}

export interface SeedPerson {
  id: string;
  last: string;
  first: string;
  co: string;
  coName: string;
  email: string;
  code: Code;
  isNew?: boolean;
}

export const SEED_COMPANIES: SeedCompany[] = [
  { id: "meridian", name: "Meridian Freight", domain: "meridianfreight.com", pattern: "first.last", seen: 14, conf: 0.97, trade: "Freight & Shipping" },
  { id: "harbor", name: "Harbor Line Ferry", domain: "harborline.co", pattern: "flast", seen: 6, conf: 0.91, trade: "Freight & Shipping" },
  { id: "tidewater", name: "Tidewater & Co.", domain: "tidewater.co", pattern: "first", seen: 4, conf: 0.88, trade: "Freight & Shipping" },
  { id: "eastlake", name: "Eastlake Press", domain: "eastlakepress.com", pattern: "first.last", seen: 9, conf: 0.95, trade: "Printers & Publishers" },
  { id: "yardarm", name: "Yardarm Books", domain: "yardarm.com", pattern: "first_last", seen: 3, conf: 0.82, trade: "Printers & Publishers" },
  { id: "riverside", name: "Riverside Print", domain: "riversideprint.com", pattern: "last", truth: "first.last", seen: 2, conf: 0.71, trade: "Printers & Publishers" },
  { id: "saltmarsh", name: "Saltmarsh Radio", domain: "saltmarsh.fm", pattern: "first", seen: 7, conf: 0.93, trade: "Radio & Signal" },
  { id: "zephyr", name: "Zephyr Signal", domain: "zephyrsignal.io", pattern: "firstl", seen: 5, conf: 0.86, trade: "Radio & Signal" },
  { id: "bellweather", name: "Bellweather Labs", domain: "bellweather.io", pattern: "flast", seen: 11, conf: 0.96, trade: "Software" },
  { id: "northwind", name: "Northwind", domain: "northwind.dev", pattern: "first.last", seen: 18, conf: 0.98, trade: "Software" },
  { id: "lantern", name: "Lantern Studio", domain: "lantern.studio", pattern: "first", seen: 5, conf: 0.9, trade: "Software" },
  { id: "quarry", name: "Quarry Street", domain: "quarrystreet.com", pattern: "first.l", seen: 3, conf: 0.77, trade: "Software" },
  { id: "vesper", name: "Vesper Hotel", domain: "vesperhotel.com", pattern: "first.last", seen: 4, conf: 0.89, trade: "Hotels & Coffee" },
  { id: "granary", name: "Granary Coffee", domain: "granary.coffee", pattern: "first", seen: 2, conf: 0.74, trade: "Hotels & Coffee" },
  { id: "ironbridge", name: "Ironbridge Health", domain: "ironbridgehealth.org", pattern: "f.last", seen: 8, conf: 0.94, trade: "Health & Law" },
  { id: "pinecrest", name: "Pinecrest Legal", domain: "pinecrestlegal.com", pattern: "first.last", seen: 3, conf: 0.84, trade: "Health & Law" },
];

const SEED =
  "Abernathy,Clara,eastlake;Adeyemi,Tunde,northwind;Alvarez,Marisol,vesper;Baptiste,Jules,saltmarsh;Bergström,Elin,bellweather;Byrne,Declan,meridian;Castellanos,Rita,ironbridge;Chen,Wei,northwind;Cole,Harriet,harbor;Dasgupta,Anjali,bellweather;Delacroix,Noé,lantern;Duarte,Paulo,tidewater;Eastman,Ruth,eastlake;Ekwueme,Chidi,zephyr;Fairweather,Tom,meridian;Farouk,Laila,ironbridge;Fontaine,Odile,vesper;Garza,Beto,granary;Gilchrist,Moira,yardarm;Greaves,Oliver,northwind;Halloran,Maeve,saltmarsh;Hartmann,Lena,bellweather;Hossain,Farhan,quarry;Ibarra,Sofía,lantern;Iwu,Nneka,pinecrest;Jablonski,Piotr,meridian;Jensen,Karin,zephyr;Kaur,Simran,northwind;Kowalczyk,Ada,eastlake;Kuroda,Ren,harbor;Lachance,Guy,riverside;Lindqvist,Maja,bellweather;Lowe,Eliza,pinecrest;Mbeki,Thandi,ironbridge;McFee,William,harbor;Moreau,Céline,vesper;Nakamura,Ellis,quarry;Ndiaye,Awa,saltmarsh;Novak,Tereza,northwind;Okafor,Adaeze,meridian;Olsen,Birgit,tidewater;O’Rourke,Finn,granary;Park,Jiwoo,bellweather;Pereira,Tomás,zephyr;Pryce,Gwen,eastlake;Rahman,Nadia,ironbridge;Reyes,Mateo,lantern;Rosen,Abe,riverside;Sato,Haruki,northwind;Silva,Bruna,vesper;Stroud,Vivian,yardarm;Tanaka,Emi,zephyr;Thibodeaux,Remy,harbor;Trent,Oona,pinecrest;Varga,Zsófia,bellweather;Voss,Anton,meridian;Whitlock,June,eastlake;Wu,Ming,northwind;Yamada,Kei,saltmarsh;Yilmaz,Deniz,quarry;Zhou,Lan,northwind;Zielinski,Marek,ironbridge";

export const TREG_WORLD: Record<string, Omit<SeedCompany, "id" | "seen" | "conf">> = {
  orchardbank: { name: "Orchard Bank", domain: "orchardbank.com", pattern: "first.last", trade: "Banks & Credit" },
  kestrelair: { name: "Kestrel Air", domain: "kestrelair.com", pattern: "flast", trade: "Air Charter" },
  unionice: { name: "Union Ice", domain: "unionice.co", pattern: "first", trade: "Cold Storage" },
  caldervoss: { name: "Calder & Voss", domain: "caldervoss.com", pattern: "first_last", trade: "Architects" },
};

export const TRADES = [
  "Freight & Shipping",
  "Printers & Publishers",
  "Radio & Signal",
  "Software",
  "Hotels & Coffee",
  "Health & Law",
  "Banks & Credit",
  "Air Charter",
  "Cold Storage",
  "Architects",
];

export const SEE: Record<string, string> = {
  "Freight & Shipping": "Radio & Signal; Cold Storage",
  "Printers & Publishers": "Software",
  "Radio & Signal": "Freight & Shipping",
  Software: "Printers & Publishers",
  "Hotels & Coffee": "Freight & Shipping (ferries)",
  "Health & Law": "Banks & Credit",
  "Banks & Credit": "Health & Law",
  "Air Charter": "Freight & Shipping",
  "Cold Storage": "Hotels & Coffee",
  Architects: "Printers & Publishers",
};

/** Related formats, for the yellow-pages "see also" line when grouping live data. */
export const SEE_PATTERN: Record<string, string> = {
  "first.last": "first_last; flast",
  flast: "f.last; first.last",
  first: "firstl; first.last",
  first_last: "first.last; first.l",
  "first.l": "first_last; firstl",
  "f.last": "flast; first.last",
  firstl: "first; first.last",
  last: "lastf; first.last",
  lastf: "last; flast",
  firstlast: "first; flast",
};

export const PRESETS = [
  { n: "01", name: "Adaeze Okafor", co: "Meridian Freight", note: "Already listed" },
  { n: "02", name: "Iris Calloway", co: "Meridian Freight", note: "House style known" },
  { n: "03", name: "Hugo Marchetti", co: "Orchard Bank", note: "A stranger" },
  { n: "04", name: "Mina Sadeghi", co: "Orchard Bank", note: "The next one there" },
  { n: "05", name: "Tobias Wren", co: "Riverside Print", note: "Gray zone" },
  { n: "06", name: "Odette Albescu", co: "Foxglove Cartography", note: "Nobody finds her" },
];

const PATTERN_FORMS: Record<string, (f: string, l: string) => string> = {
  "first.last": (f, l) => `${f}.${l}`,
  flast: (f, l) => `${f[0] ?? ""}${l}`,
  first: (f) => f,
  first_last: (f, l) => `${f}_${l}`,
  "first.l": (f, l) => `${f}.${l[0] ?? ""}`,
  "f.last": (f, l) => `${f[0] ?? ""}.${l}`,
  firstl: (f, l) => `${f}${l[0] ?? ""}`,
  last: (_f, l) => l,
  lastf: (f, l) => `${l}${f[0] ?? ""}`,
  firstlast: (f, l) => `${f}${l}`,
};

export function slug(value: string | null | undefined): string {
  return String(value ?? "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]/g, "");
}

export function local(pattern: string, first: string, last: string): string {
  const form = PATTERN_FORMS[pattern];
  return form ? form(first, last) : `${first}.${last}`;
}

/** Reverse-match an address against the known forms: "jane.doe" -> "first.last". */
export function inferPattern(email: string | null | undefined, first: string, last: string): string | null {
  if (!email || !email.includes("@")) return null;
  const localPart = email.split("@")[0];
  const f = slug(first);
  const l = slug(last);
  for (const pattern of Object.keys(PATTERN_FORMS)) {
    if (PATTERN_FORMS[pattern](f, l) === localPart) return pattern;
  }
  return null;
}

export function money(value: number): string {
  if (!value) return "$0.00";
  let text = value.toFixed(5).replace(/0+$/, "");
  if ((text.split(".")[1] ?? "").length < 2) text = value.toFixed(2);
  return `$${text}`;
}

/** 0.97 -> ".97" (confidence as the design writes it). */
export function sc(value: number): string {
  return value.toFixed(2).replace(/^0/, "");
}

export function cmp(a: { last: string; first: string }, b: { last: string; first: string }): number {
  return slug(a.last).localeCompare(slug(b.last)) || slug(a.first).localeCompare(slug(b.first));
}

export function seedPeople(): SeedPerson[] {
  const byId: Record<string, SeedCompany> = {};
  SEED_COMPANIES.forEach((company) => {
    byId[company.id] = company;
  });
  const seen: Record<string, boolean> = {};
  return SEED.split(";")
    .map((row, index) => {
      const [last, first, co] = row.split(",");
      return { id: `p${index}`, last, first, co };
    })
    .sort(cmp)
    .map((person) => {
      const company = byId[person.co];
      const code: Code = !seen[person.co] ? "FD" : company.conf < 0.8 ? "PG" : "VF";
      seen[person.co] = true;
      return {
        ...person,
        coName: company.name,
        email: `${local(company.pattern, slug(person.first), slug(person.last))}@${company.domain}`,
        code,
      };
    });
}

export interface DistributionEntry {
  pattern: string;
  n: number;
  share: number;
}

export function distribution(companies: SeedCompany[]): DistributionEntry[] {
  const counts: Record<string, number> = {};
  companies.forEach((company) => {
    counts[company.pattern] = (counts[company.pattern] ?? 0) + 1;
  });
  const total = companies.length || 1;
  return Object.keys(counts)
    .map((pattern) => ({ pattern, n: counts[pattern], share: counts[pattern] / total }))
    .sort((a, b) => b.n - a.n || a.pattern.localeCompare(b.pattern));
}

interface Candidate {
  pattern: string;
  rules: number;
  laya: number;
  email: string;
}

export function candidates(
  company: { name?: string; conf?: number; truth?: string },
  first: string,
  last: string,
  domain: string,
  known: string | null,
  companies: SeedCompany[],
): Candidate[] {
  const dist = distribution(companies);
  let list: { pattern: string; rules: number }[];
  if (known) {
    const others = dist.filter((entry) => entry.pattern !== known);
    const total = others.reduce((sum, entry) => sum + entry.share, 0) || 1;
    list = [{ pattern: known, rules: company.conf ?? 0 }].concat(
      others.map((entry) => ({
        pattern: entry.pattern,
        rules: ((1 - (company.conf ?? 0)) * entry.share) / total,
      })),
    );
  } else {
    list = dist.map((entry) => ({ pattern: entry.pattern, rules: entry.share }));
  }
  list.sort((a, b) => b.rules - a.rules);
  list = list.slice(0, 3);
  if (company.truth && !list.some((entry) => entry.pattern === company.truth)) {
    list[2] = { pattern: company.truth, rules: 0.05 };
  }
  const ruleSum = list.reduce((sum, entry) => sum + entry.rules, 0);
  list.forEach((entry) => {
    entry.rules = entry.rules / ruleSum;
  });
  const small = /studio|coffee|books|cartograph|press|bakery|atelier|workshop|&/i.test(company.name ?? "");
  const weights = list.map((entry) =>
    known
      ? entry.rules *
        (company.truth && company.truth !== known
          ? entry.pattern === company.truth
            ? 9
            : 1
          : entry.pattern === known
            ? 1.6
            : 1)
      : entry.rules * (small ? (entry.pattern === "first" ? 2.6 : 1) : entry.pattern === "first.last" ? 1.3 : 1),
  );
  const weightSum = weights.reduce((sum, value) => sum + value, 0);
  return list.map((entry, index) => ({
    pattern: entry.pattern,
    rules: entry.rules,
    laya: weights[index] / weightSum,
    email: `${local(entry.pattern, first, last)}@${domain}`,
  }));
}

export function candView(
  list: Candidate[],
  used: string,
  layaPick: string,
  mode: LayaMode,
): CandidateView[] {
  const top = list.slice().sort((a, b) => b.rules - a.rules)[0]?.pattern;
  return list.map((entry) => ({
    email: entry.email,
    rules: sc(entry.rules),
    laya: sc(entry.laya),
    mark: entry.pattern === used ? "← used" : entry.pattern === layaPick && mode !== "Active" ? "· Laya’s pick" : "",
    color: entry.pattern === used ? "#1B1813" : "#6B655A",
    rw: entry.pattern === top ? 700 : 400,
    lw: entry.pattern === layaPick ? 700 : 400,
  }));
}

export interface TraceInput {
  first: string;
  last: string;
  company: string;
  mode: LayaMode;
  companies: SeedCompany[];
  people: SeedPerson[];
  logLength: number;
}

export function trace(input: TraceInput): Ticket {
  const { first, last, company: companyText, mode, companies, people, logLength } = input;
  const key = slug(companyText);
  const fs = slug(first);
  const ls = slug(last);
  const company = companies.find(
    (entry) =>
      slug(entry.name) === key ||
      slug(entry.domain.split(".")[0]) === key ||
      (key.length >= 4 && slug(entry.name).startsWith(key)),
  );
  const skip = (no: string, q: string): TicketStep => ({
    no,
    q,
    a: "Not needed.",
    kind: "skip",
    cost: 0,
    lines: [],
  });
  const now = new Date();
  const pad = (value: number) => String(value).padStart(2, "0");
  const mut: TraceMutations = {};
  const ticket: Ticket = {
    no: String(logLength + 1).padStart(4, "0"),
    party: `${last.toUpperCase()}, ${first}`,
    first,
    last,
    coName: company ? company.name : companyText,
    when: `${pad(now.getDate())}.${pad(now.getMonth() + 1)}.${String(now.getFullYear()).slice(2)} · ${pad(now.getHours())}:${pad(now.getMinutes())}`,
    mode,
    steps: [],
    total: 0,
    email: "",
    code: "KN",
    guess: false,
    stamp: "",
    mut,
  };

  const hit = people.find(
    (person) =>
      slug(person.first) === fs &&
      slug(person.last) === ls &&
      (company ? person.co === company.id : slug(person.coName) === key),
  );

  if (hit) {
    ticket.steps.push({
      no: "01",
      q: "In the bucket?",
      a: `Yes — listed under ${hit.last.toUpperCase()}${hit.code === "PG" ? ", in pencil." : "."}`,
      kind: "hit",
      cost: 0,
      lines: [{ t: "SQLite · 1 row", c: "$0.00" }],
    });
    ticket.steps.push(skip("02", "House style known?"), skip("03", "Ask Treg to find"), skip("04", "Pencil it in"));
    return Object.assign(ticket, {
      email: hit.email,
      code: "KN",
      guess: hit.code === "PG",
      coName: hit.coName,
      stamp: "Answered from the bucket",
    });
  }

  ticket.steps.push({
    no: "01",
    q: "In the bucket?",
    a: `No listing for ${ticket.party}.`,
    kind: "miss",
    cost: 0,
    lines: [],
  });
  const makePerson = (email: string, code: Code, co: string, coName: string): SeedPerson => ({
    id: `n${Date.now()}`,
    last,
    first,
    co,
    coName,
    email,
    code,
    isNew: true,
  });

  if (company) {
    const gray = company.conf < 0.8;
    const truth = company.truth ?? company.pattern;
    let order = [company.pattern];
    let scored: Candidate[] | null = null;
    let rulesPick = company.pattern;
    let layaPick = company.pattern;
    if (gray) {
      scored = candidates(company, fs, ls, company.domain, company.pattern, companies);
      rulesPick = scored.slice().sort((a, b) => b.rules - a.rules)[0].pattern;
      layaPick = scored.slice().sort((a, b) => b.laya - a.laya)[0].pattern;
      order = scored
        .slice()
        .sort((a, b) => (mode === "Active" ? b.laya - a.laya : b.rules - a.rules))
        .map((entry) => entry.pattern);
    }
    const lines: { t: string; c: string }[] = [];
    let used: string | null = null;
    let cost = 0;
    for (const pattern of order) {
      const email = `${local(pattern, fs, ls)}@${company.domain}`;
      const ok = pattern === truth;
      cost += VERIFY;
      lines.push({
        t: `Treg · verify ${email} → ${ok ? "deliverable" : "undeliverable"}`,
        c: money(VERIFY),
      });
      if (ok) {
        used = pattern;
        break;
      }
    }
    if (!used) used = order[order.length - 1];
    const email = `${local(used, fs, ls)}@${company.domain}`;
    ticket.steps.push({
      no: "02",
      q: "House style known?",
      a: gray
        ? `Unsure — ${company.domain} is ${sc(company.conf)} on ${company.pattern}@. Candidates scored.`
        : `Yes — ${company.domain} writes ${company.pattern}@.`,
      kind: "hit",
      cost,
      lines,
      cands: scored ? candView(scored, used, layaPick, mode) : null,
      candNote:
        mode === "Active"
          ? "Laya is active: its pick settles the tie."
          : "Laya is in shadow: its pick is logged; the rules decide.",
    });
    ticket.steps.push(skip("03", "Ask Treg to find"), skip("04", "Pencil it in"));
    ticket.total = cost;
    mut.person = makePerson(email, "VF", company.id, company.name);
    const switched = used !== company.pattern;
    mut.coUpdate = {
      id: company.id,
      seen: company.seen + 1,
      pattern: used,
      conf: switched ? 0.76 : Math.min(0.98, Number((company.conf + 0.01).toFixed(2))),
      truth: switched ? undefined : company.truth,
    };
    if (gray) {
      const decision: GrayDecision = {
        co: company.name,
        rules: `${rulesPick}@`,
        laya: `${layaPick}@`,
        agree: rulesPick === layaPick,
        outcome:
          rulesPick === layaPick
            ? "Agreed. One verify."
            : mode === "Active"
              ? `Laya settled it. ${lines.length} verify.`
              : `Rules kept. Laya ${layaPick === used ? `was right; ${lines.length - 1} verify wasted.` : "was wrong."}`,
      };
      mut.gray = decision;
    }
    return Object.assign(ticket, { email, code: "VF" as Code, stamp: "Built & verified" });
  }

  ticket.steps.push({
    no: "02",
    q: "House style known?",
    a: `Never heard of ${companyText}.`,
    kind: "miss",
    cost: 0,
    lines: [],
  });
  const world = TREG_WORLD[key];
  if (world) {
    const email = `${local(world.pattern, fs, ls)}@${world.domain}`;
    ticket.coName = world.name;
    ticket.steps.push({
      no: "03",
      q: "Ask Treg to find",
      a: `Found ${email}.`,
      kind: "hit",
      cost: FIND,
      lines: [
        { t: "Treg · find → 1 result", c: money(FIND) },
        { t: `Learned the house style: ${world.pattern}@`, c: "$0.00" },
      ],
    });
    ticket.steps.push(skip("04", "Pencil it in"));
    ticket.total = FIND;
    mut.coNew = { id: key, ...world, seen: 1, conf: 0.86, isNew: true };
    mut.person = makePerson(email, "FD", key, world.name);
    return Object.assign(ticket, { email, code: "FD" as Code, stamp: "Found · style learned" });
  }

  ticket.steps.push({
    no: "03",
    q: "Ask Treg to find",
    a: "Nobody found.",
    kind: "miss",
    cost: 0,
    lines: [{ t: "Treg · find → 0 results · misses settle at $0.00", c: "$0.00" }],
  });
  const domain = `${key}.com`;
  const scored = candidates({ name: companyText }, fs, ls, domain, null, companies);
  const rulesPick = scored.slice().sort((a, b) => b.rules - a.rules)[0].pattern;
  const layaPick = scored.slice().sort((a, b) => b.laya - a.laya)[0].pattern;
  const used = mode === "Active" ? layaPick : rulesPick;
  const email = `${local(used, fs, ls)}@${domain}`;
  ticket.steps.push({
    no: "04",
    q: "Pencil it in",
    a: `Most probable: ${email}`,
    kind: "guess",
    cost: 0,
    lines: [{ t: "Written from learned house styles · unverified", c: "$0.00" }],
    cands: candView(scored, used, layaPick, mode),
    candNote:
      mode === "Active"
        ? "Laya is active: its pick is pencilled in."
        : "Laya is in shadow: its pick is logged; the rules decide.",
  });
  mut.person = makePerson(email, "PG", `x-${key}`, companyText);
  mut.gray = {
    co: companyText,
    rules: `${rulesPick}@`,
    laya: `${layaPick}@`,
    agree: rulesPick === layaPick,
    outcome:
      rulesPick === layaPick
        ? "Agreed. Pencilled in."
        : mode === "Active"
          ? "Laya’s pick pencilled in."
          : "Rules’ pick pencilled in; Laya’s logged.",
  };
  return Object.assign(ticket, { email, code: "PG" as Code, guess: true, stamp: "Pencilled in" });
}
