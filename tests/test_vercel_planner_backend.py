"""Unit tests for the local delegated Planner flow (no network calls)."""

from __future__ import annotations

import importlib.util
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_DIR = Path(__file__).resolve().parents[1]
API_DIR = PROJECT_DIR / "api"
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))


def load_numbered_module(filename: str, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, PROJECT_DIR / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


sync = load_numbered_module("11_sync_webapp_to_planner.py", "sync_webapp_to_planner_test")
import ms_planner  # noqa: E402
import _planner_backend as planner_backend  # noqa: E402


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


class FakeResponse:
    def __init__(self, status_code: int, payload=None, *, headers=None, json_error: Exception | None = None):
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}
        self._json_error = json_error

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 400

    def json(self):
        if self._json_error:
            raise self._json_error
        return self._payload


class SequencedHttp:
    def __init__(self, *, post_items, get_items=()):
        self.post_items = list(post_items)
        self.get_items = list(get_items)
        self.post_calls = []
        self.get_calls = []

    @staticmethod
    def _next(items):
        item = items.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    def post(self, url, **kwargs):
        self.post_calls.append((url, kwargs))
        return self._next(self.post_items)

    def get(self, url, **kwargs):
        self.get_calls.append((url, kwargs))
        return self._next(self.get_items)


APPS_SCRIPT_ENV = {
    "APPS_SCRIPT_WEBAPP_URL": "https://script.google.com/macros/s/unit-test/exec",
    "APPS_SCRIPT_TOKEN": "unit-test-public-token",
}
CONTENT_SERVICE_URL = "https://script.googleusercontent.com/macros/echo?user_content_key=unit-test"


