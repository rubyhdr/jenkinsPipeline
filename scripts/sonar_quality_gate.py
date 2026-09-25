#!/usr/bin/env python3
"""Wait for SonarQube to process the analysis, print the quality gate conditions, fail if it is red.

Reads the task id from .scannerwork/report-task.txt (written by sonar-scanner).
Env: SONAR_HOST_URL, SONAR_TOKEN
"""
import base64
import json
import os
import sys
import time
import urllib.parse
import urllib.request

HOST = os.environ.get("SONAR_HOST_URL", "http://sonarqube:9000").rstrip("/")
TOKEN = os.environ["SONAR_TOKEN"]
REPORT_TASK = os.environ.get("SONAR_REPORT_TASK", ".scannerwork/report-task.txt")
OUTPUT = os.environ.get("SONAR_GATE_REPORT", "reports/sonar-quality-gate.json")


def get(path, **params):
    url = f"{HOST}{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url)
    req.add_header("Authorization", "Basic " + base64.b64encode(f"{TOKEN}:".encode()).decode())
    with urllib.request.urlopen(req, timeout=30) as res:
        return json.loads(res.read().decode())


def main():
    with open(REPORT_TASK) as fh:
        task = dict(line.strip().split("=", 1) for line in fh if "=" in line)
    task_id = task["ceTaskId"]
    print(f"Waiting for SonarQube background task {task_id}")

    for _ in range(90):
        status = get("/api/ce/task", id=task_id)["task"]
        if status["status"] in ("SUCCESS", "FAILED", "CANCELED"):
            break
        time.sleep(2)
    if status["status"] != "SUCCESS":
        sys.exit(f"SonarQube analysis did not complete: {status['status']}")

    gate = get("/api/qualitygates/project_status", analysisId=status["analysisId"])["projectStatus"]
    measures = get("/api/measures/component", component=task["projectKey"],
                   metricKeys="coverage,duplicated_lines_density,ncloc,code_smells,bugs,"
                              "vulnerabilities,sqale_index,complexity,cognitive_complexity")
    values = {m["metric"]: m.get("value") for m in measures["component"]["measures"]}

    print(f"\nQuality gate: {gate['status']}")
    print(f"{'Metric':45} {'Actual':>10} {'Op':>4} {'Threshold':>10}  Result")
    for cond in gate.get("conditions", []):
        print(f"{cond['metricKey']:45} {cond.get('actualValue', '-'):>10} {cond['comparator']:>4} "
              f"{cond.get('errorThreshold', '-'):>10}  {cond['status']}")
    print("\nMeasures: " + ", ".join(f"{k}={v}" for k, v in sorted(values.items())))
    print(f"Dashboard: {task.get('dashboardUrl', HOST)}")

    os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
    with open(OUTPUT, "w") as fh:
        json.dump({"status": gate["status"], "conditions": gate.get("conditions", []),
                   "measures": values}, fh, indent=2)

    if gate["status"] != "OK":
        sys.exit("Quality gate FAILED; see conditions above")


if __name__ == "__main__":
    main()
