"""Regression tests for syncing and self-healing deleted Microsoft Planner tasks."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from requests.exceptions import HTTPError


PROJECT_DIR = Path(__file__).resolve().parents[1]


def load_sync_module():
    module_name = "sync_planner_to_webapp_deleted_task_state_test"
    spec = importlib.util.spec_from_file_location(module_name, PROJECT_DIR / "12_sync_planner_to_webapp.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


sync = load_sync_module()


def record(*, task_id: str = "task-id", status: str = "", stale: bool = False) -> dict:
    return {
        "_rowNumber": 186,
        "Số hiệu": "360/2026/NĐ-CP",
        "Planner Task ID": task_id,
        "Planner Plan ID": "plan-id",
        "Planner Bucket ID": "bucket-id",
        "Planner Bucket Name": "bucket-name",
        "Planner Task URL": "https://planner.test/plan-id/task-id",
        "Planner Sync Status": status,
        "Planner Last Sync": "09/10/2026 09:00:00",
        "Current PIC": "Pháp chế | pic@example.test" if stale else "",
        "Current Checkpoint": "Rà soát nội dung" if stale else "",
        "Next Response Due": "10/10/2026" if stale else "",
    }


def graph_not_found() -> HTTPError:
    error = HTTPError("not found")
    error.response = SimpleNamespace(status_code=404)
    return error


def active_records(count: int) -> list[dict]:
    rows = []
    for index in range(count):
        row = record(task_id=f"active-task-{index + 1}")
        row["_rowNumber"] = 100 + index
        rows.append(row)
    return rows


def stale_deleted_records(count: int) -> list[dict]:
    rows = []
    for index in range(count):
        row = record(status=sync.DELETED_SYNC_STATUS, stale=True)
        row["_rowNumber"] = 200 + index
        rows.append(row)
    return rows


class DeletedPlannerTaskSyncTests(unittest.TestCase):
    def test_graph_404_marks_deleted_and_clears_current_workflow_fields(self):
        row = record(stale=True)
        expected_updates = {
            "Planner Sync Status": sync.DELETED_SYNC_STATUS,
            "Planner Last Sync": "09/10/2026 10:00:00",
            "Current PIC": "",
            "Current Checkpoint": "",
            "Next Response Due": "",
        }
        with patch.object(sync, "get_records", return_value=[row]), patch.object(
            sync, "get_token", return_value="delegated-token"
        ), patch.object(sync, "graph_request", side_effect=graph_not_found()) as graph, patch.object(
            sync, "now_text", return_value="09/10/2026 10:00:00"
        ), patch.object(sync, "webapp_post", return_value={"ok": True}) as post:
            result = sync.sync_planner_to_webapp()

        graph.assert_called_once_with("delegated-token", "GET", "/planner/tasks/task-id")
        post.assert_called_once_with(
            sync.VBQPPL_UPDATE_ACTION,
            {"row_number": 186, "updates": expected_updates},
        )
        self.assertEqual(1, result["not_found_records"])
        self.assertEqual(0, result["failed_records"])

    def test_stale_deleted_record_is_self_healed_without_graph_or_last_sync_change(self):
        row = record(status=sync.DELETED_SYNC_STATUS, stale=True)
        expected_updates = {
            "Current PIC": "",
            "Current Checkpoint": "",
            "Next Response Due": "",
        }
        with patch.object(sync, "get_records", return_value=[row]), patch.object(
            sync, "get_token"
        ) as get_token, patch.object(sync, "graph_request") as graph, patch.object(
            sync, "webapp_post", return_value={"ok": True}
        ) as post:
            result = sync.sync_planner_to_webapp()

        get_token.assert_not_called()
        graph.assert_not_called()
        post.assert_called_once_with(
            sync.VBQPPL_UPDATE_ACTION,
            {"row_number": 186, "updates": expected_updates},
        )
        self.assertEqual("task-id", row["Planner Task ID"])
        self.assertEqual("https://planner.test/plan-id/task-id", row["Planner Task URL"])
        self.assertEqual("09/10/2026 09:00:00", row["Planner Last Sync"])
        self.assertEqual(1, result["deleted_cleanup_candidates"])
        self.assertEqual(1, result["deleted_cleanup_to_process"])
        self.assertEqual(1, result["deleted_cleanup_updated"])
        self.assertEqual(0, result["deleted_cleanup_failed"])
        self.assertEqual(0, result["skipped_records"])

    def test_clean_deleted_record_does_not_write_or_query_graph(self):
        row = record(status=sync.DELETED_SYNC_STATUS)
        with patch.object(sync, "get_records", return_value=[row]), patch.object(
            sync, "get_token"
        ) as get_token, patch.object(sync, "graph_request") as graph, patch.object(
            sync, "webapp_post"
        ) as post:
            result = sync.sync_planner_to_webapp()

        get_token.assert_not_called()
        graph.assert_not_called()
        post.assert_not_called()
        self.assertEqual(1, result["skipped_records"])
        self.assertEqual(0, result["deleted_cleanup_candidates"])
        self.assertEqual(0, result["deleted_cleanup_updated"])

    def test_dry_run_reports_deleted_cleanup_candidates_without_writing_or_querying_graph(self):
        stale_deleted = record(status=sync.DELETED_SYNC_STATUS, stale=True)
        active = record(task_id="active-task-id")
        with patch.object(sync, "get_records", return_value=[stale_deleted, active]), patch.object(
            sync, "get_token"
        ) as get_token, patch.object(sync, "graph_request") as graph, patch.object(
            sync, "webapp_post"
        ) as post:
            result = sync.sync_planner_to_webapp(dry_run=True)

        get_token.assert_not_called()
        graph.assert_not_called()
        post.assert_not_called()
        self.assertTrue(result["dry_run"])
        self.assertEqual(1, result["records_to_process"])
        self.assertEqual(1, result["deleted_cleanup_candidates"])
        self.assertEqual(1, result["deleted_cleanup_to_process"])
        self.assertEqual(0, result["deleted_cleanup_updated"])

    def test_limit_one_prioritizes_active_sync_and_defers_deleted_cleanup(self):
        active = active_records(13)
        stale_deleted = stale_deleted_records(2)
        with patch.object(sync, "get_records", return_value=active + stale_deleted), patch.object(
            sync, "get_token", return_value="delegated-token"
        ), patch.object(sync, "graph_request", return_value={}) as graph, patch.object(
            sync, "webapp_post", return_value={"ok": True}
        ) as post:
            result = sync.sync_planner_to_webapp(limit=1)

        self.assertEqual(1, result["records_to_process"])
        self.assertEqual(2, result["deleted_cleanup_candidates"])
        self.assertEqual(0, result["deleted_cleanup_to_process"])
        self.assertEqual(1, post.call_count)
        self.assertEqual(2, graph.call_count)

    def test_limit_fourteen_selects_one_cleanup_after_thirteen_active_records(self):
        with patch.object(
            sync, "get_records", return_value=active_records(13) + stale_deleted_records(2)
        ), patch.object(sync, "get_token") as get_token, patch.object(
            sync, "graph_request"
        ) as graph, patch.object(sync, "webapp_post") as post:
            result = sync.sync_planner_to_webapp(limit=14, dry_run=True)

        get_token.assert_not_called()
        graph.assert_not_called()
        post.assert_not_called()
        self.assertEqual(13, result["records_to_process"])
        self.assertEqual(2, result["deleted_cleanup_candidates"])
        self.assertEqual(1, result["deleted_cleanup_to_process"])

    def test_limit_zero_processes_all_active_and_deleted_cleanup_records(self):
        active = active_records(2)
        stale_deleted = stale_deleted_records(2)
        with patch.object(sync, "get_records", return_value=active + stale_deleted), patch.object(
            sync, "get_token", return_value="delegated-token"
        ), patch.object(sync, "graph_request", return_value={}) as graph, patch.object(
            sync, "webapp_post", return_value={"ok": True}
        ) as post:
            result = sync.sync_planner_to_webapp(limit=0)

        self.assertEqual(2, result["records_to_process"])
        self.assertEqual(2, result["deleted_cleanup_candidates"])
        self.assertEqual(2, result["deleted_cleanup_to_process"])
        self.assertEqual(4, post.call_count)
        self.assertEqual(4, graph.call_count)


if __name__ == "__main__":
    unittest.main()
