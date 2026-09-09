"""Full local history pagination without browser, credentials, or audio."""

import threading
from datetime import UTC, datetime, timedelta

import pytest

from voiceloop.assistant import AssistantService
from voiceloop.assistant_store import AssistantStore


@pytest.fixture
def store(tmp_path):
    result = AssistantStore(tmp_path / "history.sqlite3")
    yield result
    result.close()


def job(index, **values):
    return {
        "id": f"job-{index:04d}",
        "created_at": (datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=index)).isoformat(),
        "state": "completed",
        "target_name": "Sample contact",
        "objective": "Confirm the next step",
        "summary": "",
        "delivery_status": "not_requested",
        **values,
    }


def test_pages_cover_the_entire_history_beyond_the_recent_snapshot(store):
    for index in range(257):
        store.put(job(index))
    first = store.page()
    assert (first["total"], first["page"], first["pages"]) == (257, 1, 13)
    ids = [item["id"] for page in range(1, 14) for item in store.page(page=page)["items"]]
    assert ids == [f"job-{index:04d}" for index in reversed(range(257))]
    assert len(store.page(page=13)["items"]) == 17


def test_same_timestamp_order_is_stable_after_updating_a_job(store):
    timestamp = "2026-01-01T00:00:00+00:00"
    for index in (1, 3, 2):
        store.put(job(index, created_at=timestamp))
    assert [item["id"] for item in store.page()["items"]] == ["job-0003", "job-0002", "job-0001"]
    store.put(job(1, created_at=timestamp, summary="Updated later"))
    assert [item["id"] for item in store.page(page=2, page_size=1)["items"]] == ["job-0002"]


def test_summary_pages_include_requested_outcomes_and_exclude_legacy_jobs(store):
    for index, status in enumerate(("not_requested", "generating", "sent", "ambiguous", "failed")):
        store.put(job(index, delivery_status=status))
    legacy = job(9)
    del legacy["delivery_status"]
    store.put(legacy)
    result = store.page(kind="summary", page_size=2)
    assert (result["total"], result["pages"]) == (4, 2)
    assert [item["delivery_status"] for item in result["items"]] == ["failed", "ambiguous"]


@pytest.mark.parametrize("query", ["%", "_", "\\", "' OR 1=1 --"])
def test_search_treats_sql_and_wildcards_as_literal_text(store, query):
    store.put(job(1, objective=f"Contains {query} literally"))
    store.put(job(2))
    result = store.page(query=query)
    assert result["total"] == 1
    assert result["items"][0]["id"] == "job-0001"


@pytest.mark.parametrize("field", ["target_name", "objective", "summary"])
def test_search_matches_each_field_case_insensitively_with_unicode(store, field):
    store.put(job(1, **{field: "Straße follow-up"}))
    store.put(job(2))
    assert [item["id"] for item in store.page(query="STRASSE")["items"]] == ["job-0001"]


def test_search_filters_before_counting_and_clamping_the_page(store):
    for index in range(205):
        store.put(job(index))
    store.put(job(0, summary="Needle", delivery_status="sent"))
    store.put(job(1, summary="Needle"))
    result = store.page(kind="summary", query="needle", page=999)
    assert result == {"items": [store.get("job-0000")], "total": 1, "page": 1, "pages": 1}
    assert store.page(query="absent", page=5) == {"items": [], "total": 0, "page": 1, "pages": 1}


def test_page_and_page_size_are_clamped_to_bounded_valid_values(store):
    for index in range(105):
        store.put(job(index))
    assert len(store.page(page_size=10000)["items"]) == 100
    assert store.page(page=-20, page_size=0)["page"] == 1
    result = store.page(page=10000, page_size=-1)
    assert (result["page"], result["pages"], len(result["items"])) == (105, 105, 1)


@pytest.mark.parametrize(
    "options",
    [
        {"kind": "unknown"},
        {"query": None},
        {"query": "x" * 1001},
        {"page": True},
        {"page": "2"},
        {"page_size": 2.5},
        {"page_size": False},
    ],
)
def test_invalid_pagination_inputs_fail_cleanly(store, options):
    with pytest.raises(ValueError):
        store.page(**options)


def test_service_lists_old_jobs_from_sqlite_without_loading_the_recent_snapshot(store):
    for index in range(205):
        store.put(job(index, objective="Old unique objective" if index == 0 else "Other objective"))
    service = object.__new__(AssistantService)
    service.lock = threading.RLock()
    service.store = store
    result = service.list_jobs(query="unique", page=2, page_size=10)
    assert result == {"items": [store.get("job-0000")], "total": 1, "page": 1, "pages": 1}
