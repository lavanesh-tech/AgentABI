"""Request body size limit (Security Phase D spec §14) — raw ASGI
middleware, not `BaseHTTPMiddleware`. `BaseHTTPMiddleware` would have to
read the whole body into memory to inspect it, which is exactly the cost
a size limit exists to avoid, and would also replace the body stream —
breaking Phase E's planned webhook HMAC verification, which needs the
exact raw bytes as GitHub sent them. This middleware only counts bytes of
each `http.request` chunk as it streams through `receive()`; it never
buffers, rewrites, or consumes more of the body than the framework itself
already requests, so the raw stream remains verifiable downstream.

A `Content-Length` header over the limit is rejected immediately, before
any body is read at all — the common case, and the cheapest to reject.
Without one (chunked transfer), the streaming counter is the enforcement
path.
"""

import json
import uuid

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import Settings


def _too_large_response(request_id: str) -> tuple[Message, bytes]:
    body = json.dumps(
        {
            "error": {
                "code": "REQUEST_TOO_LARGE",
                "message": "Request body exceeds the maximum allowed size",
                "request_id": request_id,
            }
        }
    ).encode("utf-8")
    return {
        "type": "http.response.start",
        "status": 413,
        "headers": [(b"content-type", b"application/json")],
    }, body


class RequestSizeLimitMiddleware:
    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        self._app = app
        self._max_bytes = settings.max_request_body_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        request_id = str(uuid.uuid4())
        headers = dict(scope.get("headers", []))
        content_length = headers.get(b"content-length")
        if content_length is not None:
            try:
                if int(content_length) > self._max_bytes:
                    await self._send_413(send, request_id)
                    return
            except ValueError:
                pass  # malformed header — let downstream validation handle it

        total = 0

        # Wraps receive() so each streamed body chunk is counted as the
        # app reads it — no buffering beyond what the app already
        # requests. The threshold is only knowable once enough chunks
        # have streamed through (no Content-Length, or a lying one), so
        # this raises from inside the app's own body-reading loop rather
        # than pre-computing anything.
        async def _receive_with_limit() -> Message:
            nonlocal total
            message = await receive()
            if message["type"] == "http.request":
                total += len(message.get("body", b""))
                if total > self._max_bytes:
                    raise _RequestTooLarge()
            return message

        try:
            await self._app(scope, _receive_with_limit, send)
        except _RequestTooLarge:
            await self._send_413(send, request_id)

    async def _send_413(self, send: Send, request_id: str) -> None:
        start_message, body = _too_large_response(request_id)
        await send(start_message)
        await send({"type": "http.response.body", "body": body})


class _RequestTooLarge(Exception):
    """Internal signal only — never escapes this module."""
