#!/usr/bin/env python3
"""OpenAPI-gated client for owner-bound NetEase Waimao v2 Agent APIs."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


PREFIXES = ("/api/neteasewaimao/v2/", "/api/netease-waimao/v2/")
DENIED = ("/v1/", "/admin", "/login", "/sms", "/usage", "/raw", "/rpa", "webhook")


class ClientError(ValueError):
    def __init__(self, provider_status: str, message: str) -> None:
        super().__init__(message)
        self.provider_status = provider_status


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        raise urllib.error.HTTPError(req.full_url, code, "redirect refused", headers, fp)


def opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(NoRedirect)


def config() -> tuple[str, str, str]:
    base = os.environ.get("OMNIX_API_BASE_URL", "").strip().rstrip("/")
    key = os.environ.get("OMNIX_API_KEY", "").strip()
    if not base:
        raise ClientError("not_configured", "OMNIX_API_BASE_URL is not configured")
    parsed = urllib.parse.urlparse(base)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ClientError("not_configured", "OMNIX_API_BASE_URL must be an absolute HTTP(S) URL")
    if not key:
        raise ClientError("not_configured", "OMNIX_API_KEY is not configured")
    if not (key.startswith("omx_test_") or key.startswith("omx_live_")):
        raise ClientError("not_configured", "OMNIX_API_KEY has an unsupported prefix")
    spec_url = os.environ.get("OMNIX_OPENAPI_URL", "").strip() or f"{base}/swagger/v1/swagger.json"
    spec_parsed = urllib.parse.urlparse(spec_url)
    if (spec_parsed.scheme, spec_parsed.netloc) != (parsed.scheme, parsed.netloc):
        raise ClientError("not_configured", "OMNIX_OPENAPI_URL must use the same origin as OMNIX_API_BASE_URL")
    return base, key, spec_url


def load_openapi(url: str) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with opener().open(request, timeout=20) as response:
        value = json.load(response)
    if not isinstance(value, dict) or not isinstance(value.get("paths"), dict):
        raise ValueError("OpenAPI document does not contain paths")
    return value


def placeholders(template: str) -> list[str]:
    return re.findall(r"\{([^{}]+)\}", template)


def safe_operation(method: str, template: str) -> bool:
    lower = template.lower()
    if not any(lower.startswith(prefix) for prefix in PREFIXES):
        return False
    if any(marker in lower for marker in DENIED):
        return False
    for name in placeholders(template):
        field = name.lower().replace("_", "")
        if ("job" in field or "result" in field) and "public" not in field:
            return False
    return method in {"GET", "POST", "DELETE"}


def operations(spec: dict[str, Any]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for template, path_item in spec["paths"].items():
        if not isinstance(path_item, dict):
            continue
        for method, operation in path_item.items():
            upper = method.upper()
            if safe_operation(upper, template) and isinstance(operation, dict):
                result.append({
                    "method": upper,
                    "path": template,
                    "operationId": str(operation.get("operationId") or ""),
                })
    return sorted(result, key=lambda item: (item["path"], item["method"]))


def template_regex(template: str) -> re.Pattern[str]:
    escaped = re.escape(template)
    return re.compile("^" + re.sub(r"\\\{[^{}]+\\\}", r"[^/]+", escaped) + "$")


def match_operation(spec: dict[str, Any], method: str, path: str) -> str:
    matched = [
        item["path"] for item in operations(spec)
        if item["method"] == method and template_regex(item["path"]).match(path)
    ]
    if len(matched) != 1:
        raise ValueError(f"request does not match exactly one safe v2 OpenAPI operation: {matched}")
    return matched[0]


def parse_body(raw: str) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def body_bytes(path: str | None) -> bytes | None:
    if path is None:
        return None
    raw = sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8")
    value = json.loads(raw)
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def capabilities(_: argparse.Namespace) -> int:
    _, _, spec_url = config()
    spec = load_openapi(spec_url)
    available = operations(spec)
    status = "available" if available else "upstream_unavailable"
    print(json.dumps({"provider": "netease-waimao", "status": status, "operations": available}, ensure_ascii=False, indent=2))
    return 0 if available else 1


def request(args: argparse.Namespace) -> int:
    base, key, spec_url = config()
    method = args.method.upper()
    parsed = urllib.parse.urlsplit(args.path)
    if parsed.scheme or parsed.netloc or not parsed.path.startswith("/"):
        raise ValueError("path must be an absolute-path reference, not a URL")
    spec = load_openapi(spec_url)
    match_operation(spec, method, parsed.path)
    if method == "POST" and not args.idempotency_key:
        raise ValueError("POST requires --idempotency-key")
    if method == "DELETE" and not args.confirm_cancel:
        raise ValueError("DELETE requires --confirm-cancel after explicit user intent")
    payload = body_bytes(args.body)
    if method == "POST" and payload is None:
        raise ValueError("POST requires --body")
    headers = {"Accept": "application/json", "X-API-KEY": key}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    if args.idempotency_key:
        headers["Idempotency-Key"] = args.idempotency_key
    http_request = urllib.request.Request(f"{base}{args.path}", data=payload, headers=headers, method=method)
    try:
        response = opener().open(http_request, timeout=args.timeout)
    except urllib.error.HTTPError as error:
        raw = error.read().decode("utf-8", errors="replace")
        print(json.dumps({"provider": "netease-waimao", "providerStatus": http_provider_status(error.code), "httpStatus": error.code, "data": parse_body(raw)}, ensure_ascii=False, indent=2))
        return 1
    with response:
        raw = response.read().decode("utf-8", errors="replace")
        result = {
            "provider": "netease-waimao",
            "providerStatus": "available",
            "httpStatus": response.status,
            "retryAfter": response.headers.get("Retry-After"),
            "data": parse_body(raw),
        }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def http_provider_status(status: int) -> str:
    return {
        401: "unauthenticated",
        403: "forbidden",
        429: "rate_limited",
    }.get(status, "upstream_unavailable" if status >= 500 else "failed")


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    sub = root.add_subparsers(dest="command", required=True)
    check = sub.add_parser("capabilities")
    check.set_defaults(func=capabilities)
    invoke = sub.add_parser("request")
    invoke.add_argument("method", choices=("GET", "POST", "DELETE"))
    invoke.add_argument("path")
    invoke.add_argument("--body", help="JSON file path, or - for stdin")
    invoke.add_argument("--idempotency-key")
    invoke.add_argument("--confirm-cancel", action="store_true")
    invoke.add_argument("--timeout", type=float, default=30)
    invoke.set_defaults(func=request)
    return root


if __name__ == "__main__":
    try:
        args = parser().parse_args()
        raise SystemExit(args.func(args))
    except ClientError as error:
        print(json.dumps({"provider": "netease-waimao", "status": error.provider_status, "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(2)
    except urllib.error.HTTPError as error:
        print(json.dumps({"provider": "netease-waimao", "status": http_provider_status(error.code), "httpStatus": error.code}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(2)
    except urllib.error.URLError as error:
        print(json.dumps({"provider": "netease-waimao", "status": "upstream_unavailable", "error": str(error.reason)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(2)
    except (ValueError, OSError, json.JSONDecodeError) as error:
        print(json.dumps({"provider": "netease-waimao", "status": "failed", "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(2)
