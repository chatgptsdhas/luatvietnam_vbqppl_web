"""Unit tests for the local delegated Planner flow (no network calls)."""

from __future__ import annotations

import importlib.util
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_DIR = Path(__file__).resolve().parents[1]


def load_numbered_module(filename: str, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, PROJECT_DIR / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


sync = load_numbered_module("11_sync_webapp_to_planner.py", "sync_webapp_to_planner_test")
import ms_planner  # noqa: E402


ENV = {
    "LEGAL_DEFAULT_DUE_DAYS": "5",
    "PLANNER_PLAN_ID": "plan-id",
    "PLANNER_BUCKET_ID_PHAP_CHE": "bucket-id",
    "PLANNER_INITIAL_ASSIGNEE_USER_IDS": "user-id",
    "PLANNER_INITIAL_ASSIGNEE_EMAILS": "legal@example.test",
    "PLANNER_INITIAL_ASSIGNEE_DEPARTMENTS": "HO",
    "TENANT_ID": "tenant-id",
    "PLANNER_TASK_URL_TEMPLATE": "https://planner.test/{plan_id}/{task_id}?tenant={tenant_id}",
    "PLANNER_CREATE_FROM_DATE": "13/05/2026",
}


def record(task_id: str = "", sync_status: str = "") -> dict:
    return {
        "_rowNumber": 187,
        "Số hiệu": "296/2026/NĐ-CP",
        "Tên văn bản": "Nghị định kiểm thử",
        "Loại văn bản": "Nghị định",
        "Ngày hiệu lực": "23/07/2026",
        "Link Văn bản": "https://example.test/296",
        "Trạng thái xử lý": "Đã chuyển",
        "Ngày chuyển trạng thái": "23/07/2026",
        "Planner Task ID": task_id,
        "Planner Sync Status": sync_status,
    }


class LocalPlannerIdempotencyTests(unittest.TestCase):
    @patch.dict(os.environ, ENV, clear=False)
    def test_creates_task_and_writes_back_to_exact_target_row(self):
        row = record()
        task = {
            "ok": True,
            "task_id": "new-task-id",
            "title": "[296/2026/NĐ-CP] Nghị định kiểm thử",
            "planner_web_url": "https://planner.test/plan-id/new-task-id",
            "next_response_due": "01/08/2026",
            "reused_existing": False,
        }
        with patch.object(sync, "get_records", return_value=[row]), patch.object(
            sync, "create_planner_task_from_record", return_value=task
        ), patch.object(sync, "update_record_with_planner_info", return_value={"ok": True}) as update:
            result = sync.sync_single_webapp_record_to_planner(row_number=187)

        self.assertTrue(result["ok"])
        self.assertEqual(1, result["created_tasks"])
        update.assert_called_once_with(row, task)
        self.assertEqual(187, result["target_row_number"])

    @patch.dict(os.environ, ENV, clear=False)
    def test_same_record_retried_after_writeback_creates_at_most_one_task(self):
        row = record()
        task = {
            "ok": True,
            "task_id": "new-task-id",
            "title": "[296/2026/NĐ-CP] Nghị định kiểm thử",
            "planner_web_url": "",
            "next_response_due": "01/08/2026",
            "reused_existing": False,
        }
        with patch.object(sync, "get_records", return_value=[row]), patch.object(
            sync, "create_planner_task_from_record", return_value=task
        ) as create, patch.object(sync, "update_record_with_planner_info", return_value={"ok": True}):
            first = sync.sync_single_webapp_record_to_planner(row_number=187)
            row["Planner Task ID"] = "new-task-id"
            row["Planner Sync Status"] = sync.CREATED_SYNC_STATUS
            second = sync.sync_single_webapp_record_to_planner(row_number=187)

        self.assertEqual(1, first["created_tasks"])
        self.assertEqual(0, second["created_tasks"])
        self.assertEqual("has_planner_task_id", second["skip_reason"])
        self.assertEqual(1, create.call_count)

    @patch.dict(os.environ, ENV, clear=False)
    def test_recovered_existing_graph_task_is_written_to_exact_row_without_new_task(self):
        row = record()
        task = {
            "ok": True,
            "task_id": "recovered-task-id",
            "title": "[296/2026/NĐ-CP] Nghị định kiểm thử",
            "planner_web_url": "",
            "next_response_due": "01/08/2026",
            "reused_existing": True,
        }
        with patch.object(sync, "get_records", return_value=[row]), patch.object(
            sync, "create_planner_task_from_record", return_value=task
        ), patch.object(sync, "update_record_with_planner_info", return_value={"ok": True}) as update:
            result = sync.sync_single_webapp_record_to_planner(row_number=187)

        self.assertTrue(result["ok"])
        self.assertEqual(0, result["created_tasks"])
        self.assertTrue(result["reused_existing"])
        self.assertEqual(187, update.call_args.args[0]["_rowNumber"])

    @patch.dict(os.environ, ENV, clear=False)
    def test_update_request_targets_the_exact_vbqppl_row(self):
        row = record()
        task = {"task_id": "task-id", "planner_web_url": "", "next_response_due": "01/08/2026"}
        with patch.object(sync, "webapp_post", return_value={"ok": True}) as post:
            sync.update_record_with_planner_info(row, task)

        self.assertEqual("update_vbqppl_record", post.call_args.args[0])
        self.assertEqual(187, post.call_args.args[1]["row_number"])


class GraphRecoveryIdempotencyTests(unittest.TestCase):
    @patch.dict(os.environ, ENV, clear=False)
    def test_timeout_after_graph_create_recovers_by_title_before_a_retry_can_duplicate(self):
        row = record()
        recovered = {"id": "recovered-task-id", "title": "[296/2026/NĐ-CP] Nghị định kiểm thử"}
        with patch.object(ms_planner, "get_token", return_value="delegated-token"), patch.object(
            ms_planner, "resolve_next_response_due", return_value="01/08/2026"
        ), patch.object(ms_planner, "build_initial_checklist", return_value={}), patch.object(
            ms_planner, "find_task_by_title", side_effect=[None, recovered]
        ) as find, patch.object(ms_planner, "create_task", side_effect=TimeoutError("response lost")) as create, patch.object(
            ms_planner, "get_task_details", return_value={"@odata.etag": "details-etag"}
        ), patch.object(ms_planner, "update_task_details", return_value={}), patch.object(
            ms_planner, "get_task", return_value={"@odata.etag": "task-etag"}
        ), patch.object(ms_planner, "update_task", return_value={}):
            result = ms_planner.create_planner_task_from_record(row)

        self.assertTrue(result["ok"])
        self.assertTrue(result["reused_existing"])
        self.assertEqual("recovered-task-id", result["task_id"])
        self.assertEqual(1, create.call_count)
        self.assertEqual(2, find.call_count)


if __name__ == "__main__":
    unittest.main()
