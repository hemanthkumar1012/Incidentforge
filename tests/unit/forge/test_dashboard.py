from datetime import UTC, datetime, timedelta

import pytest

from forge.investigation.promql import check_promql
from forge.telemetry.dashboard import (
    PANELS,
    WINDOWS_MINUTES,
    build_annotations,
    fetch_dashboard,
    fetch_panel,
    shape_series,
    step_for,
)
from forge.telemetry.ports import TelemetryUnavailable

NOW = datetime(2026, 11, 9, 12, 0, tzinfo=UTC)


class RecordingBackend:
    def __init__(self, responses=None, fail_on=None):
        self.responses = responses or {}
        self.fail_on = fail_on
        self.calls = []

    def query_range(self, query, start, end, step_s):
        self.calls.append((query, start, end, step_s))
        if self.fail_on and self.fail_on in query:
            raise TelemetryUnavailable("prometheus down")
        return self.responses.get(query, [])


@pytest.mark.parametrize("panel", PANELS, ids=lambda p: p.id)
def test_every_panel_query_passes_the_investigator_promql_guard(panel):
    assert check_promql(panel.query) == panel.query


def test_panel_ids_are_unique():
    assert len({p.id for p in PANELS}) == len(PANELS)


@pytest.mark.parametrize("minutes,expected", [(15, 15), (60, 60), (360, 360)])
def test_step_keeps_roughly_sixty_points_with_a_floor(minutes, expected):
    assert step_for(minutes) == expected
    assert step_for(1) == 15


def test_shape_converts_strings_and_maps_nan_to_none():
    raw = [{"labels": {"service": "checkout"}, "values": [[1, "0.5"], [2, "NaN"], [3, "+Inf"], [4, "x"]]}]
    shaped = shape_series(raw, ("service",))
    assert shaped == [{"label": "checkout", "points": [[1.0, 0.5], [2.0, None], [3.0, None], [4.0, None]]}]


def test_shape_orders_busiest_first_caps_series_and_names_unlabelled_total():
    raw = [{"labels": {"s": str(i)}, "values": [[1, str(i)]]} for i in range(12)]
    shaped = shape_series(raw, ("s",))
    assert len(shaped) == 8
    assert shaped[0]["label"] == "11"
    assert shape_series([{"labels": {}, "values": []}], ("service",))[0]["label"] == "total"


def test_one_failing_panel_does_not_hide_the_others():
    failing = PANELS[0]
    backend = RecordingBackend(fail_on=failing.query)
    result = fetch_dashboard(backend, 60, now=lambda: NOW)
    by_id = {p["id"]: p for p in result["panels"]}
    assert by_id[failing.id]["error"] == "prometheus down"
    assert by_id[failing.id]["series"] == []
    assert all(p["error"] is None for pid, p in by_id.items() if pid != failing.id)
    assert len(backend.calls) == len(PANELS)


def test_window_is_an_allowlist_and_range_ends_at_the_snapshot_time():
    with pytest.raises(ValueError):
        fetch_dashboard(RecordingBackend(), 45)
    backend = RecordingBackend()
    fetch_panel(backend, PANELS[0], 15, NOW)
    _, start, end, step = backend.calls[0]
    assert end == NOW and (end - start).total_seconds() == 15 * 60 and step == 15
    assert set(WINDOWS_MINUTES) == {15, 60, 360}


# --- annotations -----------------------------------------------------------------------------------------------


def test_annotations_include_only_events_inside_the_window_in_time_order():
    start, end = NOW - timedelta(minutes=60), NOW
    versions = [
        {"version": 3, "author": "olivia", "created_at": (NOW - timedelta(minutes=10)).isoformat()},
        {"version": 2, "author": "lab", "created_at": (NOW - timedelta(hours=5)).isoformat()},
    ]
    incidents = [("inc1", "Checkout failing", NOW - timedelta(minutes=5))]
    result = build_annotations(versions, incidents, start, end)
    assert [(a["kind"], a["ref"]) for a in result] == [("config_change", "3"), ("incident", "inc1")]
    assert result[0]["label"] == "Checkout config v3 by olivia"


def test_annotations_accept_zulu_and_naive_timestamps_and_skip_garbage():
    start, end = NOW - timedelta(minutes=60), NOW
    zulu = (NOW - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    naive = (NOW - timedelta(minutes=2)).replace(tzinfo=None).isoformat()
    versions = [
        {"version": 1, "author": "a", "created_at": zulu},
        {"version": 2, "author": "b", "created_at": naive},
        {"version": 3, "author": "c", "created_at": "not a date"},
    ]
    assert [a["ref"] for a in build_annotations(versions, [], start, end)] == ["2", "1"]


def test_long_incident_titles_are_truncated_and_the_list_is_capped():
    start, end = NOW - timedelta(minutes=60), NOW
    long_title = "x" * 500
    one = build_annotations([], [("i", long_title, NOW)], start, end)
    assert len(one[0]["label"]) == 80
    many = [(f"i{n}", "t", NOW - timedelta(seconds=n)) for n in range(100)]
    assert len(build_annotations([], many, start, end)) == 30


def test_dashboard_survives_an_annotation_failure():
    def broken(_start, _end):
        raise TelemetryUnavailable("config database unreachable")

    result = fetch_dashboard(RecordingBackend(), 60, now=lambda: NOW, annotate=broken)
    assert result["annotations"] == [] and result["annotations_error"] == "config database unreachable"
    assert len(result["panels"]) == len(PANELS)


def test_dashboard_without_an_annotator_has_no_annotations():
    result = fetch_dashboard(RecordingBackend(), 60, now=lambda: NOW)
    assert result["annotations"] == [] and result["annotations_error"] is None
