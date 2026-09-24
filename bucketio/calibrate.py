"""Laya calibration: temperature scaling, accuracy gate and confidence helpers.

Pass 6 turns the ``laya_decisions`` audit table into a per-question calibration
table (``laya_calibration``) and provides the pure functions the resolver uses
in ``LAYA_MODE=active``:

* ``fit_temperatures`` groups labelled decisions by ``(question, n_options)``
  and picks the temperature that minimises the mean negative log-likelihood of
  the **truth** key under ``softmax(log(p) / T)``. ``n_options`` is the number
  of keys in the stored probability distribution (the natural width of that
  question as Laya answered it).
* ``enabled_questions`` is the data-driven gate: a question type is active only
  when Laya beat the rules on it (``accuracy > rules_acc``) over at least
  ``min_samples`` labelled rows.
* ``calibrated_probs`` / ``calibrated_confidence`` are pure functions shared by
  the fit and by the resolver.

``rules_acc`` is measured over the rows where ``rules_answer`` is present; if a
group has no ``rules_answer`` at all it is NULL and the group can never enable.
Rows without usable labels (no truth, no answer, unparseable probs, or a truth
key absent from the distribution) are skipped entirely and never written.
"""

from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import dataclass

from . import db

MIN_TEMPERATURE = 0.5
MAX_TEMPERATURE = 5.0
TEMPERATURE_STEP = 0.05
DEFAULT_MIN_SAMPLES = 50
_MIN_PROB = 1e-12
_NLL_FLOOR = 1e-12


def default_grid() -> tuple[float, ...]:
    """0.5, 0.55, ..., 5.0 (91 values)."""
    count = int(round((MAX_TEMPERATURE - MIN_TEMPERATURE) / TEMPERATURE_STEP))
    return tuple(round(MIN_TEMPERATURE + TEMPERATURE_STEP * i, 2) for i in range(count + 1))


@dataclass
class CalibrationRow:
    question: str
    n_options: int
    temperature: float
    n_samples: int
    accuracy: float | None
    rules_acc: float | None


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _clean_probs(raw: object) -> dict[str, float]:
    """Finite, non-negative probabilities keyed by string; empty when unusable."""
    if not isinstance(raw, dict):
        return {}
    clean: dict[str, float] = {}
    for key, value in raw.items():
        number = _number(value)
        if number is not None and number >= 0.0:
            clean[str(key)] = number
    if not clean or sum(clean.values()) <= 0.0:
        return {}
    return clean


def _safe_temperature(temperature: float) -> float:
    number = _number(temperature)
    if number is None or number <= 0.0:
        return 1.0
    return number


def calibrated_probs(
    probs: dict[str, float], temperature: float
) -> dict[str, float]:
    """Temperature-scaled probabilities: ``softmax(ln(p) / T)``.

    Pure and total: an empty/invalid distribution yields ``{}`` and a missing or
    non-positive temperature falls back to ``1.0`` (no scaling). Scaling by a
    positive ``T`` preserves the argmax and the result always sums to 1.
    """
    clean = _clean_probs(probs)
    if not clean:
        return {}
    t = _safe_temperature(temperature)
    logits = {key: math.log(max(value, _MIN_PROB)) for key, value in clean.items()}
    peak = max(logits.values())
    scaled = {key: math.exp((value - peak) / t) for key, value in logits.items()}
    total = sum(scaled.values())
    if total <= 0.0:  # pragma: no cover - the max-shift keeps this >= 1
        return {}
    return {key: value / total for key, value in scaled.items()}


def calibrated_confidence(
    probs: dict[str, float], answer: str | None, temperature: float
) -> float | None:
    """The scaled probability of the chosen key, or None when it is absent."""
    if answer is None:
        return None
    scaled = calibrated_probs(probs, temperature)
    return scaled.get(str(answer))


def _nll(probs: dict[str, float], truth: str, temperature: float) -> float:
    scaled = calibrated_probs(probs, temperature)
    return -math.log(max(scaled.get(truth, 0.0), _NLL_FLOOR))


def _best_temperature(
    items: list[tuple[dict[str, float], str]], grid: tuple[float, ...]
) -> float:
    """Grid-search the temperature minimising mean NLL of the truth key."""
    best_temperature = grid[0]
    best_nll = math.inf
    for temperature in grid:
        mean_nll = sum(_nll(probs, truth, temperature) for probs, truth in items) / len(items)
        if mean_nll < best_nll:
            best_nll = mean_nll
            best_temperature = temperature
    return best_temperature


