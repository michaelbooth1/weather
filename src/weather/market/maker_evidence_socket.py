"""Public websocket-client transport with pre-allocation frame/message bounds."""
from contextlib import contextmanager
import struct

from websocket import ABNF, WebSocket, WebSocketProtocolException, WebSocketTimeoutException
from websocket._abnf import frame_buffer

from weather.market.market_microstructure_constants import CLOB_WS_URL

MAX_MESSAGE_BYTES = 2 * 1024 * 1024
# An empty text/binary frame is inbound liveness, not a close.
EMPTY_DATA_FRAME = object()


class VenueCloseError(ConnectionError):
    """The venue sent a websocket close frame; its code and reason are kept."""

    def __init__(self, code, reason):
        self.code, self.reason = code, reason
        super().__init__(f"venue closed the websocket: code={code} reason={reason!r}")


class BoundedFrameBuffer(frame_buffer):
    def __init__(self, recv_fn, remaining):
        super().__init__(recv_fn, False)
        self.remaining = remaining

    def recv_length(self):
        super().recv_length()
        if self.header[4] in (ABNF.OPCODE_TEXT, ABNF.OPCODE_BINARY, ABNF.OPCODE_CONT):
            if self.length > self.remaining():
                raise WebSocketProtocolException("public message exceeds byte bound")
        elif self.length > 125:
            raise WebSocketProtocolException("oversized public control frame")


class BoundedWebSocket(WebSocket):
    def __init__(self):
        super().__init__(enable_multithread=True)
        self.fragment_bytes = 0
        self.frame_buffer = BoundedFrameBuffer(self._recv, lambda: MAX_MESSAGE_BYTES - self.fragment_bytes)

    def recv_frame(self):
        frame = super().recv_frame()
        if frame.opcode in (ABNF.OPCODE_TEXT, ABNF.OPCODE_BINARY, ABNF.OPCODE_CONT):
            self.fragment_bytes = 0 if frame.fin else self.fragment_bytes + len(frame.data)
        return frame

    def recv(self, timeout=1):
        """One data message; a close frame raises with its code, empty data returns EMPTY_DATA_FRAME.

        ``WebSocket.recv`` returns ``""`` for a close frame and an empty text
        frame alike, which lost the venue's close code.
        """
        self.settimeout(timeout)
        try:
            with self.readlock:
                opcode, data = self.recv_data()
        except WebSocketTimeoutException as exc:
            raise TimeoutError("public receive timeout") from exc
        if opcode == ABNF.OPCODE_CLOSE:
            payload = bytes(data or b"")
            code = struct.unpack("!H", payload[:2])[0] if len(payload) >= 2 else None
            raise VenueCloseError(code, payload[2:].decode("utf-8", errors="replace"))
        if opcode == ABNF.OPCODE_TEXT:
            return (data.decode("utf-8") if isinstance(data, bytes) else data) or EMPTY_DATA_FRAME
        if opcode == ABNF.OPCODE_BINARY:
            return data or EMPTY_DATA_FRAME
        raise ConnectionError("public socket closed")


@contextmanager
def connect(url=CLOB_WS_URL):
    socket = BoundedWebSocket()
    try:
        # Explicit bypass list prevents ambient proxy/auth lookup; no auth headers.
        socket.connect(url, timeout=4, http_no_proxy=["*"],
                       redirect_limit=0, header={"User-Agent": "weather-passive-maker-evidence/2"})
        yield socket
    finally:
        socket.close(timeout=1)
