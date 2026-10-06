"""Delete a Planner task server-side during a guarded restore operation."""

from __future__ import annotations

from http import HTTPStatus

from _planner_backend import ApiProblem, AppsScriptClient, GraphPlannerClient, JsonApiHandler, clean_text, correlation_id, error_payload


class handler(JsonApiHandler):
    def do_POST(self) -> None:
        request_id = correlation_id()
        try:
            request = self.read_json()
            task_id = clean_text(request.get("planner_task_id") or request.get("task_id"))
            if not task_id:
                raise ApiProblem(HTTPStatus.BAD_REQUEST, "INVALID_TASK_ID", "Thiếu Planner Task ID.")
            # The signed session continues to be verified by Apps Script.  The legacy
            # HMAC envelope is not used in the public-backend architecture.
            AppsScriptClient().validate_admin_session(clean_text(request.get("admin_session")))
            result = GraphPlannerClient().delete_task(task_id, clean_text(request.get("so_hieu")))
            result["correlationId"] = request_id
            self.send_json(HTTPStatus.OK, result)
        except Exception as exc:
            status, payload = error_payload(exc, request_id)
            self.send_json(status, payload)
