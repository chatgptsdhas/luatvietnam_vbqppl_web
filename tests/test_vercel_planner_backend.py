"""Unit tests for the public-backend Planner workflow (no network calls)."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


API_DIR = Path(__file__).resolve().parents[1] / "api"
sys.path.insert(0, str(API_DIR))

from _planner_backend import sync_transferred_record  # noqa: E402


class FakeApps:
    def __init__(self, record):
        self.record = record
        self.updated_row = None
        self.updated_fields = None

    def get_records(self):
        return [self.record]

    def update_planner_fields(self, row_number, fields):
        self.updated_row = row_number
        self.updated_fields = fields
        return {"ok": True}


class FakeGraph:
    def __init__(self, existing=None):
        self.existing = existing
        self.created = []
        self.configured = []

    def find_task_by_title(self, title):
        return self.existing

    def create_task(self, record):
        self.created.append(record)
        return {"id": "new-task-id"}

    def configure_new_task(self, task_id, record, due):
        self.configured.append((task_id, record, due))


def record(task_id=""):
    return {
        "_rowNumber": 187,
        "Số hiệu": "296/2026/NĐ-CP",
        "Tên văn bản": "Nghị định kiểm thử",
        "Loại văn bản": "Nghị định",
        "Ngày hiệu lực": "23/07/2026",
        "Link Văn bản": "https://example.test/296",
        "Planner Task ID": task_id,
    }


ENV = {
    "LEGAL_DEFAULT_DUE_DAYS": "5",
    "PLANNER_PLAN_ID": "plan-id",
    "PLANNER_BUCKET_ID_PHAP_CHE": "bucket-id",
    "PLANNER_INITIAL_ASSIGNEE_USER_IDS": "user-id",
    "PLANNER_INITIAL_ASSIGNEE_EMAILS": "legal@example.test",
    "PLANNER_INITIAL_ASSIGNEE_DEPARTMENTS": "HO",
    "TENANT_ID": "tenant-id",
    "PLANNER_TASK_URL_TEMPLATE": "https://planner.test/{plan_id}/{task_id}?tenant={tenant_id}",
}


class SyncTransferredRecordTests(unittest.TestCase):
    @patch.dict(os.environ, ENV, clear=False)
    def test_creates_task_and_writes_back_to_exact_target_row(self):
        apps = FakeApps(record())
        graph = FakeGraph()

        result = sync_transferred_record(apps, graph, target_row_number=187, so_hieu="296/2026/NĐ-CP")

        self.assertTrue(result["ok"])
        self.assertTrue(result["created"])
        self.assertEqual("new-task-id", result["task_id"])
        self.assertEqual(187, apps.updated_row)
        self.assertEqual("new-task-id", apps.updated_fields["Planner Task ID"])
        self.assertEqual("Đã tạo task Planner", apps.updated_fields["Planner Sync Status"])
        self.assertEqual(1, len(graph.created))
        self.assertEqual(1, len(graph.configured))

    @patch.dict(os.environ, ENV, clear=False)
    def test_reuses_matching_existing_task_after_partial_failure(self):
        apps = FakeApps(record())
        graph = FakeGraph(existing={"id": "existing-task-id", "title": "[296/2026/NĐ-CP] Nghị định kiểm thử"})

        result = sync_transferred_record(apps, graph, target_row_number=187)

        self.assertTrue(result["ok"])
        self.assertTrue(result["already_existed"])
        self.assertEqual("existing-task-id", apps.updated_fields["Planner Task ID"])
        self.assertEqual([], graph.created)

    @patch.dict(os.environ, ENV, clear=False)
    def test_existing_sheet_task_never_creates_a_duplicate(self):
        apps = FakeApps(record(task_id="sheet-task-id"))
        graph = FakeGraph()

        result = sync_transferred_record(apps, graph, target_row_number=187)

        self.assertTrue(result["already_existed"])
        self.assertEqual("sheet-task-id", result["task_id"])
        self.assertEqual([], graph.created)


if __name__ == "__main__":
    unittest.main()