def fit_temperatures(
    conn: sqlite3.Connection, *, grid: tuple[float, ...] | None = None
) -> list[CalibrationRow]:
    """Fit one temperature per ``(question, n_options)`` and upsert the table.

    Only rows with a truth key that is present in the stored distribution are
    used. ``accuracy`` is the share of those rows where ``answer == truth``;
    ``rules_acc`` is the share where ``rules_answer == truth`` over the rows
    that have a ``rules_answer`` (NULL when none do). Returns the fitted rows.
    """
    temperatures = tuple(grid) if grid else default_grid()
    if not temperatures:
        temperatures = default_grid()

    grouped: dict[tuple[str, int], list[tuple[dict[str, float], str, str | None, str | None]]] = {}
    for row in conn.execute(
        """
        SELECT question, answer, rules_answer, probs_json, truth
        FROM laya_decisions
        WHERE truth IS NOT NULL AND answer IS NOT NULL AND probs_json IS NOT NULL
        """
    ):
        try:
            raw_probs = json.loads(row["probs_json"])
        except (TypeError, ValueError):
            continue
        probs = _clean_probs(raw_probs)
        if not probs:
            continue
        truth = str(row["truth"])
        if truth not in probs:
            continue
        answer = str(row["answer"])
        rules_answer = None if row["rules_answer"] is None else str(row["rules_answer"])
        grouped.setdefault((str(row["question"]), len(probs)), []).append(
            (probs, truth, answer, rules_answer)
        )

    fitted: list[CalibrationRow] = []
    with db.tx(conn):
        for (question, n_options), rows in sorted(grouped.items()):
            temperature = _best_temperature(
                [(probs, truth) for probs, truth, _, _ in rows], temperatures
            )
            n_samples = len(rows)
            accuracy = sum(1 for _, truth, answer, _ in rows if answer == truth) / n_samples
            rules_rows = [row for row in rows if row[3] is not None]
            rules_acc = (
                sum(1 for _, truth, _, rules_answer in rules_rows if rules_answer == truth)
                / len(rules_rows)
                if rules_rows
                else None
            )
            conn.execute(
                """
                INSERT INTO laya_calibration
                    (question, n_options, temperature, n_samples, accuracy, rules_acc, fitted_at)
                VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT(question, n_options) DO UPDATE SET
                    temperature = excluded.temperature,
                    n_samples = excluded.n_samples,
                    accuracy = excluded.accuracy,
                    rules_acc = excluded.rules_acc,
                    fitted_at = excluded.fitted_at
                """,
                (question, n_options, temperature, n_samples, accuracy, rules_acc),
            )
            fitted.append(
                CalibrationRow(
                    question=question,
                    n_options=n_options,
                    temperature=temperature,
                    n_samples=n_samples,
                    accuracy=accuracy,
                    rules_acc=rules_acc,
                )
            )
    return fitted


def enabled_questions(
    conn: sqlite3.Connection, *, min_samples: int = DEFAULT_MIN_SAMPLES
) -> set[str]:
    """Question types Laya earned the right to influence: better than rules."""
    rows = conn.execute(
        """
        SELECT question FROM laya_calibration
        WHERE n_samples >= ?
          AND accuracy IS NOT NULL
          AND rules_acc IS NOT NULL
          AND accuracy > rules_acc
        """,
        (int(min_samples),),
    ).fetchall()
    return {str(row["question"]) for row in rows}


def format_report(rows: list[CalibrationRow]) -> str:
    """A small fixed-width table for ``bucketio report``-style output."""
    if not rows:
        return "Laya calibration: no labelled decisions yet"
    lines = [
        "Laya calibration (question, options, temperature, samples, accuracy, rules, lift):",
        f"{'question':<10} {'opts':>4} {'temp':>6} {'n':>6} {'acc':>7} {'rules':>7} {'lift':>7}",
    ]
    for row in rows:
        accuracy = "-" if row.accuracy is None else f"{row.accuracy:.3f}"
        rules_acc = "-" if row.rules_acc is None else f"{row.rules_acc:.3f}"
        lift = (
            "-"
            if row.accuracy is None or row.rules_acc is None
            else f"{row.accuracy - row.rules_acc:+.3f}"
        )
        lines.append(
            f"{row.question:<10} {row.n_options:>4} {row.temperature:>6.2f} "
            f"{row.n_samples:>6} {accuracy:>7} {rules_acc:>7} {lift:>7}"
        )
    return "\n".join(lines)
