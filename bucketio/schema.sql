PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;
PRAGMA busy_timeout = 5000;

CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL);

-- Companies and their email domains
CREATE TABLE IF NOT EXISTS companies (
  id            INTEGER PRIMARY KEY,
  name          TEXT NOT NULL,               -- as first seen
  company_key   TEXT NOT NULL UNIQUE,        -- normalized
  domain        TEXT,                        -- e.g. acme.com (nullable until known)
  is_catch_all  INTEGER NOT NULL DEFAULT 0,
  mx_ok         INTEGER,                     -- 1/0/NULL unknown
  created_at    TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_companies_domain ON companies(domain);

-- Aliases so "ACME Corp" and "Acme Inc" resolve to one company
CREATE TABLE IF NOT EXISTS company_aliases (
  alias_key   TEXT PRIMARY KEY,
  company_id  INTEGER NOT NULL REFERENCES companies(id)
);

-- The "sheet": one row per real person
CREATE TABLE IF NOT EXISTS contacts (
  id                  INTEGER PRIMARY KEY,
  full_name           TEXT NOT NULL,          -- display, as first seen
  first_name          TEXT,
  middle_name         TEXT,
  last_name           TEXT,
  name_key            TEXT NOT NULL,          -- normalized "first last"
  company_id          INTEGER NOT NULL REFERENCES companies(id),
  email               TEXT,                   -- best known email
  email_source        TEXT CHECK (email_source IN
                        ('cache','treg_find','treg_verify','pattern','import','manual')),
  email_pattern       TEXT,                   -- e.g. first.last or 'custom'
  verification_status TEXT NOT NULL DEFAULT 'unverified' CHECK (verification_status IN
                        ('unverified','valid','invalid','catch_all','risky','unknown',
                         'pattern_guess','not_found','no_domain')),
  high_pattern_email  TEXT,                   -- top generated candidate
  confidence          REAL,                   -- 0..1
  seen_count          INTEGER NOT NULL DEFAULT 0,
  first_seen_at       TEXT NOT NULL DEFAULT (datetime('now')),
  last_seen_at        TEXT NOT NULL DEFAULT (datetime('now')),
  last_verified_at    TEXT,
  do_not_contact      INTEGER NOT NULL DEFAULT 0,
  merged_into         INTEGER REFERENCES contacts(id),   -- soft-merge
  UNIQUE (name_key, company_id)
);
CREATE INDEX IF NOT EXISTS idx_contacts_email  ON contacts(email);
CREATE INDEX IF NOT EXISTS idx_contacts_status ON contacts(verification_status);

-- Learned email formats per domain (Beta counts)
CREATE TABLE IF NOT EXISTS domain_patterns (
  domain         TEXT NOT NULL,
  pattern        TEXT NOT NULL,
  hits           INTEGER NOT NULL DEFAULT 0,   -- valid outcomes
  misses         INTEGER NOT NULL DEFAULT 0,   -- invalid outcomes
  verified_hits  INTEGER NOT NULL DEFAULT 0,   -- valid via Treg (find or verify)
  last_hit_at    TEXT,
  PRIMARY KEY (domain, pattern)
);

-- Global pattern priors (seeded, then re-estimated from all domains)
CREATE TABLE IF NOT EXISTS pattern_priors (
  pattern  TEXT PRIMARY KEY,
  prior    REAL NOT NULL
);

-- One row per fetch request (audit + metrics + Laya training labels)
CREATE TABLE IF NOT EXISTS lookups (
  id              INTEGER PRIMARY KEY,
  contact_id      INTEGER REFERENCES contacts(id),
  input_name      TEXT NOT NULL,
  input_company   TEXT NOT NULL,
  route           TEXT NOT NULL CHECK (route IN
                    ('cache_hit','catch_all','pattern_verify','treg_find','generate','error')),
  identity_method TEXT CHECK (identity_method IN ('exact','fuzzy_rule','laya','new')),
  result_email    TEXT,
  result_status   TEXT,
  confidence      REAL,
  cost_usd        REAL NOT NULL DEFAULT 0,
  est_saved_usd   REAL NOT NULL DEFAULT 0,     -- vs. baseline of one find
  laya_mode       TEXT NOT NULL,
  latency_ms      INTEGER,
  forced          INTEGER NOT NULL DEFAULT 0,
  created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_lookups_created ON lookups(created_at);

-- Every Treg call, raw output kept verbatim
CREATE TABLE IF NOT EXISTS treg_calls (
  id          INTEGER PRIMARY KEY,
  lookup_id   INTEGER NOT NULL REFERENCES lookups(id),
  kind        TEXT NOT NULL CHECK (kind IN ('find','verify')),
  request     TEXT NOT NULL,                 -- name|company or email
  status      TEXT NOT NULL,
  email       TEXT,
  cost_usd    REAL NOT NULL DEFAULT 0,
  raw_json    TEXT NOT NULL,
  created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Candidate emails generated per lookup
CREATE TABLE IF NOT EXISTS candidates (
  lookup_id    INTEGER NOT NULL REFERENCES lookups(id),
  email        TEXT NOT NULL,
  pattern      TEXT NOT NULL,
  rules_score  REAL NOT NULL,
  laya_prob    REAL,
  final_score  REAL NOT NULL,
  rank         INTEGER NOT NULL,
  outcome      TEXT,                          -- filled when verified: valid/invalid/catch_all
  PRIMARY KEY (lookup_id, email)
);

-- Every Laya question asked (shadow or active) + eventual ground truth
CREATE TABLE IF NOT EXISTS laya_decisions (
  id            INTEGER PRIMARY KEY,
  lookup_id     INTEGER NOT NULL REFERENCES lookups(id),
  question      TEXT NOT NULL CHECK (question IN ('identity','route','rank','plausible')),
  routed_model  TEXT,                         -- english / multilingual (from response.routing)
  answer        TEXT,                         -- chosen key
  confidence    REAL,
  probs_json    TEXT,                         -- full distribution
  rules_answer  TEXT,                         -- what the rule engine chose
  applied       INTEGER NOT NULL DEFAULT 0,   -- 1 if it changed the outcome (active mode)
  truth         TEXT,                         -- filled later from verification
  latency_ms    INTEGER,
  error         TEXT,
  created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Laya calibration output (Pass 6)
CREATE TABLE IF NOT EXISTS laya_calibration (
  question     TEXT NOT NULL,
  n_options    INTEGER NOT NULL,
  temperature  REAL NOT NULL,
  n_samples    INTEGER NOT NULL,
  accuracy     REAL,
  rules_acc    REAL,
  fitted_at    TEXT NOT NULL DEFAULT (datetime('now')),
  PRIMARY KEY (question, n_options)
);
