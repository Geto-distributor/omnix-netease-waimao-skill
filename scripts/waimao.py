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
FORBIDDEN_REQUEST_FIELDS = {
    "owner", "ownerid", "useraccountid", "tenant", "tenantid",
    "jobid", "resultid", "searchresultid", "internaljobid", "internalresultid",
    "upstreamjobid", "upstreamresultid", "rpaid",
}
INTERNAL_RESPONSE_FIELDS = {
    "jobid", "resultid", "searchresultid", "internaljobid", "internalresultid",
    "upstreamjobid", "upstreamresultid", "rpaid",
    "rpataskid", "rpajobid", "rparesultid",
}
JOB_STATUS_MAP = {
    "queued": "queued",
    "pending": "queued",
    "running": "running",
    "inprogress": "running",
    "completed": "completed",
    "succeeded": "completed",
    "failed": "failed",
    "cancelled": "cancelled",
    "canceled": "cancelled",
    "providersessionexpired": "provider_session_expired",
    "sessionexpired": "provider_session_expired",
}
SENSITIVE_TEXT_PATTERNS = (
    re.compile(r"omx_(?:test|live)_[A-Za-z0-9_-]+", re.IGNORECASE),
    re.compile(
        r"(?i)\b(?:upstream_|internal_)?(?:job|result|search_result)_id\b\s*[:=]\s*[^\s,;]+"
    ),
)
SERVER_CONFIGURATION_MARKERS = {
    "SEARCH_RESULTS_JSON_PATH": "server_configuration_missing",
}


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


