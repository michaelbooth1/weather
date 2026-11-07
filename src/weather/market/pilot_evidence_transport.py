"""Bounded direct TLS/HTTP and RFC6455 public-market transport.

No proxy, cookie, authentication or redirect layer. DNS is additionally owned
by the supervisor process watchdog, because Python cannot cancel getaddrinfo.
"""
from __future__ import annotations

import base64
import hashlib
import http.client
import os
import socket
import ssl
import struct
import time
from types import SimpleNamespace
from urllib.parse import urlencode

from weather.market.pilot_evidence_contract import MIB, retry_delay


class IdlePoll(TimeoutError):
    """No first byte arrived during the short poll; no framing state consumed."""


class TransportLimit(ValueError):
    pass


class HandshakeError(OSError):
    def __init__(self, status, headers, body, truncated=False):
        super().__init__("public websocket handshake refused")
        self.status, self.headers, self.body, self.truncated = status, headers, body, truncated


class DeadlineSocket:
    def __init__(self, sock, check, deadline, *, clock=time.monotonic):
        self.sock, self.check, self.deadline, self.clock = sock, check, deadline, clock
        self.buffer = bytearray()
        self.sock.settimeout(0.25)

    def exact(self, size, *, idle=False, allow_eof=False):
        if not 0 <= size <= 4 * MIB + 1:
            raise TransportLimit("bounded read size")
        output = bytearray()
        if self.buffer:
            take = min(size, len(self.buffer))
            output.extend(self.buffer[:take])
            del self.buffer[:take]
        while len(output) < size:
            self.check()
            if self.clock() >= self.deadline:
                raise TimeoutError("absolute transport deadline")
            try:
                part = self.sock.recv(min(16384, size - len(output)))
            except (socket.timeout, ssl.SSLWantReadError):
                if idle and not output:
                    raise IdlePoll()
                continue
            if not part:
                if not output or allow_eof:
                    return bytes(output)
                raise ConnectionError("truncated public read")
            output.extend(part)
        return bytes(output)

    def line(self, limit):
        while True:
            newline = self.buffer.find(b"\n")
            if newline >= 0 and newline < limit:
                result = bytes(self.buffer[:newline + 1])
                del self.buffer[:newline + 1]
                return result
            if len(self.buffer) >= limit:
                raise TransportLimit("HTTP line limit")
            self.check()
            if self.clock() >= self.deadline:
                raise TimeoutError("absolute header deadline")
            try:
                raw = self.sock.recv(min(4096, limit - len(self.buffer)))
            except (socket.timeout, ssl.SSLWantReadError):
                continue
            if not raw:
                result = bytes(self.buffer)
                self.buffer.clear()
                return result
            self.buffer.extend(raw)

    def makefile(self, mode):
        return BoundedReader(self)

    def sendall(self, raw):
        view = memoryview(raw)
        while view:
            self.check()
            if self.clock() >= self.deadline:
                raise TimeoutError("absolute send deadline")
            try:
                sent = self.sock.send(view[:16384])
            except (socket.timeout, ssl.SSLWantWriteError):
                continue
            if sent == 0:
                raise ConnectionError("public socket closed")
            view = view[sent:]

    def close(self):
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.sock.close()


class BoundedReader:
    def __init__(self, stream):
        self.stream, self.header_bytes, self.headers_done = stream, 0, False

    def read(self, size=-1):
        if size < 0:
            raise TransportLimit("unbounded HTTP read refused")
        return self.stream.exact(size, allow_eof=True)

    def readline(self, size=-1):
        limit = min(8192, size) if size >= 0 else 8192
        line = self.stream.line(limit)
        if not self.headers_done:
            self.header_bytes += len(line)
            if self.header_bytes > 32768:
                raise TransportLimit("HTTP header limit")
            if line == b"\r\n":
                self.headers_done = True
        return bytes(line)

    def close(self):
        pass  # The transport owner closes the actual socket.


def tls_socket(host, check, *, seconds=8):
    check()
    deadline = time.monotonic() + seconds
    # The outer process watchdog bounds resolution as well as TLS setup.
    raw = socket.create_connection((host, 443), timeout=2)
    try:
        raw.settimeout(max(0.1, min(2, deadline - time.monotonic())))
        secure = ssl.create_default_context().wrap_socket(raw, server_hostname=host)
    except BaseException:
        raw.close()
        raise
    return DeadlineSocket(secure, check, deadline)


def header_cooldown(status, headers, gate, store, kind):
    if status == 429 or 500 <= status <= 599:
        delay = retry_delay(headers.get("Retry-After"), 1)
        gate.defer(delay)
        store.write("response_header_backoff", {"transport": kind, "status": status,
                                               "minimum_seconds": delay})


