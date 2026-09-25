/* Display formatting shared by every section. */

import type { Code, Contact, VerificationStatus } from "./types";

export function fmtInt(value: unknown): string {
  const number = Number(value);
  return Number.isFinite(number) ? String(Math.trunc(number)) : "—";
}

export function fmtUsd(value: unknown): string {
  const number = Number(value);
  return Number.isFinite(number) ? `$${number.toFixed(2)}` : "—";
}

export function fmtPct(value: unknown): string {
  const number = Number(value);
  return Number.isFinite(number) ? `${(number * 100).toFixed(0)}%` : "—";
}

export function fmtWhen(value: string | null | undefined): string {
  if (!value) return "—";
  let raw = String(value);
  if (/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/.test(raw)) raw = `${raw.replace(" ", "T")}Z`;
  const date = new Date(raw);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

export function statusLabel(status: VerificationStatus | string | null | undefined): string {
  const value = String(status ?? "").trim();
  return value ? value.replace(/_/g, " ") : "unknown";
}

/** The directory's own abbreviations: KN known, VF verified, FD found, PG pencilled. */
export function codeForContact(contact: Pick<Contact, "verification_status">): Code {
  switch (contact.verification_status) {
    case "valid":
    case "catch_all":
    case "risky":
      return "VF";
    case "pattern_guess":
    case "unverified":
    case "unknown":
    case "no_domain":
    case "not_found":
    case "invalid":
      return "PG";
    default:
      return "KN";
  }
}

export function isPencilled(contact: Pick<Contact, "verification_status">): boolean {
  return codeForContact(contact) === "PG";
}

/** First letter of the surname, A–Z, for the white-pages groups. */
export function surnameLetter(fullName: string): string {
  const parts = String(fullName ?? "").trim().split(/\s+/).filter(Boolean);
  const surname = parts.length > 1 ? parts[parts.length - 1] : (parts[0] ?? "");
  const letter = surname
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .charAt(0)
    .toUpperCase();
  return /[A-Z]/.test(letter) ? letter : "#";
}

export function splitName(fullName: string): { first: string; last: string } {
  const parts = String(fullName ?? "").trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return { first: "", last: "" };
  if (parts.length === 1) return { first: parts[0], last: parts[0] };
  return { first: parts[0], last: parts.slice(1).join(" ") };
}
