#!/usr/bin/env python3
"""Verify the monitoring stack is watching production, and record the release in Grafana.

Checks: Prometheus ready, production target UP and scraped, alert rules loaded,
Alertmanager ready, Grafana healthy; then posts a "release" annotation to the dashboard.
Env: PROMETHEUS_URL, ALERTMANAGER_URL, GRAFANA_URL, GRAFANA_PASSWORD, RELEASE_VERSION
"""
import base64
import json
import os
import sys
import time
import urllib.parse
import urllib.request

PROM = os.environ.get("PROMETHEUS_URL", "http://prometheus:9090")
AM = os.environ.get("ALERTMANAGER_URL", "http://alertmanager:9093")
GRAFANA = os.environ.get("GRAFANA_URL", "http://grafana:3000")
GRAFANA_PASSWORD = os.environ.get("GRAFANA_PASSWORD", "admin")
VERSION = os.environ.get("RELEASE_VERSION", "unknown")
REPORT = os.environ.get("MONITORING_REPORT", "reports/monitoring-check.json")


def get_json(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=10) as res:
        return json.loads(res.read().decode())


def query(expr):
    data = get_json(f"{PROM}/api/v1/query?" + urllib.parse.urlencode({"query": expr}))
    return data["data"]["result"]


def retry(fn, attempts=40, delay=3):
    last = None
    for _ in range(attempts):
        try:
            result = fn()
            if result:
                return result
        except Exception as exc:  # services still starting
            last = exc
        time.sleep(delay)
    raise RuntimeError(f"gave up waiting: {last}")


def main():
    results = {}

    def check(name, fn):
        try:
            value = retry(fn)
            results[name] = {"ok": True, "value": value}
            print(f"  [PASS] {name}: {value}")
        except RuntimeError as err:
            results[name] = {"ok": False, "value": str(err)}
            print(f"  [FAIL] {name}: {err}")

    print("Verifying monitoring & alerting")
    check("prometheus ready", lambda: urllib.request.urlopen(f"{PROM}/-/ready", timeout=5).status == 200)
    check("production target up", lambda: [r["value"][1] for r in query('up{job="shelf-production"}')
                                           if r["value"][1] == "1"])
    check("production version scraped", lambda: [r["metric"].get("version")
                                                 for r in query('shelf_app_info{job="shelf-production"}')
                                                 if r["metric"].get("version") == VERSION])
    check("alert rules loaded", lambda: [r["name"] for g in get_json(f"{PROM}/api/v1/rules")["data"]["groups"]
                                         for r in g["rules"]])
    check("alertmanager ready", lambda: urllib.request.urlopen(f"{AM}/-/ready", timeout=5).status == 200)
    check("grafana healthy", lambda: get_json(f"{GRAFANA}/api/health").get("database") == "ok")

    firing = query('ALERTS{alertstate="firing"}')
    results["firing_alerts"] = [a["metric"]["alertname"] for a in firing]
    print(f"  Currently firing alerts: {results['firing_alerts'] or 'none'}")
    for name, expr in [("active loans", 'library_active_loans{job="shelf-production"}'),
                       ("overdue loans", 'library_overdue_loans{job="shelf-production"}'),
                       ("request rate", 'sum(rate(flask_http_request_total{job="shelf-production"}[1m]))')]:
        value = query(expr)
        print(f"  {name}: {value[0]['value'][1] if value else 'n/a'}")

    try:
        auth = base64.b64encode(f"admin:{GRAFANA_PASSWORD}".encode()).decode()
        body = json.dumps({"time": int(time.time() * 1000), "tags": ["release", "production"],
                           "text": f"Released Shelf v{VERSION} to production"}).encode()
        req = urllib.request.Request(f"{GRAFANA}/api/annotations", data=body, method="POST",
                                     headers={"Content-Type": "application/json",
                                              "Authorization": f"Basic {auth}"})
        urllib.request.urlopen(req, timeout=10)
        print(f"  Grafana annotation added for v{VERSION}")
    except Exception as exc:
        print(f"  (could not add Grafana annotation: {exc})")

    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    with open(REPORT, "w") as fh:
        json.dump(results, fh, indent=2)
    failed = [k for k, v in results.items() if isinstance(v, dict) and not v["ok"]]
    if failed:
        sys.exit(f"Monitoring checks failed: {failed}")
    print("Monitoring checks passed")


if __name__ == "__main__":
    main()
