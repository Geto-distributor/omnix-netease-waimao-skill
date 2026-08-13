from __future__ import annotations

import argparse
import importlib.util
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = json.loads((ROOT / "tests/fixtures/netease-agent-rest.json").read_text(encoding="utf-8"))


def load_client():
    spec = importlib.util.spec_from_file_location("waimao", ROOT / "scripts/waimao.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load NetEase client")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CLIENT = load_client()


class FakeResponse:
    status = 202
    headers = {"Retry-After": None}

    def __init__(self, payload: bytes = b'{"status":"queued","public_job_ref":"pub_job_A1"}') -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, maximum: int = -1) -> bytes:
        return self.payload if maximum < 0 else self.payload[:maximum]


class CapturingOpener:
    def __init__(self, response: FakeResponse | None = None) -> None:
        self.request = None
        self.response = response or FakeResponse()

    def open(self, request, timeout):  # noqa: ANN001, ARG002
        self.request = request
        return self.response


def args(method: str, path: str, body: str | None = None, **overrides):
    values = {
        "method": method, "path": path, "body": body, "idempotency_key": None,
        "confirm_cancel": False, "timeout": 1.0, "max_response_bytes": 1024,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


class OpenApiSafetyTests(unittest.TestCase):
    def test_internal_job_placeholder_and_admin_are_excluded(self) -> None:
        paths = {(item["method"], item["path"]) for item in CLIENT.operations(SPEC)}
        self.assertFalse(any("{jobId}" in path for _, path in paths))
        self.assertFalse(any("/admin" in path for _, path in paths))

    def test_public_ref_pattern_is_checked(self) -> None:
        template = CLIENT.match_operation(
            SPEC, "GET", "/api/NeteaseWaimao/v2/search/jobs/12345"
        )
        operation = CLIENT.operation_definition(SPEC, template, "GET")
        errors = CLIENT.validate_parameters(
            SPEC, template, operation, "/api/NeteaseWaimao/v2/search/jobs/12345", ""
        )
        self.assertTrue(any("pattern" in error for error in errors))

    def test_pagination_bounds_and_required_fields_are_checked(self) -> None:
        path = "/api/NeteaseWaimao/v2/search/jobs/pub_job_A1/results"
        template = CLIENT.match_operation(SPEC, "GET", path)
        operation = CLIENT.operation_definition(SPEC, template, "GET")
        missing = CLIENT.validate_parameters(SPEC, template, operation, path, "pageNumber=1")
        too_large = CLIENT.validate_parameters(
            SPEC, template, operation, path, "pageNumber=1&pageSize=1000"
        )
        self.assertTrue(any("pageSize" in error for error in missing))
        self.assertTrue(any("maximum" in error for error in too_large))

    def test_request_body_rejects_owner_and_internal_ids(self) -> None:
        errors = CLIENT.forbidden_request_paths({
            "public_result_ref": "pub_result_A1", "owner_id": "other", "job_id": "internal"
        })
        self.assertEqual(len(errors), 2)

    def test_internal_response_ids_are_removed(self) -> None:
        data, warnings = CLIENT.sanitize_response({
            "public_job_ref": "pub_job_A1", "job_id": "internal-1",
            "nested": {
                "search_result_id": "internal-2", "upstream_job_id": "internal-3"
            },
        })
        self.assertEqual(data["public_job_ref"], "pub_job_A1")
        self.assertNotIn("job_id", data)
        self.assertNotIn("search_result_id", data["nested"])
        self.assertNotIn("upstream_job_id", data["nested"])
        self.assertEqual(len(warnings), 3)

    def test_sensitive_values_embedded_in_messages_are_redacted(self) -> None:
        data, warnings = CLIENT.sanitize_response({
            "message": "upstream_job_id=raw-123 key=omx_test_should-not-leak"
        })
        self.assertNotIn("raw-123", data["message"])
        self.assertNotIn("omx_test_", data["message"])
        self.assertEqual(len(warnings), 1)


class AsyncStatusTests(unittest.TestCase):
    def test_all_documented_job_statuses_normalize(self) -> None:
        cases = {
            "queued": "queued", "running": "running", "completed": "completed",
            "failed": "failed", "cancelled": "cancelled",
            "session_expired": "provider_session_expired",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(CLIENT.normalized_job_status({"task_status": raw}), expected)


class RequestTests(unittest.TestCase):
    def run_request(self, request_args, response: FakeResponse | None = None):
        capturing = CapturingOpener(response)
        output = StringIO()
        with mock.patch.object(
            CLIENT, "config", return_value=("https://omnix.example", "omx_test_fixture", "spec")
        ), mock.patch.object(CLIENT, "load_openapi", return_value=SPEC), mock.patch.object(
            CLIENT, "opener", return_value=capturing
        ), redirect_stdout(output):
            result = CLIENT.request(request_args)
        return result, capturing.request, json.loads(output.getvalue())

    def test_post_sends_idempotency_and_returns_queued_not_completed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            body = Path(directory) / "search.json"
            body.write_text('{"countryCode":"AU","keywords":["formwork"]}', encoding="utf-8")
            result, request, output = self.run_request(args(
                "POST", "/api/NeteaseWaimao/v2/search/jobs", str(body),
                idempotency_key="stable-search-key",
            ))
        self.assertEqual(result, 0)
        self.assertEqual(request.get_header("Idempotency-key"), "stable-search-key")
        self.assertEqual(output["jobStatus"], "queued")
        self.assertEqual(output["providerStatus"], "available")

    def test_session_expired_is_separate_provider_status(self) -> None:
        path = "/api/NeteaseWaimao/v2/search/jobs/pub_job_A1"
        result, _, output = self.run_request(
            args("GET", path), FakeResponse(b'{"status":"session_expired"}')
        )
        self.assertEqual(result, 0)
        self.assertEqual(output["jobStatus"], "provider_session_expired")
        self.assertEqual(output["providerStatus"], "provider_session_expired")

    def test_response_size_is_bounded(self) -> None:
        path = "/api/NeteaseWaimao/v2/search/jobs/pub_job_A1"
        with self.assertRaisesRegex(ValueError, "response exceeds"):
            self.run_request(
                args("GET", path, max_response_bytes=10),
                FakeResponse(b'{"status":"queued","padding":"too-large"}'),
            )


if __name__ == "__main__":
    unittest.main()
