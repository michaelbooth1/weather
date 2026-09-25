"""Public websocket-client transport with pre-allocation frame/message bounds."""
from contextlib import contextmanager

from websocket import ABNF, WebSocket, WebSocketProtocolException, WebSocketTimeoutException
from websocket._abnf import frame_buffer

from weather.market.market_microstructure_constants import CLOB_WS_URL

MAX_MESSAGE_BYTES = 2 * 1024 * 1024


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
        self.settimeout(timeout)
        try:
            message = super().recv()
        except WebSocketTimeoutException as exc:
            raise TimeoutError("public receive timeout") from exc
        if message in ("", b""):
            raise ConnectionError("public socket closed")
        return message


@contextmanager
def connect():
    socket = BoundedWebSocket()
    try:
        # Explicit bypass list prevents ambient proxy/auth lookup; no auth headers.
        socket.connect(CLOB_WS_URL, timeout=4, http_no_proxy=["*"],
                       redirect_limit=0, header={"User-Agent": "weather-passive-maker-evidence/2"})
        yield socket
    finally:
        socket.close(timeout=1)