def normalize_field(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def resolve_pointer(document: dict[str, Any], reference: str) -> Any:
    if not reference.startswith("#/"):
        raise ValueError(f"only local OpenAPI references are supported: {reference}")
    value: Any = document
    for token in reference[2:].split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        if not isinstance(value, dict) or token not in value:
            raise ValueError(f"OpenAPI reference does not resolve: {reference}")
        value = value[token]
    return value


def resolve_object(spec: dict[str, Any], value: Any) -> Any:
    seen: set[str] = set()
    while isinstance(value, dict) and isinstance(value.get("$ref"), str):
        reference = value["$ref"]
        if reference in seen:
            raise ValueError(f"cyclic OpenAPI reference: {reference}")
        seen.add(reference)
        value = resolve_pointer(spec, reference)
    return value


def operation_definition(spec: dict[str, Any], template: str, method: str) -> dict[str, Any]:
    path_item = spec["paths"].get(template)
    operation = path_item.get(method.lower()) if isinstance(path_item, dict) else None
    if not isinstance(operation, dict):
        raise ValueError("matched OpenAPI operation has no definition")
    return operation


def operation_parameters(
    spec: dict[str, Any], template: str, operation: dict[str, Any]
) -> list[dict[str, Any]]:
    path_item = spec["paths"].get(template)
    values: list[Any] = []
    if isinstance(path_item, dict) and isinstance(path_item.get("parameters"), list):
        values.extend(path_item["parameters"])
    if isinstance(operation.get("parameters"), list):
        values.extend(operation["parameters"])
    return [value for item in values if isinstance((value := resolve_object(spec, item)), dict)]


def path_values(template: str, concrete_path: str) -> dict[str, str]:
    template_parts = template.strip("/").split("/")
    concrete_parts = concrete_path.strip("/").split("/")
    if len(template_parts) != len(concrete_parts):
        return {}
    values: dict[str, str] = {}
    for expected, actual in zip(template_parts, concrete_parts):
        if expected.startswith("{") and expected.endswith("}"):
            values[expected[1:-1]] = urllib.parse.unquote(actual)
    return values


def validate_parameter_value(raw: str, schema: Any, location: str, spec: dict[str, Any]) -> list[str]:
    schema = resolve_object(spec, schema)
    if not isinstance(schema, dict):
        return []
    errors: list[str] = []
    expected = schema.get("type")
    value: Any = raw
    if expected == "integer":
        try:
            value = int(raw)
        except ValueError:
            return [f"{location}: expected integer"]
    elif expected == "number":
        try:
            value = float(raw)
        except ValueError:
            return [f"{location}: expected number"]
    elif expected == "boolean":
        if raw.lower() not in {"true", "false"}:
            return [f"{location}: expected boolean"]
        value = raw.lower() == "true"
    if isinstance(schema.get("enum"), list) and value not in schema["enum"]:
        errors.append(f"{location}: value is not in OpenAPI enum {schema['enum']}")
    if isinstance(schema.get("pattern"), str) and not re.fullmatch(schema["pattern"], raw):
        errors.append(f"{location}: value does not match OpenAPI pattern")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if isinstance(schema.get("minimum"), (int, float)) and value < schema["minimum"]:
            errors.append(f"{location}: below OpenAPI minimum")
        if isinstance(schema.get("maximum"), (int, float)) and value > schema["maximum"]:
            errors.append(f"{location}: above OpenAPI maximum")
    return errors


def validate_parameters(
    spec: dict[str, Any],
    template: str,
    operation: dict[str, Any],
    concrete_path: str,
    query: str,
) -> list[str]:
    parameters = operation_parameters(spec, template, operation)
    query_values = urllib.parse.parse_qs(query, keep_blank_values=True)
    declared_query = {
        item.get("name"): item for item in parameters
        if item.get("in") == "query" and isinstance(item.get("name"), str)
    }
    errors: list[str] = []
    for name in query_values.keys() - declared_query.keys():
        errors.append(f"query parameter is not declared by OpenAPI: {name}")
    for name, parameter in declared_query.items():
        if parameter.get("required") is True and name not in query_values:
            errors.append(f"required OpenAPI query parameter is missing: {name}")
        for raw in query_values.get(str(name), []):
            errors.extend(validate_parameter_value(raw, parameter.get("schema"), f"query.{name}", spec))
    concrete_values = path_values(template, concrete_path)
    for parameter in parameters:
        if parameter.get("in") != "path" or not isinstance(parameter.get("name"), str):
            continue
        name = parameter["name"]
        raw = concrete_values.get(name)
        if raw is None:
            errors.append(f"required OpenAPI path parameter is missing: {name}")
        else:
            errors.extend(validate_parameter_value(raw, parameter.get("schema"), f"path.{name}", spec))
    return errors


def request_schema(spec: dict[str, Any], operation: dict[str, Any]) -> dict[str, Any] | None:
    request_body = resolve_object(spec, operation.get("requestBody"))
    if not isinstance(request_body, dict):
        return None
    content = request_body.get("content")
    if not isinstance(content, dict):
        return None
    media = content.get("application/json")
    if not isinstance(media, dict):
        media = next(
            (value for key, value in content.items() if key.endswith("+json") and isinstance(value, dict)),
            None,
        )
    schema = media.get("schema") if isinstance(media, dict) else None
    return schema if isinstance(schema, dict) else None


def json_type_matches(value: Any, expected: str) -> bool:
    return {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
        "null": value is None,
    }.get(expected, True)


def validate_json_schema(
    value: Any,
    schema: dict[str, Any],
    spec: dict[str, Any],
    location: str = "$",
    depth: int = 0,
) -> list[str]:
    if depth > 32:
        return [f"{location}: OpenAPI schema nesting exceeds 32 levels"]
    schema = resolve_object(spec, schema)
    if not isinstance(schema, dict):
        return []
    if value is None and schema.get("nullable") is True:
        return []
    expected = schema.get("type")
    if isinstance(expected, str) and not json_type_matches(value, expected):
        return [f"{location}: expected OpenAPI type {expected}"]
    errors: list[str] = []
    if isinstance(schema.get("enum"), list) and value not in schema["enum"]:
        errors.append(f"{location}: value is not in OpenAPI enum {schema['enum']}")
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        properties = properties if isinstance(properties, dict) else {}
        required = schema.get("required", [])
        for name in required if isinstance(required, list) else []:
            if name not in value:
                errors.append(f"{location}.{name}: required by OpenAPI")
        if schema.get("additionalProperties") is False:
            for name in value.keys() - properties.keys():
                errors.append(f"{location}.{name}: property is not allowed by OpenAPI")
        for name, child in value.items():
            child_schema = properties.get(name)
            if isinstance(child_schema, dict):
                errors.extend(
                    validate_json_schema(child, child_schema, spec, f"{location}.{name}", depth + 1)
                )
    if isinstance(value, list):
        if isinstance(schema.get("minItems"), int) and len(value) < schema["minItems"]:
            errors.append(f"{location}: requires at least {schema['minItems']} item(s)")
        if isinstance(schema.get("maxItems"), int) and len(value) > schema["maxItems"]:
            errors.append(f"{location}: allows at most {schema['maxItems']} item(s)")
        items = schema.get("items")
        if isinstance(items, dict):
            for index, child in enumerate(value):
                errors.extend(validate_json_schema(child, items, spec, f"{location}[{index}]", depth + 1))
    if isinstance(value, str):
        if isinstance(schema.get("minLength"), int) and len(value) < schema["minLength"]:
            errors.append(f"{location}: shorter than OpenAPI minLength")
        if isinstance(schema.get("maxLength"), int) and len(value) > schema["maxLength"]:
            errors.append(f"{location}: longer than OpenAPI maxLength")
        if isinstance(schema.get("pattern"), str) and not re.fullmatch(schema["pattern"], value):
            errors.append(f"{location}: value does not match OpenAPI pattern")
    return errors


def forbidden_request_paths(value: Any, location: str = "$.") -> list[str]:
    errors: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = normalize_field(str(key))
            if normalized in FORBIDDEN_REQUEST_FIELDS and not normalized.startswith("public"):
                errors.append(f"{location}{key}: owner/internal identifier is forbidden")
            errors.extend(forbidden_request_paths(child, f"{location}{key}."))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            errors.extend(forbidden_request_paths(child, f"{location}{index}."))
    return errors


def sanitize_response(value: Any, location: str = "$") -> tuple[Any, list[str]]:
    warnings: list[str] = []
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, child in value.items():
            normalized = normalize_field(str(key))
            if normalized in INTERNAL_RESPONSE_FIELDS and not normalized.startswith("public"):
                warnings.append(f"removed internal response field {location}.{key}")
                continue
            safe_child, child_warnings = sanitize_response(child, f"{location}.{key}")
            sanitized[key] = safe_child
            warnings.extend(child_warnings)
        return sanitized, warnings
    if isinstance(value, list):
        sanitized_items = []
        for index, child in enumerate(value):
            safe_child, child_warnings = sanitize_response(child, f"{location}[{index}]")
            sanitized_items.append(safe_child)
            warnings.extend(child_warnings)
        return sanitized_items, warnings
    if isinstance(value, str):
        sanitized_text = value
        for pattern in SENSITIVE_TEXT_PATTERNS:
            sanitized_text = pattern.sub("[redacted-sensitive-value]", sanitized_text)
        if sanitized_text != value:
            warnings.append(f"redacted sensitive text at {location}")
        return sanitized_text, warnings
    return value, warnings


def normalized_job_status(value: Any) -> str | None:
    if isinstance(value, dict):
        for key, child in value.items():
            if normalize_field(str(key)) in {"status", "jobstatus", "taskstatus"} and isinstance(child, str):
                normalized = JOB_STATUS_MAP.get(normalize_field(child))
                if normalized:
                    return normalized
        for child in value.values():
            normalized = normalized_job_status(child)
            if normalized:
                return normalized
    elif isinstance(value, list):
        for child in value:
            normalized = normalized_job_status(child)
            if normalized:
                return normalized
    return None


def diagnostic_codes(value: Any) -> list[str]:
    text = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
    upper = text.upper()
    return sorted({code for marker, code in SERVER_CONFIGURATION_MARKERS.items() if marker in upper})


def semantic_provider_status(value: Any, job_status: str | None, http_status: int) -> str:
    if diagnostic_codes(value):
        return "failed"
    if job_status == "provider_session_expired":
        return "provider_session_expired"
    if job_status == "failed":
        return "failed"
    return http_provider_status(http_status) if http_status >= 400 else "available"


def parse_body(raw: str) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def body_bytes(path: str | None) -> tuple[Any | None, bytes | None]:
    if path is None:
        return None, None
    raw = sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8")
    value = json.loads(raw)
    data = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return value, data


def read_limited(response: Any, maximum: int) -> str:
    raw = response.read(maximum + 1)
    if len(raw) > maximum:
        raise ValueError(f"response exceeds --max-response-bytes={maximum}")
    return raw.decode("utf-8", errors="replace")


def capabilities(_: argparse.Namespace) -> int:
    _, _, spec_url = config()
    spec = load_openapi(spec_url)
    available = operations(spec)
    status = "available" if available else "upstream_unavailable"
    print(json.dumps({"provider": "netease-waimao", "status": status, "operations": available}, ensure_ascii=False, indent=2))
    return 0 if available else 1


def request(args: argparse.Namespace) -> int:
    base, key, spec_url = config()
    if args.max_response_bytes <= 0:
        raise ValueError("--max-response-bytes must be positive")
    method = args.method.upper()
    parsed = urllib.parse.urlsplit(args.path)
    if parsed.scheme or parsed.netloc or not parsed.path.startswith("/"):
        raise ValueError("path must be an absolute-path reference, not a URL")
    spec = load_openapi(spec_url)
    template = match_operation(spec, method, parsed.path)
    operation = operation_definition(spec, template, method)
    parameter_errors = validate_parameters(
        spec, template, operation, parsed.path, parsed.query
    )
    forbidden_query = [
        name for name in urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
        if normalize_field(name) in FORBIDDEN_REQUEST_FIELDS
    ]
    if forbidden_query:
        parameter_errors.append(f"owner/internal query parameter is forbidden: {forbidden_query}")
    if parameter_errors:
        raise ValueError("; ".join(parameter_errors))
    if method == "POST" and not args.idempotency_key:
        raise ValueError("POST requires --idempotency-key")
    if method == "DELETE" and not args.confirm_cancel:
        raise ValueError("DELETE requires --confirm-cancel after explicit user intent")
    body, payload = body_bytes(args.body)
    if method == "POST" and payload is None:
        raise ValueError("POST requires --body")
    if body is not None:
        body_errors = forbidden_request_paths(body)
        schema = request_schema(spec, operation)
        if schema is not None:
            body_errors.extend(validate_json_schema(body, schema, spec))
        if body_errors:
            raise ValueError("request body violates Agent REST contract: " + "; ".join(body_errors))
    headers = {"Accept": "application/json", "X-API-KEY": key}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    if args.idempotency_key:
        headers["Idempotency-Key"] = args.idempotency_key
    http_request = urllib.request.Request(f"{base}{args.path}", data=payload, headers=headers, method=method)
    try:
        response = opener().open(http_request, timeout=args.timeout)
    except urllib.error.HTTPError as error:
        raw = read_limited(error, args.max_response_bytes)
        safe_data, warnings = sanitize_response(parse_body(raw))
        job_status = normalized_job_status(safe_data)
        print(json.dumps({
            "provider": "netease-waimao",
            "providerStatus": semantic_provider_status(safe_data, job_status, error.code),
            "httpStatus": error.code,
            "jobStatus": job_status,
            "diagnosticCodes": diagnostic_codes(safe_data),
            "data": safe_data,
            "warnings": warnings,
        }, ensure_ascii=False, indent=2))
        return 1
    with response:
        raw = read_limited(response, args.max_response_bytes)
        safe_data, warnings = sanitize_response(parse_body(raw))
        job_status = normalized_job_status(safe_data)
        result = {
            "provider": "netease-waimao",
            "providerStatus": semantic_provider_status(safe_data, job_status, response.status),
            "httpStatus": response.status,
            "retryAfter": response.headers.get("Retry-After"),
            "jobStatus": job_status,
            "diagnosticCodes": diagnostic_codes(safe_data),
            "data": safe_data,
            "warnings": warnings,
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
    invoke.add_argument("--max-response-bytes", type=int, default=5_000_000)
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
