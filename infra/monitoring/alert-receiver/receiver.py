"""Minimal notification sink standing in for Slack/PagerDuty.

POST /alerts    Alertmanager webhook payloads
POST /events    pipeline events sent by Jenkins (e.g. build failed)
GET  /alerts    JSON list of received notifications (used by the pipeline to verify alerting)
GET  /          human-readable feed for the demo
"""
import html
import json
import logging
from collections import deque
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
LOG = logging.getLogger("alert-receiver")
FEED = deque(maxlen=500)


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, content_type="application/json"):
        data = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return self._send(400, '{"error": "invalid json"}')

        if self.path.startswith("/alerts"):
            for alert in payload.get("alerts", []):
                entry = {
                    "received": _now(),
                    "kind": "alert",
                    "status": alert.get("status"),
                    "name": alert.get("labels", {}).get("alertname"),
                    "severity": alert.get("labels", {}).get("severity"),
                    "summary": alert.get("annotations", {}).get("summary"),
                    "startsAt": alert.get("startsAt"),
                }
                FEED.appendleft(entry)
                LOG.info("ALERT %-8s %-28s %s", entry["status"], entry["name"], entry["summary"])
        elif self.path.startswith("/events"):
            entry = {"received": _now(), "kind": "event", **payload}
            FEED.appendleft(entry)
            LOG.info("EVENT %s", json.dumps(payload))
        else:
            return self._send(404, '{"error": "not found"}')
        return self._send(200, '{"ok": true}')

    def do_GET(self):  # noqa: N802
        if self.path.startswith("/alerts"):
            return self._send(200, json.dumps(list(FEED)))
        if self.path.startswith("/health"):
            return self._send(200, '{"status": "ok"}')
        rows = "".join(
            "<tr><td>{}</td><td>{}</td><td class='{}'>{}</td><td>{}</td><td>{}</td></tr>".format(
                html.escape(e["received"]), html.escape(e["kind"]),
                html.escape(str(e.get("status", ""))), html.escape(str(e.get("status", ""))),
                html.escape(str(e.get("name") or e.get("event", ""))),
                html.escape(str(e.get("summary") or e.get("message", ""))),
            )
            for e in FEED
        ) or "<tr><td colspan=5>No notifications yet.</td></tr>"
        page = f"""<!doctype html><meta charset=utf-8><meta http-equiv=refresh content=5>
<title>Shelf alerts</title>
<style>body{{font:15px system-ui;margin:32px;color:#1c1b19}}table{{border-collapse:collapse;width:100%}}
td,th{{padding:8px 12px;border-bottom:1px solid #e7e3dc;text-align:left}}
.firing{{color:#a3322b;font-weight:600}}.resolved{{color:#2f6b3f;font-weight:600}}</style>
<h1>Shelf on-call feed</h1><p>Alertmanager and Jenkins notifications (auto-refreshes).</p>
<table><tr><th>Received</th><th>Kind</th><th>Status</th><th>Name</th><th>Summary</th></tr>{rows}</table>"""
        return self._send(200, page, "text/html; charset=utf-8")

    def log_message(self, fmt, *args):
        pass


if __name__ == "__main__":
    LOG.info("alert-receiver listening on :5055")
    ThreadingHTTPServer(("0.0.0.0", 5055), Handler).serve_forever()  # nosec B104 - container-only
