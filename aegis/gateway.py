"""Authenticate before consuming request bodies. Bound request memory and concurrency."""
import asyncio
import hashlib
import hmac
import re

from starlette.datastructures import Headers
from starlette.responses import JSONResponse

MAX_PDF = 4 * 1024 * 1024
MAX_UPLOAD = MAX_PDF + 8192


class Gateway:
    def __init__(self, app, keys):
        self.app = app
        if not isinstance(keys, dict) or not keys:
            raise ValueError("Define AEGIS_KEYS using the setup script.")
        self.keys = {}
        for owner, key in keys.items():
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", owner) or not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", key):
                raise ValueError("Invalid owner or key format.")
            digest = hashlib.sha256(key.encode()).digest()
            if digest in self.keys:
                raise ValueError("Each owner needs a unique key.")
            self.keys[digest] = owner
        self.active = 0

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = Headers(scope=scope)

        async def reply(code, detail):
            extra = {"Cache-Control": "no-store"}
            if code == 401:
                extra["WWW-Authenticate"] = "Bearer"
            await JSONResponse({"detail": detail}, code, headers=extra)(scope, receive, send)

        public = scope["method"] == "GET" and scope["path"] in {
            "/", "/workspace.css", "/workspace.js", "/api/v1/health/live"}
        if not public:
            auth = headers.getlist("authorization")
            token = auth[0].split(" ", 1) if len(auth) == 1 else []
            if len(token) != 2 or token[0].lower() != "bearer" or len(token[1]) > 128:
                return await reply(401, "Authentication required")
            digest = hashlib.sha256(token[1].encode()).digest()
            owner = next((v for k, v in self.keys.items() if hmac.compare_digest(k, digest)), None)
            if owner is None:
                return await reply(401, "Authentication required")
            scope.setdefault("state", {})["owner"] = owner

        if self.active >= 4:
            return await reply(429, "Service busy")
        self.active += 1
        try:
            if scope["method"] == "POST":
                limit = MAX_UPLOAD if scope["path"] == "/api/v1/documents" else 8192
                length = headers.get("content-length")
                if length is not None and (not length.isascii() or not length.isdigit() or len(length) > 12):
                    return await reply(400, "Invalid request size")
                if length and int(length) > limit:
                    return await reply(413, "Request too large")
                body = bytearray()
                try:
                    async with asyncio.timeout(20):
                        while True:
                            message = await receive()
                            if message["type"] == "http.disconnect":
                                return
                            chunk = message.get("body", b"")
                            if len(body) + len(chunk) > limit:
                                return await reply(413, "Request too large")
                            body.extend(chunk)
                            if not message.get("more_body", False):
                                break
                except TimeoutError:
                    return await reply(408, "Upload timed out")
                consumed = False

                async def buffered_receive():
                    nonlocal consumed
                    if consumed:
                        return await receive()
                    consumed = True
                    return {"type": "http.request", "body": bytes(body), "more_body": False}
            else:
                buffered_receive = receive
            async def private_send(message):
                if message["type"] == "http.response.start":
                    message.setdefault("headers", []).extend([
                        (b"cache-control", b"no-store"), (b"x-content-type-options", b"nosniff")])
                await send(message)
            await self.app(scope, buffered_receive, private_send)
        finally:
            self.active -= 1
