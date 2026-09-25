#!/usr/bin/env python3
"""Simulate a production incident and prove that the alert fires, reaches the team, and resolves.

    python3 scripts/simulate_incident.py outage   # stop the prod container (ShelfProductionDown)
    python3 scripts/simulate_incident.py errors   # burst of 5xx responses (ShelfHighErrorRate)

Runs inside Jenkins (docker CLI + devops-net), or from the host with the URLs overridden.
"""
import json
import os
import subprocess  # nosec B404 - fixed docker commands only
import sys
import time
import urllib.error
import urllib.request

AM = os.environ.get("ALERTMANAGER_URL", "http://alertmanager:9093")
RECEIVER = os.environ.get("RECEIVER_URL", "http://alert-receiver:5055")
APP = os.environ.get("APP_URL", "http://library-production:8000")
CONTAINER = os.environ.get("APP_CONTAINER", "library-production")


def alerts(name):
    with urllib.request.urlopen(f"{AM}/api/v2/alerts?filter=alertname%3D%22{name}%22", timeout=10) as res:
        return [a for a in json.loads(res.read()) if a["status"]["state"] == "active"]


def notifications(name, status):
    with urllib.request.urlopen(f"{RECEIVER}/alerts", timeout=10) as res:
        return [e for e in json.loads(res.read()) if e.get("name") == name and e.get("status") == status]


def wait(description, predicate, timeout=180, interval=5):
    start = time.time()
    while time.time() - start < timeout:
        if predicate():
            print(f"  [OK] {description} after {int(time.time() - start)}s")
            return True
        time.sleep(interval)
    print(f"  [FAIL] {description}: timed out after {timeout}s")
    return False


def outage():
    name = "ShelfProductionDown"
    before = len(notifications(name, "resolved"))
    print(f"Stopping {CONTAINER} to simulate an outage")
    subprocess.run(["docker", "stop", CONTAINER], check=True)  # nosec B603 B607
    try:
        ok = wait(f"{name} firing in Alertmanager", lambda: alerts(name))
        ok = wait("on-call webhook notified (firing)", lambda: notifications(name, "firing")) and ok
    finally:
        print(f"Recovering: starting {CONTAINER}")
        subprocess.run(["docker", "start", CONTAINER], check=True)  # nosec B603 B607
    ok = wait(f"{name} resolved", lambda: len(notifications(name, "resolved")) > before, timeout=240) and ok
    return ok


def errors():
    name = "ShelfHighErrorRate"
    print("Sending a burst of failing requests to /_chaos/error for ~75s")
    end = time.time() + 75
    while time.time() < end:
        for path in ("/_chaos/error", "/"):
            try:
                urllib.request.urlopen(APP + path, timeout=5)
            except urllib.error.HTTPError:
                pass
        time.sleep(0.2)
        if alerts(name):
            break
    ok = wait(f"{name} firing in Alertmanager", lambda: alerts(name), timeout=90)
    ok = wait("on-call webhook notified (firing)", lambda: notifications(name, "firing")) and ok
    print("Traffic stopped; the alert resolves once the error ratio drops (about 1-2 minutes).")
    return ok


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "outage"
    result = {"outage": outage, "errors": errors}[mode]()
    print("Incident simulation " + ("PASSED" if result else "FAILED"))
    sys.exit(0 if result else 1)