def http_exchange(method, parts, params, body, *, gate, store, pool=None):
    """One request, no retries. The scheduler can service books before a retry."""
    import json
    stream = pool.pop(parts.hostname, None) if pool is not None else None

    def send():
        nonlocal stream
        store.attempt_started("rest")
        store.begin_operation("rest", 10)
        if stream is None:
            stream = tls_socket(parts.hostname, lambda: store.check(fast=True))
        stream.deadline = time.monotonic() + 8
        path = parts.path + (("?" + urlencode(params)) if params else "")
        encoded = json.dumps(body, separators=(",", ":")).encode() if body is not None else b""
        headers = [f"{method} {path} HTTP/1.1", f"Host: {parts.hostname}",
                   "Accept: application/json", "User-Agent: weather-public-evidence/2", "Connection: keep-alive"]
        if body is not None:
            headers += ["Content-Type: application/json", f"Content-Length: {len(encoded)}"]
        store.network_started("rest")
        stream.sendall(("\r\n".join(headers) + "\r\n\r\n").encode() + encoded)

    try:
        gate.start(send)
        response = http.client.HTTPResponse(stream)
        response.begin()
        headers = {k: response.getheader(k) for k in ("Date", "Retry-After", "Content-Type",
                                                    "Content-Length", "Transfer-Encoding", "Content-Encoding")}
        header_cooldown(response.status, headers, gate, store, "rest")
        raw = response.read(4 * MIB + 1)
        if len(raw) <= 4 * MIB and getattr(response, "length", 0) not in (0, None):
            store.raw("http_incomplete_response", raw, parse=False, status=response.status,
                      response_headers=headers, missing_bytes=response.length, body_complete=False)
            raise http.client.IncompleteRead(raw, response.length)
        if pool is not None and not response.will_close and len(raw) <= 4 * MIB:
            pool[parts.hostname] = stream
            stream = None
        return response.status, headers, raw
    finally:
        store.end_operation("rest")
        if stream is not None:
            stream.close()


class BoundedWebSocket:
    """Limits advertised frame length and logical messages before allocation."""
    def __init__(self, stream, *, max_size=MIB):
        self.stream, self.max_size = stream, max_size
        self.fragments = bytearray()
        self.fragment_opcode = None

    def recv_frame(self):
        self.stream.deadline = time.monotonic() + 5
        first = self.stream.exact(2, idle=True)
        if len(first) != 2:
            raise ConnectionError("public stream closed")
        fin, rsv, opcode = first[0] >> 7, (first[0] >> 4) & 7, first[0] & 15
        masked, length = first[1] >> 7, first[1] & 127
        if masked or rsv or opcode not in (0, 1, 2, 8, 9, 10):
            raise ValueError("unsupported server framing")
        if length == 126:
            length = struct.unpack("!H", self.stream.exact(2))[0]
        elif length == 127:
            length = struct.unpack("!Q", self.stream.exact(8))[0]
        if length > self.max_size or (opcode >= 8 and (length > 125 or not fin)):
            raise TransportLimit("socket_frame_cap")
        if opcode < 8 and len(self.fragments) + length > self.max_size:
            raise TransportLimit("socket_message_cap")
        raw = self.stream.exact(length)
        if len(raw) != length:
            raise ConnectionError("truncated frame")
        return SimpleNamespace(fin=fin, rsv1=0, rsv2=0, rsv3=0, opcode=opcode, data=raw)

    def message(self, frame):
        if frame.opcode >= 8:
            return None
        if frame.opcode in (1, 2):
            if self.fragment_opcode is not None:
                raise ValueError("interleaved data message")
            self.fragment_opcode = frame.opcode
        elif self.fragment_opcode is None:
            raise ValueError("unexpected continuation")
        if len(self.fragments) + len(frame.data) > self.max_size:
            raise TransportLimit("socket_message_cap")
        self.fragments.extend(frame.data)
        if not frame.fin:
            return None
        result = bytes(self.fragments)
        self.fragments.clear()
        self.fragment_opcode = None
        return result

    def send(self, data, *, opcode=1):
        raw = data.encode() if isinstance(data, str) else data
        if len(raw) > 32768:
            raise TransportLimit("socket_send_cap")
        mask = os.urandom(4)
        length = len(raw)
        head = bytes((128 | opcode, 128 | length)) if length < 126 else bytes((128 | opcode, 254)) + struct.pack("!H", length)
        encoded = bytes(value ^ mask[i % 4] for i, value in enumerate(raw))
        self.stream.deadline = time.monotonic() + 3
        self.stream.sendall(head + mask + encoded)

    def pong(self, raw):
        self.send(raw, opcode=10)

    def close(self, timeout=1):
        self.stream.close()  # No blocking close handshake on a stop path.


def socket_exchange(parts, *, gate, store, max_size=MIB):
    stream = None
    key = base64.b64encode(os.urandom(16)).decode()

    def send():
        nonlocal stream
        store.attempt_started("ws_connect")
        store.begin_operation("ws_handshake", 10)
        stream = tls_socket(parts.hostname, lambda: store.check(fast=True))
        request = (f"GET {parts.path} HTTP/1.1\r\nHost: {parts.hostname}\r\nUpgrade: websocket\r\n"
                   f"Connection: Upgrade\r\nOrigin: https://{parts.hostname}\r\n"
                   f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n")
        store.network_started("ws_handshake")
        stream.sendall(request.encode())

    try:
        gate.start(send)
        response = http.client.HTTPResponse(stream)
        response.begin()
        headers = {k: response.getheader(k) for k in ("Date", "Retry-After", "Content-Type")}
        header_cooldown(response.status, headers, gate, store, "websocket")
        if response.status != 101:
            raw = response.read(16385)
            raise HandshakeError(response.status, headers, raw[:16384], len(raw) > 16384)
        expected = base64.b64encode(hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()).decode()
        if (response.getheader("Sec-WebSocket-Accept") != expected or
                response.getheader("Upgrade", "").lower() != "websocket" or
                "upgrade" not in response.getheader("Connection", "").lower()):
            raise ValueError("public websocket upgrade binding")
        store.write("ws_handshake_response", {"status": 101, "response_headers": headers,
                                      "transport_start": store.last_network_stamp.get("ws_handshake")})
        return BoundedWebSocket(stream, max_size=max_size)
    except BaseException:
        if stream is not None:
            stream.close()
        raise
    finally:
        store.end_operation("ws_handshake")
