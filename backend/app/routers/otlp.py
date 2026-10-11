"""OTLP/HTTP trace ingest — accept OpenTelemetry spans without the CortexOps SDK.

Point any OTLP/HTTP exporter at the base URL `https://api.getcortexops.com/v1/otlp`
(exporters append `/v1/traces`). Both `application/x-protobuf` and `application/json`
bodies are accepted, optionally gzip-compressed.

Auth: `X-API-Key: cxo-...` or `Authorization: Bearer cxo-...` (the form most OTel
exporters send via OTEL_EXPORTER_OTLP_HEADERS). Dashboard JWTs also work as Bearer tokens.
"""
from __future__ import annotations

import dataclasses
import json
import logging
import time
import uuid
import zlib
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, Security
from fastapi.security import HTTPAuthorizationCredentials
from google.protobuf.json_format import MessageToJson
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceResponse
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import _api_key_header, _bearer, get_current_key_info
from ..db import get_db
from ..models.records import TraceRecord
from ..models.schemas import TraceIngest
from ..services.otlp import (
    OTelSpan,
    OTLPDecodeError,
    build_trace_payload,
    decode_export_request,
    group_by_trace,
    resource_project,
    trace_record_id,
)
from ..services.trace_store import authorize_trace_write, persist_trace, redact_trace_payload
from ..tiers import TierInfo, require_project_access, require_scope

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/otlp", tags=["otlp"])

MAX_OTLP_BODY_BYTES = 8 * 1024 * 1024  # after decompression; each stored trace is still capped at 128KB

_PROTOBUF_TYPES = {"application/x-protobuf", "application/protobuf"}
_JSON_TYPES = {"application/json"}
# google.rpc.Code values for the Status body OTLP expects on errors
_GRPC_CODES = {400: 3, 401: 16, 403: 7, 404: 5, 413: 3, 415: 3, 429: 8, 503: 14}
# When every trace in a request is rejected, surface the most actionable status
_STATUS_PRIORITY = (429, 403, 413, 400)


async def get_otlp_key_info(
    raw_key: str | None = Security(_api_key_header),
    credentials: HTTPAuthorizationCredentials | None = Security(_bearer),
    db: AsyncSession = Depends(get_db),
) -> TierInfo:
    """Same checks as `get_current_key_info`, but a Bearer token that is not a JWT is treated as an API key."""
    token = credentials.credentials if credentials else ""
    if token and token.count(".") != 2:
        return await get_current_key_info(token, None, db)
    return await get_current_key_info(raw_key, credentials, db)


class _OTLPError(Exception):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def _encoding(content_type: str | None) -> str:
    media_type = (content_type or "").split(";")[0].strip().lower()
    if media_type in _PROTOBUF_TYPES:
        return "protobuf"
    if media_type in _JSON_TYPES:
        return "json"
    raise _OTLPError(415, "Content-Type must be application/x-protobuf or application/json")


async def _read_body(request: Request) -> bytes:
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_OTLP_BODY_BYTES:
        raise _OTLPError(413, f"Request body exceeds {MAX_OTLP_BODY_BYTES} bytes")
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_OTLP_BODY_BYTES:
            raise _OTLPError(413, f"Request body exceeds {MAX_OTLP_BODY_BYTES} bytes")
        chunks.append(chunk)
    body = b"".join(chunks)

    content_encoding = request.headers.get("content-encoding", "").strip().lower()
    if content_encoding in ("", "identity"):
        return body
    if content_encoding != "gzip":
        raise _OTLPError(415, "Content-Encoding must be gzip or identity")
    decompressor = zlib.decompressobj(16 + zlib.MAX_WBITS)
    try:
        data = decompressor.decompress(body, MAX_OTLP_BODY_BYTES + 1)
    except zlib.error as exc:
        raise _OTLPError(400, "Body is not valid gzip") from exc
    if len(data) > MAX_OTLP_BODY_BYTES or decompressor.unconsumed_tail:
        raise _OTLPError(413, f"Decompressed body exceeds {MAX_OTLP_BODY_BYTES} bytes")
    return data


def _varint(value: int) -> bytes:
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        out.append(byte | 0x80 if value else byte)
        if not value:
            return bytes(out)


def _status_response(encoding: str, status_code: int, message: str) -> Response:
    """Error body as a google.rpc.Status message, encoded like the request (OTLP/HTTP spec)."""
    code = _GRPC_CODES.get(status_code, 2)
    if encoding == "protobuf":
        text = message.encode()
        body = b"\x08" + _varint(code) + b"\x12" + _varint(len(text)) + text
        return Response(body, status_code=status_code, media_type="application/x-protobuf")
    return Response(json.dumps({"code": code, "message": message}), status_code=status_code,
                    media_type="application/json")


def _export_response(encoding: str, rejected_spans: int, message: str) -> Response:
    msg = ExportTraceServiceResponse()
    if rejected_spans:
        msg.partial_success.rejected_spans = rejected_spans
        msg.partial_success.error_message = message
    if encoding == "protobuf":
        return Response(msg.SerializeToString(), media_type="application/x-protobuf")
    return Response(MessageToJson(msg, indent=None), media_type="application/json")


def _can_write(tier_info: TierInfo, project: str) -> bool:
    try:
        require_project_access(tier_info, project)
    except HTTPException:
        return False
    return True


