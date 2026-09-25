"""One-shot SonarQube bootstrap, run by the sonar-init container.

* waits for SonarQube to come up
* replaces the default admin password
* creates the "Shelf Gate" quality gate with custom thresholds and makes it the default
* creates the `shelf` project and assigns the gate
* issues a fresh analysis token for Jenkins and writes it to /var/sonar/token
"""
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

SONAR_URL = os.environ.get("SONAR_URL", "http://sonarqube:9000").rstrip("/")
ADMIN_PASSWORD = os.environ.get("SONAR_ADMIN_PASSWORD", "Shelf-Sonar-Admin-2026!")
TOKEN_FILE = os.environ.get("SONAR_TOKEN_FILE", "/var/sonar/token")
PROJECT_KEY = "shelf"
GATE = "Shelf Gate"

# (metric candidates, operator, threshold). Newer SonarQube builds use software_quality_* ratings;
# older ones use the classic metric keys, so each condition tries both.
CONDITIONS = [
    (["coverage"], "LT", "80"),
    (["duplicated_lines_density"], "GT", "3"),
    (["software_quality_reliability_rating", "reliability_rating"], "GT", "1"),
    (["software_quality_security_rating", "security_rating"], "GT", "1"),
    (["software_quality_maintainability_rating", "sqale_rating"], "GT", "1"),
]


def call(method, path, params=None, password=None, expect_json=True):
    data = urllib.parse.urlencode(params or {}).encode()
    url = f"{SONAR_URL}{path}"
    if method == "GET" and params:
        url += "?" + data.decode()
        data = None
    req = urllib.request.Request(url, data=data, method=method)
    if password is not None:
        creds = base64.b64encode(f"admin:{password}".encode()).decode()
        req.add_header("Authorization", f"Basic {creds}")
    with urllib.request.urlopen(req, timeout=30) as res:
        body = res.read().decode()
    return json.loads(body) if expect_json and body else body


def wait_until_up():
    for attempt in range(120):
        try:
            if call("GET", "/api/system/status").get("status") == "UP":
                print("SonarQube is UP")
                return
        except (urllib.error.URLError, ConnectionError, json.JSONDecodeError):
            pass
        if attempt % 10 == 0:
            print("Waiting for SonarQube...")
        time.sleep(5)
    sys.exit("SonarQube did not start in time")


def admin_password():
    if call("GET", "/api/authentication/validate", password=ADMIN_PASSWORD).get("valid"):
        return ADMIN_PASSWORD
    print("Changing default admin password")
    call("POST", "/api/users/change_password",
         {"login": "admin", "previousPassword": "admin", "password": ADMIN_PASSWORD},
         password="admin", expect_json=False)
    return ADMIN_PASSWORD


def ensure_gate(pw):
    try:
        gate = call("GET", "/api/qualitygates/show", {"name": GATE}, password=pw)
    except urllib.error.HTTPError:
        call("POST", "/api/qualitygates/create", {"name": GATE}, password=pw)
        gate = call("GET", "/api/qualitygates/show", {"name": GATE}, password=pw)
        print(f"Created quality gate '{GATE}'")

    existing = {c["metric"] for c in gate.get("conditions", [])}
    for metrics, op, error in CONDITIONS:
        if existing.intersection(metrics):
            continue
        for metric in metrics:
            try:
                call("POST", "/api/qualitygates/create_condition",
                     {"gateName": GATE, "metric": metric, "op": op, "error": error}, password=pw)
                print(f"  condition: {metric} {op} {error}")
                break
            except urllib.error.HTTPError as err:
                print(f"  metric {metric} not accepted ({err.code}), trying fallback")
    call("POST", "/api/qualitygates/set_as_default", {"name": GATE}, password=pw, expect_json=False)


def ensure_project(pw):
    found = call("GET", "/api/projects/search", {"projects": PROJECT_KEY}, password=pw)
    if not found.get("components"):
        call("POST", "/api/projects/create", {"project": PROJECT_KEY, "name": "Shelf"}, password=pw)
        print("Created project 'shelf'")
    call("POST", "/api/qualitygates/select", {"gateName": GATE, "projectKey": PROJECT_KEY},
         password=pw, expect_json=False)


def issue_token(pw):
    try:
        call("POST", "/api/user_tokens/revoke", {"name": "jenkins"}, password=pw, expect_json=False)
    except urllib.error.HTTPError:
        pass
    token = call("POST", "/api/user_tokens/generate",
                 {"name": "jenkins", "type": "GLOBAL_ANALYSIS_TOKEN"}, password=pw)["token"]
    os.makedirs(os.path.dirname(TOKEN_FILE), exist_ok=True)
    with open(TOKEN_FILE, "w") as fh:
        fh.write(token)
    print(f"Wrote analysis token to {TOKEN_FILE}")


def main():
    wait_until_up()
    pw = admin_password()
    ensure_gate(pw)
    ensure_project(pw)
    issue_token(pw)
    print("SonarQube bootstrap complete")


if __name__ == "__main__":
    main()
