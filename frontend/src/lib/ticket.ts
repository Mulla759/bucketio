/* Map a live /api/fetch result onto the ticket view model, so the same toll
   ticket renders a real lookup and the offline simulation. */

import { FIND, VERIFY, inferPattern, money } from "./directory";
import type { Code, FetchResult, LayaMode, Route, Ticket, TicketStep } from "./types";

const FIND_HIT_ROUTES: Route[] = ["treg_find"];

export function codeFromRoute(route: Route): Code {
  switch (route) {
    case "cache_hit":
      return "KN";
    case "pattern_verify":
    case "catch_all":
      return "VF";
    case "treg_find":
      return "FD";
    case "generate":
      return "PG";
    default:
      return "KN";
  }
}

function stampForRoute(route: Route): string {
  switch (route) {
    case "cache_hit":
      return "Answered from the bucket";
    case "catch_all":
      return "Built · catch-all domain";
    case "pattern_verify":
      return "Built & verified";
    case "treg_find":
      return "Found · style learned";
    case "generate":
      return "Pencilled in";
    default:
      return "Nothing on the line";
  }
}

function nowStamp(): string {
  const now = new Date();
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${pad(now.getDate())}.${pad(now.getMonth() + 1)}.${String(now.getFullYear()).slice(2)} · ${pad(now.getHours())}:${pad(now.getMinutes())}`;
}

export function ticketFromResult(result: FetchResult, mode: LayaMode, logLength: number): Ticket {
  const parts = result.name.trim().split(/\s+/).filter(Boolean);
  const first = parts[0] ?? result.name;
  const last = parts.length > 1 ? parts.slice(1).join(" ") : first;
  const domain = result.domain ?? "—";
  const email = result.email ?? "—";
  const pattern = inferPattern(result.email, first, last);

  const skip = (no: string, q: string): TicketStep => ({
    no,
    q,
    a: "Not needed.",
    kind: "skip",
    cost: 0,
    lines: [],
  });
  const miss = (no: string, q: string, a: string, lines: TicketStep["lines"] = []): TicketStep => ({
    no,
    q,
    a,
    kind: "miss",
    cost: 0,
    lines,
  });

  const findCharge = FIND_HIT_ROUTES.includes(result.route) ? result.treg_calls.find * FIND : 0;
  const verifyCharge = result.treg_calls.verify * VERIFY;
  const total = findCharge + verifyCharge;
  const steps: TicketStep[] = [];
  let candidateStep = "02";

  switch (result.route) {
    case "cache_hit":
      steps.push({
        no: "01",
        q: "In the bucket?",
        a: `Yes — listed under ${last.toUpperCase()}.`,
        kind: "hit",
        cost: 0,
        lines: [{ t: "SQLite · 1 row", c: "$0.00" }],
      });
      steps.push(skip("02", "House style known?"), skip("03", "Ask Treg to find"), skip("04", "Pencil it in"));
      break;

    case "catch_all":
      steps.push(miss("01", "In the bucket?", `No listing for ${last.toUpperCase()}, ${first}.`));
      steps.push({
        no: "02",
        q: "House style known?",
        a: `Yes — ${domain} is catch-all and the format is on file.`,
        kind: "hit",
        cost: 0,
        lines: [
          { t: "Treg · no call needed · catch-all domain", c: "$0.00" },
          ...(pattern ? [{ t: `Built ${email} from ${pattern}@`, c: "$0.00" }] : []),
        ],
      });
      steps.push(skip("03", "Ask Treg to find"), skip("04", "Pencil it in"));
      break;

    case "pattern_verify": {
      steps.push(miss("01", "In the bucket?", `No listing for ${last.toUpperCase()}, ${first}.`));
      const lines: TicketStep["lines"] = [];
      for (let index = 0; index < result.treg_calls.verify; index += 1) {
        lines.push({ t: `Treg · verify ${email} → deliverable`, c: money(VERIFY) });
      }
      steps.push({
        no: "02",
        q: "House style known?",
        a: `Yes — ${domain} writes ${pattern ? `${pattern}@` : "a known format"}.`,
        kind: "hit",
        cost: verifyCharge,
        lines,
      });
      steps.push(skip("03", "Ask Treg to find"), skip("04", "Pencil it in"));
      break;
    }

    case "treg_find":
      steps.push(miss("01", "In the bucket?", `No listing for ${last.toUpperCase()}, ${first}.`));
      steps.push(miss("02", "House style known?", `Never heard of ${result.company}.`));
      steps.push({
        no: "03",
        q: "Ask Treg to find",
        a: `Found ${email}.`,
        kind: "hit",
        cost: findCharge,
        lines: [
          { t: "Treg · find → 1 result", c: money(FIND) },
          ...(pattern ? [{ t: `Learned the house style: ${pattern}@`, c: "$0.00" }] : []),
        ],
      });
      steps.push(skip("04", "Pencil it in"));
      candidateStep = "03";
      break;

    case "generate":
    default:
      steps.push(miss("01", "In the bucket?", `No listing for ${last.toUpperCase()}, ${first}.`));
      steps.push(miss("02", "House style known?", `Never heard of ${result.company}.`));
      steps.push(
        miss("03", "Ask Treg to find", "Nobody found.", [
          { t: "Treg · find → 0 results · misses settle at $0.00", c: "$0.00" },
        ]),
      );
      steps.push({
        no: "04",
        q: "Pencil it in",
        a: `Most probable: ${email}`,
        kind: "guess",
        cost: 0,
        lines: [{ t: "Written from learned house styles · unverified", c: "$0.00" }],
      });
      candidateStep = "04";
      break;
  }

  const alternates = result.alternates.filter(Boolean);
  if (alternates.length) {
    const step = steps.find((entry) => entry.no === candidateStep);
    if (step) {
      step.cands = alternates.map((candidate) => ({
        email: candidate,
        rules: "—",
        laya: "—",
        mark: candidate === result.email ? "← used" : "",
        color: candidate === result.email ? "#1B1813" : "#6B655A",
        rw: 400,
        lw: 400,
      }));
      step.candNote = "Other candidates on file for this company.";
    }
  }

  return {
    no: String(logLength + 1).padStart(4, "0"),
    party: `${last.toUpperCase()}, ${first}`,
    first,
    last,
    coName: result.company,
    when: nowStamp(),
    mode,
    steps,
    total,
    email,
    code: result.verification_status === "pattern_guess" ? "PG" : codeFromRoute(result.route),
    guess: result.route === "generate" || result.verification_status === "pattern_guess",
    stamp: stampForRoute(result.route),
    mut: {},
  };
}