def _resolve_project(tier_info: TierInfo, spans: list[OTelSpan]) -> str:
    """Resource `cortexops.project`, else `service.name` when the key may write to it, else the key's project.

    An explicit `cortexops.project` the key cannot access is rejected. `service.name` is only a
    hint: OTel SDKs always set it (default `unknown_service:<lang>`), so a mismatch falls back
    to the key's own project instead of rejecting every span.
    """
    explicit, service_name = resource_project(spans)
    if explicit:
        project = explicit
    elif service_name and not service_name.startswith("unknown_service") and _can_write(tier_info, service_name):
        project = service_name
    else:
        project = tier_info.project
    if len(project) > 255:
        raise HTTPException(status_code=400, detail="Project name exceeds 255 characters")
    authorize_trace_write(tier_info, project)
    return project


_ID_FIELDS = ("node_id", "span_id", "parent_span_id")


def _redact_keeping_ids(payload: dict[str, Any]) -> dict[str, Any]:
    """PII redaction, then restore span ids (validated hex) that the digit patterns may have rewritten."""
    safe = redact_trace_payload(payload)
    for node, safe_node in zip(payload.get("nodes", []), safe.get("nodes", []), strict=True):
        for key in _ID_FIELDS:
            if key in node:
                safe_node[key] = node[key]
        for tool, safe_tool in zip(node.get("tool_calls", []), safe_node.get("tool_calls", []), strict=True):
            for key in _ID_FIELDS:
                if key in tool:
                    safe_tool[key] = tool[key]
    otel, safe_otel = payload["metadata"]["otel"], safe["metadata"]["otel"]
    safe_otel["trace_id"] = otel["trace_id"]
    if otel.get("root"):
        safe_otel["root"]["span_id"] = otel["root"]["span_id"]
    return safe


def _http_message(exc: HTTPException) -> str:
    detail = exc.detail
    if isinstance(detail, dict):
        return str(detail.get("message") or detail.get("error") or detail)
    return str(detail)


async def _ingest_trace(
    db: AsyncSession, tier_info: TierInfo, trace_id: str, spans: list[OTelSpan], new_traces: int,
) -> bool:
    """Store or merge one OTel trace. Returns True when a new CortexOps trace was created."""
    project = _resolve_project(tier_info, spans)
    record_id = trace_record_id(trace_id)
    existing = await db.get(TraceRecord, record_id)
    if existing is not None and existing.project != project:
        existing, record_id = None, str(uuid.uuid4())
    previous: dict[str, Any] | None = None
    if existing is not None:
        try:
            previous = json.loads(existing.raw_trace)
        except ValueError:
            previous = None

    payload = build_trace_payload(trace_id, spans, project, previous)
    try:
        body = TraceIngest(**payload)
    except ValidationError as exc:
        fields = ", ".join(".".join(str(p) for p in err["loc"]) for err in exc.errors())
        raise HTTPException(status_code=400, detail=f"Invalid trace fields: {fields}") from exc

    quota_view = dataclasses.replace(tier_info, monthly_traces=tier_info.monthly_traces + new_traces)
    await persist_trace(db, quota_view, body, existing=existing, record_id=record_id, redact=_redact_keeping_ids)
    return existing is None


@router.post("/v1/traces", status_code=200, responses={
    200: {"description": "ExportTraceServiceResponse; partialSuccess lists rejected spans"},
    400: {"description": "Malformed OTLP payload"},
    401: {"description": "Invalid or missing API key"},
    403: {"description": "Forbidden — insufficient scope or project mismatch"},
    413: {"description": "Body over 8MB, or every trace over the 128KB per-trace limit"},
    415: {"description": "Unsupported Content-Type or Content-Encoding"},
    429: {"description": "Rate limit or monthly trace quota exceeded"},
    503: {"description": "Concurrent write to the same trace; retry"},
})
async def export_traces(
    request: Request,
    db: AsyncSession = Depends(get_db),
    tier_info: TierInfo = Depends(get_otlp_key_info),
) -> Response:
    """OTLP/HTTP ExportTraceServiceRequest. One OTel trace becomes one CortexOps trace."""
    t0 = time.perf_counter()
    encoding = "json"
    try:
        encoding = _encoding(request.headers.get("content-type"))
        try:
            require_scope(tier_info, "read_write")
        except HTTPException as exc:
            raise _OTLPError(exc.status_code, _http_message(exc)) from exc
        body = await _read_body(request)
        try:
            spans, invalid_spans = decode_export_request(body, encoding)
        except OTLPDecodeError as exc:
            raise _OTLPError(400, str(exc)) from exc
    except _OTLPError as exc:
        await db.rollback()
        return _status_response(encoding, exc.status_code, exc.message)

    rejected_spans = invalid_spans
    failures: list[tuple[int, str]] = []
    if invalid_spans:
        failures.append((400, f"{invalid_spans} span(s) with missing or malformed trace/span ids"))
    stored = new_traces = 0
    for trace_id, trace_spans in group_by_trace(spans).items():
        try:
            if await _ingest_trace(db, tier_info, trace_id, trace_spans, new_traces):
                new_traces += 1
            stored += 1
        except HTTPException as exc:
            rejected_spans += len(trace_spans)
            failures.append((exc.status_code, f"trace {trace_id}: {_http_message(exc)}"))
        except IntegrityError:
            await db.rollback()
            return _status_response(encoding, 503, "Concurrent write to the same trace; retry the export")

    message = "; ".join(m for _, m in failures[:5])
    if failures and stored == 0:
        await db.rollback()
        statuses = {code for code, _ in failures}
        status_code = next((c for c in _STATUS_PRIORITY if c in statuses), failures[0][0])
        return _status_response(encoding, status_code, message)

    logger.debug(
        "op=otlp_export duration_ms=%.2f spans=%d stored_traces=%d new_traces=%d rejected_spans=%d",
        (time.perf_counter() - t0) * 1000, len(spans), stored, new_traces, rejected_spans,
    )
    return _export_response(encoding, rejected_spans, message)
