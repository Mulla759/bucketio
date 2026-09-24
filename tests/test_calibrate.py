from __future__ import annotations

import json

import pytest

from bucketio import calibrate
from bucketio.calibrate import (
    CalibrationRow,
    calibrated_confidence,
    calibrated_probs,
    enabled_questions,
    fit_temperatures,
    format_report,
)


def _lookup(conn) -> int:
    cursor = conn.execute(
        "INSERT INTO lookups (input_name, input_company, route, laya_mode) "
        "VALUES ('N', 'C', 'generate', 'shadow')"
    )
    return int(cursor.lastrowid)


def _decision(
    conn,
    lookup_id: int,
    *,
    question: str,
    answer: str | None,
    rules_answer: str | None,
    probs: dict | None,
    truth: str | None,
) -> None:
    conn.execute(
        """
        INSERT INTO laya_decisions
            (lookup_id, question, answer, confidence, probs_json, rules_answer, truth)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            lookup_id,
            question,
            answer,
            None,
            None if probs is None else json.dumps(probs),
            rules_answer,
            truth,
        ),
    )


def _calibration(
    conn,
    *,
    question: str,
    n_options: int,
    n_samples: int,
    accuracy: float | None,
    rules_acc: float | None,
    temperature: float = 1.0,
) -> None:
    conn.execute(
        """
        INSERT INTO laya_calibration
            (question, n_options, temperature, n_samples, accuracy, rules_acc)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (question, n_options, temperature, n_samples, accuracy, rules_acc),
    )
    conn.commit()


def test_default_grid_spans_half_to_five():
    grid = calibrate.default_grid()
    assert len(grid) == 91
    assert grid[0] == pytest.approx(0.5)
    assert grid[-1] == pytest.approx(5.0)
    assert list(grid) == sorted(grid)


def test_fit_overconfident_probs_raise_temperature(conn):
    lookup_id = _lookup(conn)
    for index in range(100):
        truth = "A" if index < 50 else "B"
        _decision(
            conn,
            lookup_id,
            question="identity",
            answer="A",
            rules_answer="B",
            probs={"A": 0.9, "B": 0.1},
            truth=truth,
        )
    conn.commit()

    rows = fit_temperatures(conn)

    assert len(rows) == 1
    row = rows[0]
    assert (row.question, row.n_options, row.n_samples) == ("identity", 2, 100)
    assert row.temperature > 1.0
    assert row.accuracy == pytest.approx(0.5)
    assert row.rules_acc == pytest.approx(0.5)

    stored = conn.execute("SELECT * FROM laya_calibration").fetchall()
    assert len(stored) == 1
    assert stored[0]["question"] == "identity"
    assert stored[0]["n_options"] == 2
    assert stored[0]["temperature"] == pytest.approx(row.temperature)
    assert stored[0]["fitted_at"] is not None


def test_fit_underconfident_probs_lower_temperature(conn):
    lookup_id = _lookup(conn)
    for _ in range(60):
        _decision(
            conn,
            lookup_id,
            question="plausible",
            answer="A",
            rules_answer="A",
            probs={"A": 0.6, "B": 0.4},
            truth="A",
        )
    conn.commit()

    row = fit_temperatures(conn)[0]

    assert row.temperature < 1.0
    assert row.accuracy == pytest.approx(1.0)
    assert row.rules_acc == pytest.approx(1.0)


def test_fit_accuracy_and_rules_accuracy(conn):
    lookup_id = _lookup(conn)
    cases = [
        ("A", "A", "A"),
        ("B", "A", "A"),
        ("A", "A", "B"),
        ("B", "B", "B"),
    ]
    for answer, rules_answer, truth in cases:
        _decision(
            conn,
            lookup_id,
            question="route",
            answer=answer,
            rules_answer=rules_answer,
            probs={"A": 0.7, "B": 0.3},
            truth=truth,
        )
    conn.commit()

    row = fit_temperatures(conn)[0]

    assert row.n_samples == 4
    assert row.accuracy == pytest.approx(0.5)
    assert row.rules_acc == pytest.approx(0.75)


def test_fit_upserts_one_row_per_group(conn):
    lookup_id = _lookup(conn)
    _decision(
        conn,
        lookup_id,
        question="identity",
        answer="A",
        rules_answer="A",
        probs={"A": 0.9, "B": 0.1},
        truth="A",
    )
    conn.commit()
    first = fit_temperatures(conn)
    assert len(first) == 1
    assert first[0].n_samples == 1

    _decision(
        conn,
        lookup_id,
        question="identity",
        answer="B",
        rules_answer="B",
        probs={"A": 0.9, "B": 0.1},
        truth="B",
    )
    conn.commit()
    second = fit_temperatures(conn)

    assert len(second) == 1
    assert second[0].n_samples == 2
    stored = conn.execute("SELECT * FROM laya_calibration").fetchall()
    assert len(stored) == 1
    assert stored[0]["n_samples"] == 2
    assert stored[0]["fitted_at"] is not None


