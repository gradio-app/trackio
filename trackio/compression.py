from __future__ import annotations

import gzip
import io
from typing import NoReturn

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

try:
    import brotli

    HAS_BROTLI = True
except ImportError:
    brotli = None
    HAS_BROTLI = False

COMPRESSIBLE_CONTENT_TYPES = (
    "application/json",
    "application/javascript",
    "application/manifest+json",
    "application/xml",
    "application/xhtml+xml",
    "image/svg+xml",
    "text/",
)


class CompressionMiddleware:
    """Negotiates Brotli, then gzip, then identity based on Accept-Encoding.

    Only text-like content types are compressed, so already-compressed media
    (images, audio, video) and zero-copy file sends pass through untouched.
    """

    def __init__(
        self,
        app: ASGIApp,
        minimum_size: int = 512,
        gzip_level: int = 6,
        brotli_quality: int = 5,
    ) -> None:
        self.app = app
        self.minimum_size = minimum_size
        self.gzip_level = gzip_level
        self.brotli_quality = brotli_quality

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        accept_encoding = Headers(scope=scope).get("Accept-Encoding", "")
        responder: _CompressionResponder
        if HAS_BROTLI and "br" in accept_encoding:
            responder = _BrotliResponder(
                self.app, self.minimum_size, self.brotli_quality
            )
        elif "gzip" in accept_encoding:
            responder = _GZipResponder(self.app, self.minimum_size, self.gzip_level)
        else:
            responder = _CompressionResponder(self.app, self.minimum_size)

        await responder(scope, receive, send)


class _CompressionResponder:
    content_encoding: str = ""

    def __init__(self, app: ASGIApp, minimum_size: int) -> None:
        self.app = app
        self.minimum_size = minimum_size
        self.send: Send = _unattached_send
        self.initial_message: Message = {}
        self.started = False
        self.passthrough = True

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        self.send = send
        await self.app(scope, receive, self.send_with_compression)

    async def send_with_compression(self, message: Message) -> None:
        message_type = message["type"]
        if message_type == "http.response.start":
            self.initial_message = message
            headers = Headers(raw=message["headers"])
            content_type = headers.get("content-type", "")
            already_encoded = "content-encoding" in headers
            self.passthrough = already_encoded or not content_type.startswith(
                COMPRESSIBLE_CONTENT_TYPES
            )
        elif message_type == "http.response.body" and self.passthrough:
            if not self.started:
                self.started = True
                await self.send(self.initial_message)
            await self.send(message)
        elif message_type == "http.response.body" and not self.started:
            self.started = True
            body = message.get("body", b"")
            more_body = message.get("more_body", False)
            if len(body) < self.minimum_size and not more_body:
                await self.send(self.initial_message)
                await self.send(message)
            else:
                compressed = self.apply_compression(body, more_body=more_body)
                headers = MutableHeaders(raw=self.initial_message["headers"])
                headers.add_vary_header("Accept-Encoding")
                if compressed != body:
                    headers["Content-Encoding"] = self.content_encoding
                    if more_body:
                        del headers["Content-Length"]
                    else:
                        headers["Content-Length"] = str(len(compressed))
                    message["body"] = compressed
                await self.send(self.initial_message)
                await self.send(message)
        elif message_type == "http.response.body":
            body = message.get("body", b"")
            more_body = message.get("more_body", False)
            message["body"] = self.apply_compression(body, more_body=more_body)
            await self.send(message)
        elif message_type == "http.response.pathsend":
            await self.send(self.initial_message)
            await self.send(message)

    def apply_compression(self, body: bytes, *, more_body: bool) -> bytes:
        return body


class _GZipResponder(_CompressionResponder):
    content_encoding = "gzip"

    def __init__(self, app: ASGIApp, minimum_size: int, compresslevel: int) -> None:
        super().__init__(app, minimum_size)
        self.buffer = io.BytesIO()
        self.file = gzip.GzipFile(
            mode="wb", fileobj=self.buffer, compresslevel=compresslevel
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        with self.buffer, self.file:
            await super().__call__(scope, receive, send)

    def apply_compression(self, body: bytes, *, more_body: bool) -> bytes:
        self.file.write(body)
        if not more_body:
            self.file.close()
        data = self.buffer.getvalue()
        self.buffer.seek(0)
        self.buffer.truncate()
        return data


class _BrotliResponder(_CompressionResponder):
    content_encoding = "br"

    def __init__(self, app: ASGIApp, minimum_size: int, quality: int) -> None:
        super().__init__(app, minimum_size)
        self.compressor = brotli.Compressor(quality=quality)

    def apply_compression(self, body: bytes, *, more_body: bool) -> bytes:
        data = self.compressor.process(body)
        if not more_body:
            data += self.compressor.finish()
        return data


async def _unattached_send(message: Message) -> NoReturn:
    raise RuntimeError("send awaitable not set")
