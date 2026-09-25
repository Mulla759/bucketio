/* Shared shapes. The API types mirror bucketio/api.py exactly; the ticket
   types mirror the design component's view model so the same UI can render a
   live lookup and the offline simulation. */

export type VerificationStatus =
  | "unverified"
  | "valid"
  | "invalid"
  | "catch_all"
  | "risky"
  | "unknown"
  | "pattern_guess"
  | "not_found"
  | "no_domain";

export type Route =
  | "cache_hit"
  | "catch_all"
  | "pattern_verify"
  | "treg_find"
  | "generate"
  | "error";

export interface Contact {
  id: number;
  name: string;
  full_name?: string;
  company: string;
  email: string | null;
  high_pattern_email: string | null;
  verification_status: VerificationStatus;
  confidence: number | null;
  seen_count: number;
  last_verified_at: string | null;
  route: Route | null;
}

export interface ContactDetail extends Contact {
  company_domain: string | null;
  email_pattern: string | null;
  email_source: string | null;
  first_seen_at: string | null;
  last_seen_at: string | null;
  do_not_contact: boolean;
}

export interface Company {
  id: number | string;
  name: string;
  domain: string | null;
  pattern: string | null;
  confidence: number | null;
  seen: number;
  is_catch_all: boolean;
  trade?: string;
  isNew?: boolean;
}

/** One white-pages listing, normalised from the API or the offline seed. */
export interface DirectoryRow {
  id: string;
  name: string;
  first: string;
  last: string;
  company: string;
  email: string;
  code: Code;
  confidence: number | null;
  seen: number;
  status: VerificationStatus;
  isNew: boolean;
}

export interface FetchResult {
  contact_id: number;
  name: string;
  company: string;
  domain: string | null;
  email: string | null;
  verification_status: VerificationStatus;
  high_pattern_email: string | null;
  alternates: string[];
  confidence: number | null;
  route: Route;
  treg_calls: { find: number; verify: number };
  seen_count: number;
  est_cost_saved: number;
}

export interface LookupRecord {
  id: number;
  input_name: string;
  input_company: string;
  route: Route;
  identity_method: string | null;
  result_email: string | null;
  result_status: string | null;
  confidence: number | null;
  cost_usd: number;
  est_saved_usd: number;
  laya_mode: string;
  latency_ms: number | null;
  forced: boolean;
  created_at: string;
}

export interface ImportResult {
  rows: number;
  created: number;
  updated: number;
  errors: { row: number; error: string }[];
}

export interface Report {
  fetches: number;
  routes: Record<string, number>;
  treg: { find_calls: number; verify_calls: number; cost_usd: number };
  est_saved_usd: number;
  contacts: number;
  laya: { agreement: number | null; samples: number };
}

export interface Health {
  status: string;
  db: boolean;
  laya: { mode: string; enabled: boolean; reachable: boolean };
  treg: { mode: string };
}

/* ---------- ticket view model ---------- */

export type StepKind = "hit" | "miss" | "guess" | "skip" | "idle";
export type Code = "KN" | "VF" | "FD" | "PG";
export type LayaMode = "Shadow" | "Active";

export interface TicketLine {
  t: string;
  c: string;
}

export interface CandidateView {
  email: string;
  rules: string;
  laya: string;
  mark: string;
  color: string;
  rw: number;
  lw: number;
}

export interface TicketStep {
  no: string;
  q: string;
  a: string;
  kind: StepKind;
  cost: number;
  lines: TicketLine[];
  cands?: CandidateView[] | null;
  candNote?: string;
}

export interface GrayDecision {
  co: string;
  rules: string;
  laya: string;
  agree: boolean;
  outcome: string;
}

export interface TraceMutations {
  coNew?: import("./directory").SeedCompany;
  coUpdate?: {
    id: string;
    seen: number;
    pattern: string;
    conf: number;
    truth?: string;
  };
  person?: import("./directory").SeedPerson;
  gray?: GrayDecision;
}

export interface Ticket {
  no: string;
  party: string;
  first: string;
  last: string;
  coName: string;
  when: string;
  mode: string;
  steps: TicketStep[];
  total: number;
  email: string;
  code: Code;
  guess: boolean;
  stamp: string;
  mut: TraceMutations;
}

export interface SessionEntry {
  code: Code;
  cost: number;
  gray: "a" | "d" | null;
}
