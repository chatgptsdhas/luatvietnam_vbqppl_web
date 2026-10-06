"""Same-origin proxy for Dashboard -> Apps Script calls.

The proxy removes browser CORS/redirect exposure and injects APPS_SCRIPT_TOKEN
on the server.  Apps Script remains the authority for its own admin session.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import Any

from _planner_backend import ADMIN_ACTIONS, SERVICE_ONLY_ACTIONS, ApiProblem, AppsScriptClient, JsonApiHandler, clean_text, correlation_id, error_payload


class handler(JsonApiHandler):
    def do_POST(self) -> None:
        request_id = correlation_id()
        try:
            request = self.read_json()
            action = clean_text(request.get("action"))
            if not action:
                raise ApiProblem(HTTPStatus.BAD_REQUEST, "INVALID_ACTION", "Thiếu action.")
            if action in SERVICE_ONLY_ACTIONS or action == "request_planner_sync_envelope":
                raise ApiProblem(HTTPStatus.FORBIDDEN, "ACTION_NOT_ALLOWED", "Action này không được gọi từ trình duyệt.")

            payload = request.get("payload") or {}
            if not isinstance(payload, dict):
                raise ApiProblem(HTTPStatus.BAD_REQUEST, "INVALID_PAYLOAD", "payload phải là JSON object.")
            admin_session = clean_text(request.get("admin_session"))
            if action in ADMIN_ACTIONS and not admin_session:
                raise ApiProblem(HTTPStatus.UNAUTHORIZED, "ADMIN_SESSION_REQUIRED", "Vui lòng đăng nhập quản trị viên.")

            result = AppsScriptClient().call(action, payload, admin_session=admin_session)
            if isinstance(result, dict) and "correlationId" not in result:
                result["correlationId"] = request_id
            self.send_json(HTTPStatus.OK, result)
        except Exception as exc:
            status, payload = error_payload(exc, request_id)
            self.send_json(status, payload)
