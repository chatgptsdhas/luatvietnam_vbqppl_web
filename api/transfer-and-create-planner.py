"""Atomic user-facing transfer workflow: Apps Script transfer, then Planner sync."""

from __future__ import annotations

from http import HTTPStatus

from _planner_backend import ApiProblem, AppsScriptClient, GraphPlannerClient, JsonApiHandler, clean_text, correlation_id, error_payload, sync_transferred_record


class handler(JsonApiHandler):
    def do_POST(self) -> None:
        request_id = correlation_id()
        try:
            request = self.read_json()
            admin_session = clean_text(request.get("admin_session"))
            try:
                source_row_number = int(request.get("row_number"))
            except (TypeError, ValueError) as exc:
                raise ApiProblem(HTTPStatus.BAD_REQUEST, "INVALID_ROW_NUMBER", "row_number không hợp lệ.") from exc
            if source_row_number < 2:
                raise ApiProblem(HTTPStatus.BAD_REQUEST, "INVALID_ROW_NUMBER", "row_number không hợp lệ.")

            apps = AppsScriptClient()
            # transfer_record is the authoritative session validation and also writes the
            # source/target sheets.  It is intentionally never performed by the browser.
            transfer = apps.call("transfer_record", {"row_number": source_row_number}, admin_session=admin_session)
            if not transfer.get("ok"):
                transfer.setdefault("correlationId", request_id)
                self.send_json(HTTPStatus.OK, transfer)
                return

            planner_result: dict
            try:
                planner_result = sync_transferred_record(
                    apps,
                    GraphPlannerClient(),
                    target_row_number=transfer.get("vbqppl_row_number"),
                    so_hieu=clean_text(transfer.get("soHieu")),
                )
            except Exception as planner_error:
                _, planner_payload = error_payload(planner_error, request_id)
                # Transfer is durable even if Planner is temporarily unavailable.  The UI
                # needs this distinction so it does not falsely offer a second transfer.
                self.send_json(
                    HTTPStatus.OK,
                    {
                        "ok": True,
                        "transfer": transfer,
                        "planner": planner_payload,
                        "planner_ok": False,
                        "message": "Đã chuyển văn bản nhưng chưa tạo được task Planner.",
                        "correlationId": request_id,
                    },
                )
                return

            self.send_json(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "transfer": transfer,
                    "planner": planner_result,
                    "planner_ok": True,
                    "soHieu": planner_result.get("so_hieu") or transfer.get("soHieu") or "",
                    "vbqppl_row_number": planner_result.get("target_row_number") or transfer.get("vbqppl_row_number") or "",
                    "correlationId": request_id,
                },
            )
        except Exception as exc:
            status, payload = error_payload(exc, request_id)
            self.send_json(status, payload)