class AppsScriptClientRedirectTests(unittest.TestCase):
    def _client(self, *, post_items, get_items=()):
        http = SequencedHttp(post_items=post_items, get_items=get_items)
        return planner_backend.AppsScriptClient(http=http), http

    @patch.dict(os.environ, APPS_SCRIPT_ENV, clear=False)
    def test_verify_admin_redirect_post_then_get_json_uses_one_post_and_one_get(self):
        client, http = self._client(
            post_items=[FakeResponse(302, headers={"Location": CONTENT_SERVICE_URL})],
            get_items=[FakeResponse(200, {"ok": True, "adminSession": "test-session"}, headers={"Content-Type": "application/json"})],
        )

        result = client.call("verify_admin", {"password": "test-password"})

        self.assertTrue(result["ok"])
        self.assertEqual(1, len(http.post_calls))
        self.assertEqual(1, len(http.get_calls))
        self.assertEqual(planner_backend.WEBAPP_ADMIN_TIMEOUT_SECONDS, http.post_calls[0][1]["timeout"])
        self.assertFalse(http.post_calls[0][1]["allow_redirects"])
        self.assertEqual(planner_backend.WEBAPP_CONTENTSERVICE_TIMEOUT_SECONDS, http.get_calls[0][1]["timeout"])
        self.assertFalse(http.get_calls[0][1]["allow_redirects"])

    @patch.dict(os.environ, APPS_SCRIPT_ENV, clear=False)
    def test_verify_admin_retries_contentservice_get_without_reposting(self):
        client, http = self._client(
            post_items=[FakeResponse(302, headers={"Location": CONTENT_SERVICE_URL})],
            get_items=[
                FakeResponse(502, {}),
                FakeResponse(200, {"ok": True, "adminSession": "test-session"}, headers={"Content-Type": "application/json"}),
            ],
        )
        with patch.object(planner_backend.time, "sleep") as sleep:
            result = client.call("verify_admin", {"password": "test-password"})

        self.assertTrue(result["ok"])
        self.assertEqual(1, len(http.post_calls))
        self.assertEqual(2, len(http.get_calls))
        sleep.assert_called_once_with(0.5)

    @patch.dict(os.environ, APPS_SCRIPT_ENV, clear=False)
    def test_verify_admin_retries_non_json_contentservice_response_without_reposting(self):
        client, http = self._client(
            post_items=[FakeResponse(302, headers={"Location": CONTENT_SERVICE_URL})],
            get_items=[
                FakeResponse(200, "<html>temporary response</html>", headers={"Content-Type": "text/html"}),
                FakeResponse(200, {"ok": True}, headers={"Content-Type": "application/json"}),
            ],
        )
        with patch.object(planner_backend.time, "sleep") as sleep:
            result = client.call("verify_admin", {"password": "test-password"})

        self.assertTrue(result["ok"])
        self.assertEqual(1, len(http.post_calls))
        self.assertEqual(2, len(http.get_calls))
        sleep.assert_called_once_with(0.5)

    @patch.dict(os.environ, APPS_SCRIPT_ENV, clear=False)
    def test_verify_admin_retries_malformed_json_contentservice_response_without_reposting(self):
        client, http = self._client(
            post_items=[FakeResponse(302, headers={"Location": CONTENT_SERVICE_URL})],
            get_items=[
                FakeResponse(
                    200,
                    headers={"Content-Type": "application/json"},
                    json_error=ValueError("invalid JSON"),
                ),
                FakeResponse(200, {"ok": True}, headers={"Content-Type": "application/json"}),
            ],
        )
        with patch.object(planner_backend.time, "sleep") as sleep:
            result = client.call("verify_admin", {"password": "test-password"})

        self.assertTrue(result["ok"])
        self.assertEqual(1, len(http.post_calls))
        self.assertEqual(2, len(http.get_calls))
        sleep.assert_called_once_with(0.5)

    @patch.dict(os.environ, APPS_SCRIPT_ENV, clear=False)
    def test_verify_admin_retries_non_object_json_contentservice_response_without_reposting(self):
        client, http = self._client(
            post_items=[FakeResponse(302, headers={"Location": CONTENT_SERVICE_URL})],
            get_items=[
                FakeResponse(200, ["not", "an", "object"], headers={"Content-Type": "application/json"}),
                FakeResponse(200, {"ok": True}, headers={"Content-Type": "application/json"}),
            ],
        )
        with patch.object(planner_backend.time, "sleep") as sleep:
            result = client.call("verify_admin", {"password": "test-password"})

        self.assertTrue(result["ok"])
        self.assertEqual(1, len(http.post_calls))
        self.assertEqual(2, len(http.get_calls))
        sleep.assert_called_once_with(0.5)

    @patch.dict(os.environ, APPS_SCRIPT_ENV, clear=False)
    def test_verify_admin_contentservice_get_exhaustion_does_not_repost(self):
        client, http = self._client(
            post_items=[FakeResponse(302, headers={"Location": CONTENT_SERVICE_URL})],
            get_items=[FakeResponse(502, {}), FakeResponse(502, {}), FakeResponse(502, {})],
        )
        with patch.object(planner_backend.time, "sleep"):
            with self.assertRaises(planner_backend.ApiProblem) as caught:
                client.call("verify_admin", {"password": "test-password"})

        self.assertEqual("APPS_SCRIPT_UNAVAILABLE", caught.exception.code)
        self.assertEqual(1, len(http.post_calls))
        self.assertEqual(3, len(http.get_calls))

    @patch.dict(os.environ, APPS_SCRIPT_ENV, clear=False)
    def test_verify_admin_rejects_untrusted_redirect_without_following_it(self):
        client, http = self._client(
            post_items=[FakeResponse(302, headers={"Location": "https://attacker.example/redirect"})],
        )

        with self.assertRaises(planner_backend.ApiProblem) as caught:
            client.call("verify_admin", {"password": "test-password"})

        self.assertEqual("APPS_SCRIPT_UNAVAILABLE", caught.exception.code)
        self.assertEqual(1, len(http.post_calls))
        self.assertEqual([], http.get_calls)
        self.assertNotIn("attacker.example", caught.exception.message)

    @patch.dict(os.environ, APPS_SCRIPT_ENV, clear=False)
    def test_ordinary_action_keeps_post_retry_policy(self):
        client, http = self._client(
            post_items=[FakeResponse(502, {}), FakeResponse(200, {"ok": True, "data": []})],
        )
        with patch.object(planner_backend.time, "sleep") as sleep:
            result = client.call("get_all_records")

        self.assertTrue(result["ok"])
        self.assertEqual(2, len(http.post_calls))
        self.assertEqual([], http.get_calls)
        self.assertEqual(planner_backend.WEBAPP_TIMEOUT_SECONDS, http.post_calls[0][1]["timeout"])
        self.assertNotIn("allow_redirects", http.post_calls[0][1])
        sleep.assert_called_once_with(0.5)

    @patch.dict(os.environ, APPS_SCRIPT_ENV, clear=False)
    def test_verify_admin_post_timeout_is_not_retried(self):
        client, http = self._client(post_items=[planner_backend.requests.Timeout("timed out")])

        with self.assertRaises(planner_backend.ApiProblem) as caught:
            client.call("verify_admin", {"password": "test-password"})

        self.assertEqual("APPS_SCRIPT_UNAVAILABLE", caught.exception.code)
        self.assertEqual(1, len(http.post_calls))
        self.assertEqual([], http.get_calls)


if __name__ == "__main__":
    unittest.main()