def test_fit_groups_by_option_count(conn):
    lookup_id = _lookup(conn)
    for probs, truth in (
        ({"c1": 0.6, "c2": 0.4}, "c1"),
        ({"c1": 0.5, "c2": 0.3, "c3": 0.2}, "c2"),
    ):
        _decision(
            conn,
            lookup_id,
            question="rank",
            answer=next(iter(probs)),
            rules_answer="c1",
            probs=probs,
            truth=truth,
        )
    conn.commit()

    rows = fit_temperatures(conn)

    assert [(row.question, row.n_options) for row in rows] == [("rank", 2), ("rank", 3)]


def test_unlabeled_rows_are_skipped(conn):
    lookup_id = _lookup(conn)
    _decision(
        conn, lookup_id, question="identity", answer="A", rules_answer="B",
        probs={"A": 0.9, "B": 0.1}, truth=None,
    )
    _decision(
        conn, lookup_id, question="identity", answer=None, rules_answer="B",
        probs={"A": 0.9, "B": 0.1}, truth="A",
    )
    _decision(
        conn, lookup_id, question="identity", answer="A", rules_answer="B",
        probs={"A": 0.9, "B": 0.1}, truth="c9",
    )
    _decision(
        conn, lookup_id, question="identity", answer="A", rules_answer="B",
        probs=None, truth="A",
    )
    conn.execute(
        """
        INSERT INTO laya_decisions
            (lookup_id, question, answer, probs_json, rules_answer, truth)
        VALUES (?, 'identity', 'A', '{not json', 'B', 'A')
        """,
        (lookup_id,),
    )
    conn.commit()

    assert fit_temperatures(conn) == []
    assert conn.execute("SELECT COUNT(*) AS n FROM laya_calibration").fetchone()["n"] == 0


def test_unlabeled_rows_do_not_count_towards_samples(conn):
    lookup_id = _lookup(conn)
    for _ in range(3):
        _decision(
            conn, lookup_id, question="rank", answer="c1", rules_answer="c1",
            probs={"c1": 0.6, "c2": 0.4}, truth="c1",
        )
    _decision(
        conn, lookup_id, question="rank", answer="c1", rules_answer="c1",
        probs={"c1": 0.6, "c2": 0.4}, truth=None,
    )
    conn.commit()

    row = fit_temperatures(conn)[0]
    assert row.n_samples == 3


def test_enabled_questions_gate(conn):
    _calibration(conn, question="rank", n_options=6, n_samples=60, accuracy=0.9, rules_acc=0.5)
    _calibration(conn, question="route", n_options=2, n_samples=60, accuracy=0.4, rules_acc=0.5)
    _calibration(conn, question="identity", n_options=2, n_samples=10, accuracy=0.9, rules_acc=0.1)
    _calibration(conn, question="plausible", n_options=2, n_samples=50, accuracy=0.5, rules_acc=0.5)

    assert enabled_questions(conn) == {"rank"}
    assert enabled_questions(conn, min_samples=10) == {"rank", "identity"}
    assert enabled_questions(conn, min_samples=1000) == set()


def test_enabled_questions_ignores_null_accuracy(conn):
    _calibration(conn, question="rank", n_options=6, n_samples=60, accuracy=None, rules_acc=None)
    assert enabled_questions(conn) == set()


def test_calibrated_probs_sums_to_one_and_preserves_argmax():
    probs = {"A": 0.7, "B": 0.2, "C": 0.1}
    for temperature in (0.5, 1.0, 2.0, 5.0):
        scaled = calibrated_probs(probs, temperature)
        assert sum(scaled.values()) == pytest.approx(1.0)
        assert set(scaled) == set(probs)
        assert max(scaled, key=scaled.get) == "A"

    hot = calibrated_probs(probs, 0.5)
    cool = calibrated_probs(probs, 5.0)
    assert hot["A"] > probs["A"] > cool["A"]

    assert calibrated_probs({}, 1.0) == {}
    assert calibrated_probs(probs, 0.0) == pytest.approx(probs)
    assert calibrated_probs({"A": 1.0, "B": 0.0}, 1.0) == pytest.approx({"A": 1.0, "B": 0.0})


def test_calibrated_confidence_uses_scaled_probability():
    probs = {"A": 0.7, "B": 0.3}

    assert calibrated_confidence(probs, "A", 1.0) == pytest.approx(0.7)
    assert calibrated_confidence(probs, "B", 1.0) == pytest.approx(0.3)
    assert calibrated_confidence(probs, "A", 2.0) < 0.7
    assert calibrated_confidence(probs, "A", 0.5) > 0.7

    assert calibrated_confidence(probs, "Z", 1.0) is None
    assert calibrated_confidence(probs, None, 1.0) is None
    assert calibrated_confidence({}, "A", 1.0) is None


def test_format_report_renders_rows():
    text = format_report([CalibrationRow("rank", 6, 1.5, 60, 0.9, 0.5)])
    assert "rank" in text
    assert "1.50" in text
    assert "+0.400" in text
    assert "no labelled decisions" in format_report([])
