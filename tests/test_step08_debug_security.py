"""Offline regression coverage for STEP 08 diagnostic credential handling."""

from __future__ import annotations

import copy
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from contextlib import ExitStack, redirect_stdout
from pathlib import Path
from unittest.mock import MagicMock, call, patch
from urllib.error import HTTPError, URLError
from urllib.parse import quote, quote_plus


PROJECT_DIR = Path(__file__).resolve().parents[1]


def load_module(name, filename):
    spec = importlib.util.spec_from_file_location(name, PROJECT_DIR / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


step08 = load_module("step08_debug_security_test", "08_process_field_documents_batch.py")
step09 = load_module("step09_debug_security_test", "09_validate_pipeline_result.py")

# Generated fixtures only: assertions intentionally never print credential values.
PUBLIC_FIXTURE = "unit-test-public-" + "p" * 32
SERVICE_FIXTURE = "unit-test-service-" + "s" * 32
BUSINESS_MARKER = "unit-test-private-business-content"
URL = "https://example.invalid/apps-script"


def response(data):
    mock = MagicMock()
    mock.__enter__.return_value = mock
    mock.read.return_value = json.dumps(data, ensure_ascii=False).encode("utf-8")
    return mock


def business_response():
    return {
        "ok": True,
        "result": {
            "write_result": {"action": "inserted", "row": 2},
            "match_report": {"reference": {"matched_ids": ["VB001"], "missing_items": []}},
        },
    }


class Step08DebugSecurityTests(unittest.TestCase):
    def setUp(self):
        self.config = {
            "APPS_SCRIPT_WEBAPP_URL": URL,
            "APPS_SCRIPT_TOKEN": PUBLIC_FIXTURE,
            "APPS_SCRIPT_SERVICE_TOKEN": SERVICE_FIXTURE,
            "apps_script_send_max_attempts": 3,
            "apps_script_timeout_seconds": 37,
            "apps_script_retry_base_delay_seconds": 2,
            "apps_script_retry_max_delay_seconds": 12,
        }
        self.payload = {
            "document": BUSINESS_MARKER,
            "nested": [{"password": SERVICE_FIXTURE, "message": PUBLIC_FIXTURE}],
        }
        self.relationships = {"references": [{"access_token": SERVICE_FIXTURE}]}

    def assert_no_credentials(self, value, extra=()):
        serialized = value if isinstance(value, str) else json.dumps(value, ensure_ascii=True)
        for credential in (PUBLIC_FIXTURE, SERVICE_FIXTURE, *extra):
            self.assertTrue(credential not in serialized, "Diagnostic credential exposure detected")

    def send(self, transport, debug=True):
        with patch.object(step08, "urlopen", transport), patch.object(step08, "sleep_before_apps_script_retry") as sleep:
            try:
                result = step08.send_to_apps_script(self.payload, self.relationships, self.config, debug)
            except Exception:
                raise AssertionError("An unexpected diagnostic exception escaped the sender") from None
        return result, sleep

    def test_https_request_contract_and_credentials_are_unchanged(self):
        original_payload = copy.deepcopy(self.payload)
        original_relationships = copy.deepcopy(self.relationships)
        transport = MagicMock(return_value=response(business_response()))
        result, _ = self.send(transport)
        request = transport.call_args.args[0]
        body = json.loads(request.data.decode("utf-8"))
        self.assertTrue(body["token"] == PUBLIC_FIXTURE, "Public request credential changed")
        self.assertTrue(body["service_token"] == SERVICE_FIXTURE, "Service request credential changed")
        self.assertTrue(body["payload"] == original_payload, "Business request payload changed")
        self.assertTrue(body["luoc_do_data"] == original_relationships, "Relationship request payload changed")
        self.assertEqual("import_vbqppl_nhap", body["action"])
        self.assertEqual({"token", "service_token", "action", "payload", "luoc_do_data", "options"}, set(body))
        self.assertEqual({
            "mode": "upsert_preserve_existing",
            "match_keys": ["S\u1ed1 hi\u1ec7u"],
            "update_only_blank_fields": True,
            "preserve_manual_edits": True,
            "allow_manual_override": True,
            "relationship_value_mode": "so_hieu",
            "relationship_cell_strategy": "multi_select",
        }, body["options"])
        self.assertEqual(URL, request.full_url)
        self.assertEqual("POST", request.get_method())
        self.assertEqual("application/json", request.get_header("Content-type"))
        self.assertEqual("close", request.get_header("Connection"))
        self.assertEqual({"timeout": 37}, transport.call_args.kwargs)
        self.assertTrue(self.payload == original_payload and self.relationships == original_relationships,
                        "Sending mutated input data")
        self.assert_no_credentials(result)

    def test_debug_contains_only_request_metadata(self):
        result, _ = self.send(MagicMock(return_value=response(business_response())))
        self.assertTrue("request_body" not in result, "Original request retained in diagnostics")
        metadata = result["request_metadata"]
        self.assertEqual({"action", "request_bytes", "payload_field_count", "relationship_section_count"}, set(metadata))
        self.assertEqual("import_vbqppl_nhap", metadata["action"])
        self.assertEqual(len(self.payload), metadata["payload_field_count"])
        self.assertGreater(metadata["request_bytes"], 0)
        self.assert_no_credentials(result)
        self.assertTrue(BUSINESS_MARKER not in json.dumps(result), "Business payload copied into diagnostics")

    def test_debug_disabled_has_no_request_diagnostics(self):
        result, _ = self.send(MagicMock(return_value=response(business_response())), debug=False)
        self.assertTrue("request_body" not in result, "Original request retained with debug disabled")
        self.assertTrue("request_metadata" not in result, "Request metadata retained with debug disabled")
        self.assert_no_credentials(result)

    def test_success_response_preserves_nonsensitive_business_contract(self):
        expected = business_response()
        result, _ = self.send(MagicMock(return_value=response(expected)))
        self.assertEqual(expected, result["result"])
        self.assertTrue(result["ok"])
        self.assertEqual(1, result["attempt"])

    def test_success_response_scrubs_echoes_nested_fields_and_keys(self):
        extra = "unit-test-unrelated-sensitive-value"
        data = business_response()
        data["details"] = [{"message": PUBLIC_FIXTURE + SERVICE_FIXTURE,
                            "Authorization": extra, "clientSecret": {"arbitrary": extra}}]
        data[PUBLIC_FIXTURE] = {"cookie": extra}
        result, _ = self.send(MagicMock(return_value=response(data)))
        self.assert_no_credentials(result, (extra,))
        self.assertEqual(business_response()["result"], result["result"]["result"])

    def test_non_json_response_content_is_not_retained(self):
        raw_response = response({})
        raw_response.read.return_value = (PUBLIC_FIXTURE + SERVICE_FIXTURE + BUSINESS_MARKER).encode()
        result, _ = self.send(MagicMock(return_value=raw_response))
        self.assertTrue(result["ok"])
        self.assertIn("raw", result["result"])
        self.assert_no_credentials(result)
        self.assertTrue(BUSINESS_MARKER not in json.dumps(result), "Raw server content retained")

    def test_http_error_retry_keeps_policy_and_request_bytes_without_leaking_body(self):
        extra = "unit-test-server-body-sensitive-value"
        failure = HTTPError(URL, 503, PUBLIC_FIXTURE, {}, io.BytesIO((SERVICE_FIXTURE + extra).encode()))
        transport = MagicMock(side_effect=[failure, response(business_response())])
        result, sleep = self.send(transport)
        self.assertTrue(result["ok"])
        self.assertEqual(2, result["attempt"])
        self.assertEqual(2, transport.call_count)
        self.assertTrue(transport.call_args_list[0].args[0].data == transport.call_args_list[1].args[0].data,
                        "Retry changed request bytes")
        self.assertEqual([call(1, 2.0, 12.0)], sleep.call_args_list)
        self.assertTrue(result["retry_errors"][0]["retryable"])
        self.assert_no_credentials(result, (extra,))

    def test_front_end_auth_errors_remain_retryable(self):
        for status in (401, 403):
            with self.subTest(status=status):
                failure = HTTPError(URL, status, SERVICE_FIXTURE, {}, io.BytesIO(PUBLIC_FIXTURE.encode()))
                result, _ = self.send(MagicMock(side_effect=[failure, response(business_response())]))
                self.assertTrue(result["ok"])
                self.assertEqual(2, result["attempt"])
                self.assert_no_credentials(result)

    def test_nonretryable_http_error_stops_without_disclosing_response(self):
        failure = HTTPError(URL, 400, PUBLIC_FIXTURE, {}, io.BytesIO(SERVICE_FIXTURE.encode()))
        transport = MagicMock(side_effect=failure)
        result, sleep = self.send(transport)
        self.assertFalse(result["ok"])
        self.assertEqual(1, transport.call_count)
        sleep.assert_not_called()
        self.assertFalse(result["retry_errors"][0]["retryable"])
        self.assert_no_credentials(result)

    def test_http_error_diagnostic_does_not_read_untrusted_body(self):
        body = MagicMock()
        body.read.side_effect = RuntimeError(SERVICE_FIXTURE)
        failure = HTTPError(URL, 400, PUBLIC_FIXTURE, {}, body)
        result, _ = self.send(MagicMock(side_effect=failure))
        self.assertFalse(result["ok"])
        body.read.assert_not_called()
        self.assert_no_credentials(result)

    def test_urlerror_retry_never_retains_reason(self):
        failure = URLError("timeout " + PUBLIC_FIXTURE + SERVICE_FIXTURE)
        result, _ = self.send(MagicMock(side_effect=[failure, response(business_response())]))
        self.assertTrue(result["ok"])
        self.assertEqual(2, result["attempt"])
        self.assert_no_credentials(result)

    def test_generic_failure_is_safe_with_debug_on_and_off(self):
        for debug in (True, False):
            with self.subTest(debug=debug):
                result, _ = self.send(MagicMock(side_effect=ValueError(PUBLIC_FIXTURE + SERVICE_FIXTURE)), debug)
                self.assertFalse(result["ok"])
                self.assert_no_credentials(result)

    def test_exhausted_timeout_retries_are_safe(self):
        transport = MagicMock(side_effect=TimeoutError(PUBLIC_FIXTURE + SERVICE_FIXTURE))
        result, sleep = self.send(transport)
        self.assertFalse(result["ok"])
        self.assertEqual(3, result["attempt"])
        self.assertEqual(3, transport.call_count)
        self.assertEqual([call(1, 2.0, 12.0), call(2, 2.0, 12.0)], sleep.call_args_list)
        self.assert_no_credentials(result)

    def test_missing_service_token_has_no_public_token_fallback(self):
        self.config.pop("APPS_SCRIPT_SERVICE_TOKEN")
        transport = MagicMock()
        with patch.dict(step08.os.environ, {}, clear=True):
            result, _ = self.send(transport)
        self.assertFalse(result["ok"])
        transport.assert_not_called()
        self.assert_no_credentials(result)

    def test_sanitizer_is_recursive_and_does_not_mutate_input(self):
        extra = "unit-test-nested-sensitive-value"
        data = {"normal": [{"PASSWORD": extra}, {"refresh_token": extra},
                           {"session": {"value": extra}}, {"signature": extra}],
                "echo": PUBLIC_FIXTURE + SERVICE_FIXTURE,
                SERVICE_FIXTURE: {"api_key": extra}}
        original = copy.deepcopy(data)
        clean = step08.sanitize_diagnostic_data(data, (PUBLIC_FIXTURE, SERVICE_FIXTURE))
        self.assertTrue(data == original, "Diagnostic sanitizer mutated its input")
        self.assert_no_credentials(clean, (extra,))
        self.assertEqual("[REDACTED]", clean["normal"][0]["PASSWORD"])

    def test_sanitizer_removes_encoded_credentials(self):
        credential = "unit-test-quoted-" + '"' + "\\\n" + "\u0111"
        encoded = [credential, json.dumps(credential)[1:-1],
                   json.dumps(credential, ensure_ascii=False)[1:-1], quote(credential, safe=""), quote_plus(credential)]
        clean = step08.sanitize_diagnostic_data({"messages": encoded}, (credential,))
        for original in encoded:
            self.assertTrue(original not in json.dumps(clean), "Encoded diagnostic credential exposure detected")
        self.assertTrue(all(value == "[REDACTED]" for value in clean["messages"]))

    def test_debug_row_rejects_unexpected_metadata_and_sensitive_response_values(self):
        sent = {"ok": True, "attempt": PUBLIC_FIXTURE,
                "request_metadata": {"action": SERVICE_FIXTURE, "request_bytes": PUBLIC_FIXTURE,
                                     "payload_field_count": 2, "payload": self.payload},
                "result": {"ok": SERVICE_FIXTURE, "payload": self.payload},
                "retry_errors": [{"error": SERVICE_FIXTURE}]}
        row = step08.build_apps_script_debug_row(sent, 1)
        self.assert_no_credentials(row)
        self.assertTrue(BUSINESS_MARKER not in json.dumps(row), "Unexpected metadata copied into debug")
        self.assertEqual(1, row["attempt"])
        self.assertIsNone(row["response"]["apps_script_ok"])
        self.assertEqual(1, row["retry_count"])

    def run_mock_batch(self, directory, debug, transport=None):
        config = {**self.config, "debug_save_request_body": debug, "dry_run": False, "apps_script_enabled": True,
                  "run_mode": "unit-test", "filters": {"accepted_doc_types": ["Lu\u1eadt"]}}
        document = {"url": "https://example.invalid/van-ban?trace=" + PUBLIC_FIXTURE}
        processed = {"url": document["url"], "source_doc_type": "Lu\u1eadt",
                     "source_doc_number": "1/2026/QH15", "source_title": "Unit test document",
                     "current_doc": {"ngay_hieu_luc": "01/01/2026"}, "luoc_do_data": [],
                     "luoc_do_payload": self.relationships}
        output_file = Path(directory) / "batch.json"
        debug_file = Path(directory) / "debug.json"
        transport = transport if transport is not None else MagicMock(return_value=response(business_response()))
        captured = io.StringIO()
        with ExitStack() as stack:
            for target, value in [("OUTPUT_FILE", output_file), ("OUTPUT_REQUEST_DEBUG_FILE", debug_file)]:
                stack.enter_context(patch.object(step08, target, value))
            stack.enter_context(patch.object(step08, "setup_utf8_stdio"))
            stack.enter_context(patch.object(step08, "load_env_file"))
            stack.enter_context(patch.object(step08, "load_json", side_effect=[config, {"documents": [document]}]))
            stack.enter_context(patch.object(step08, "load_sheet_schema", return_value=step08.DEFAULT_SHEET_COLUMNS))
            stack.enter_context(patch.object(step08, "sync_playwright", MagicMock()))
            stack.enter_context(patch.object(step08, "process_document", return_value=processed))
            stack.enter_context(patch.object(step08, "urlopen", transport))
            stack.enter_context(patch.object(step08.time, "sleep"))
            stack.enter_context(redirect_stdout(captured))
            try:
                step08.main()
            except Exception:
                raise AssertionError("An unexpected exception escaped the mocked batch") from None
        self.assert_no_credentials(captured.getvalue())
        self.assert_no_credentials(output_file.read_text(encoding="utf-8"))
        return json.loads(output_file.read_text(encoding="utf-8")), debug_file, transport, config

    def test_debug_disabled_creates_no_debug_file(self):
        with tempfile.TemporaryDirectory() as directory:
            _, debug_file, _, _ = self.run_mock_batch(directory, False)
            self.assertFalse(debug_file.exists())

    def test_debug_disabled_preserves_existing_debug_file(self):
        with tempfile.TemporaryDirectory() as directory:
            debug_file = Path(directory) / "debug.json"
            original = b"previous diagnostic artifact"
            debug_file.write_bytes(original)
            self.run_mock_batch(directory, False)
            self.assertEqual(original, debug_file.read_bytes())

    def test_debug_enabled_persists_allowlisted_metadata_only(self):
        data = business_response()
        data["echo"] = {"token": PUBLIC_FIXTURE, "service_token": SERVICE_FIXTURE,
                        "business": BUSINESS_MARKER}
        with tempfile.TemporaryDirectory() as directory:
            _, debug_file, _, _ = self.run_mock_batch(directory, True, MagicMock(return_value=response(data)))
            debug_text = debug_file.read_text(encoding="utf-8")
            self.assert_no_credentials(debug_text)
            self.assertTrue(BUSINESS_MARKER not in debug_text, "Business response copied into debug file")
            row = json.loads(debug_text)["rows"][0]
            self.assertEqual({"document_index", "request_metadata", "attempt", "response", "retry_count"}, set(row))
            self.assertEqual({"transport_ok", "apps_script_ok"}, set(row["response"]))
            self.assertTrue(row["response"]["transport_ok"])

    def test_failed_batch_output_debug_and_console_are_safe(self):
        for debug in (True, False):
            with self.subTest(debug=debug), tempfile.TemporaryDirectory() as directory:
                failure = HTTPError(URL, 400, PUBLIC_FIXTURE, {}, io.BytesIO(SERVICE_FIXTURE.encode()))
                output, debug_file, _, _ = self.run_mock_batch(directory, debug, MagicMock(side_effect=failure))
                self.assertEqual("error", output["results"][0]["status"])
                if debug:
                    self.assert_no_credentials(debug_file.read_text(encoding="utf-8"))
                else:
                    self.assertFalse(debug_file.exists())

    def test_successful_batch_sanitizes_response_echoes_with_debug_disabled(self):
        data = business_response()
        data["echo"] = {"message": PUBLIC_FIXTURE + SERVICE_FIXTURE}
        with tempfile.TemporaryDirectory() as directory:
            output, debug_file, _, _ = self.run_mock_batch(directory, False, MagicMock(return_value=response(data)))
            self.assertEqual("sent", output["results"][0]["status"])
            self.assertFalse(debug_file.exists())

    def test_retried_batch_output_debug_and_console_are_safe(self):
        failure = URLError("timeout " + PUBLIC_FIXTURE + SERVICE_FIXTURE)
        transport = MagicMock(side_effect=[failure, response(business_response())])
        with tempfile.TemporaryDirectory() as directory:
            output, debug_file, _, _ = self.run_mock_batch(directory, True, transport)
            self.assertEqual(2, output["results"][0]["send_attempt"])
            self.assert_no_credentials(debug_file.read_text(encoding="utf-8"))

    def test_step09_consumes_new_debug_and_unchanged_batch_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            output, debug_file, _, config = self.run_mock_batch(directory, True)
            debug_data = json.loads(debug_file.read_text(encoding="utf-8"))
            summary = step09.summarize_step08(output, debug_data, config)
            self.assertEqual(1, summary["sent_success_count"])
            self.assertEqual(1, summary["request_debug_rows_count"])
            self.assertEqual(0, summary["payload_invalid_count"])
            self.assertEqual(0, summary["result_error_count"])
            self.assertEqual(0, summary["sent_without_match_report_count"])
            self.assert_no_credentials(summary)

    def test_checked_in_config_disables_request_debug(self):
        config = json.loads((PROJECT_DIR / "config" / "scan_config.json").read_text(encoding="utf-8"))
        self.assertIs(config["debug_save_request_body"], False)


if __name__ == "__main__":
    unittest.main()
