"""Bounded stdio and local Streamable HTTP MCP transports (no public listener)."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import json
import threading
import time
import uuid

from .bridge import PROTOCOLS, Session

MAX_MESSAGE = 1024 * 1024


def parse_error():
    return {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}


def stdio(input_stream, output_stream, state_dir=None):
    session = Session(state_dir)
    try:
        while True:
            raw = input_stream.readline(MAX_MESSAGE + 1)
            if not raw:
                break
            if len(raw) > MAX_MESSAGE:
                raise ValueError("MCP input exceeds 1 MiB; closing session")
            try:
                result = session.handle(json.loads(raw))
            except (ValueError, UnicodeError):
                result = parse_error()
            if result is not None:
                output_stream.write((json.dumps(result, ensure_ascii=False) + "\n").encode("utf-8"))
                output_stream.flush()
    finally:
        session.close()


class HTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, token, state_dir=None):
        if address[0] != "127.0.0.1":
            raise ValueError("HTTP bridge binds only to 127.0.0.1; use an authenticated local tunnel")
        if not isinstance(token, str) or len(token) < 32 or not token.isascii() or any(c.isspace() for c in token):
            raise ValueError("HTTP requires a private bearer token of at least 32 ASCII characters")
        self.token, self.state_dir = token, state_dir
        self.sessions, self.sessions_lock = {}, threading.RLock()
        self.workers = threading.BoundedSemaphore(16)
        super().__init__(address, Handler)

    def process_request(self, request, client_address):
        if not self.workers.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.workers.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.workers.release()

    def server_close(self):
        super().server_close()
        with self.sessions_lock:
            entries = list(self.sessions.values())
            self.sessions.clear()
        for session, lock, _ in entries:
            with lock:
                session.close()  # Normal shutdown must not leave crash-style leases.

    def session(self, sid):
        with self.sessions_lock:
            entry = self.sessions.get(sid)
            if entry and time.monotonic() - entry[2] <= 3600:
                entry[2] = time.monotonic()
                return entry
        return None

    def create_session(self):
        with self.sessions_lock:
            # Expired owners retain only time-limited database leases until next cleanup.
            for key, entry in list(self.sessions.items()):
                if time.monotonic() - entry[2] > 3600 and entry[1].acquire(blocking=False):
                    try:
                        entry[0].close()
                        del self.sessions[key]
                    finally:
                        entry[1].release()
            if len(self.sessions) >= 128:
                return None, None
            sid = str(uuid.uuid4())
            entry = [Session(self.state_dir), threading.RLock(), time.monotonic()]
            self.sessions[sid] = entry
            return sid, entry


class Handler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(15)

    def log_message(self, *args):
        pass  # Never log authorization headers, request bodies or project data.

    def reply(self, status, value=None, sid=None):
        raw = json.dumps(value, ensure_ascii=False).encode("utf-8") if value is not None else b""
        self.send_response(status)
        self.send_header("Content-Length", str(len(raw)))
        if raw:
            self.send_header("Content-Type", "application/json")
        if sid:
            self.send_header("Mcp-Session-Id", sid)
        self.end_headers()
        if raw:
            self.wfile.write(raw)

    def authorize(self):
        port = self.server.server_port
        hosts = {"127.0.0.1:" + str(port), "localhost:" + str(port)}
        if self.headers.get("Host") not in hosts:
            self.reply(403)
            return False
        origin = self.headers.get("Origin")
        if origin and origin not in {"http://" + host for host in hosts}:
            self.reply(403)
            return False
        supplied = self.headers.get("Authorization", "")
        if not hmac.compare_digest(supplied.encode(), ("Bearer " + self.server.token).encode()):
            self.reply(401)
            return False
        if self.path != "/mcp":
            self.reply(404)
            return False
        return True

    def do_GET(self):
        if self.authorize():
            self.reply(405)  # No asynchronous event stream is offered.

    def do_DELETE(self):
        if not self.authorize():
            return
        sid = self.headers.get("Mcp-Session-Id")
        entry = self.server.session(sid)
        if not entry:
            self.reply(404)
            return
        with entry[1]:
            entry[0].close()
            with self.server.sessions_lock:
                self.server.sessions.pop(sid, None)
        self.reply(204)

    def do_POST(self):
        if not self.authorize():
            return
        if self.headers.get_content_type() != "application/json":
            self.reply(415)
            return
        accept = self.headers.get("Accept", "")
        if "application/json" not in accept or "text/event-stream" not in accept:
            self.reply(406)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= MAX_MESSAGE or self.headers.get("Transfer-Encoding"):
                self.reply(413)
                return
            raw = self.rfile.read(length)
            if len(raw) != length:
                self.reply(400, parse_error())
                return
            message = json.loads(raw)
        except (ValueError, UnicodeError):
            self.reply(400, parse_error())
            return
        sid = self.headers.get("Mcp-Session-Id")
        new = False
        if isinstance(message, dict) and message.get("method") == "initialize" and not sid:
            sid, entry = self.server.create_session()
            new = True
            if not entry:
                self.reply(503)
                return
        else:
            entry = self.server.session(sid)
            if not entry:
                self.reply(404)
                return
            protocol = self.headers.get("MCP-Protocol-Version", "2025-03-26")
            if protocol not in PROTOCOLS or protocol != entry[0].protocol:
                self.reply(400)
                return
        with entry[1]:
            if not new and self.server.session(sid) is not entry:
                self.reply(404)
                return
            result = entry[0].handle(message)
            if new and (result is None or "error" in result):
                with self.server.sessions_lock:
                    self.server.sessions.pop(sid, None)
                self.reply(400, result)
            else:
                self.reply(202 if result is None else 200, result, sid if new else None)
