#!/usr/bin/env python3
"""Post-deployment smoke test: health, version, and a real borrow/return through the API.

    python3 scripts/smoke_test.py http://library-staging:8000 --expect-version 1.0.12
"""
import argparse
import json
import sys
import time
import urllib.error
import urllib.request
import uuid


def request(base, method, path, body=None, token=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=10) as res:
            raw = res.read().decode()
            return res.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as err:
        raw = err.read().decode()
        try:
            return err.code, json.loads(raw)
        except json.JSONDecodeError:
            return err.code, {"raw": raw[:200]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("base_url")
    parser.add_argument("--expect-version")
    parser.add_argument("--report")
    parser.add_argument("--retries", type=int, default=30)
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    checks = []

    def check(name, ok, detail=""):
        checks.append({"check": name, "ok": bool(ok), "detail": detail})
        print(f"  [{'PASS' if ok else 'FAIL'}] {name} {detail}")
        return ok

    print(f"Smoke testing {base}")
    health = {}
    for _ in range(args.retries):
        try:
            status, health = request(base, "GET", "/health")
            if status == 200:
                break
        except (urllib.error.URLError, ConnectionError, TimeoutError):
            pass
        time.sleep(2)
    check("health endpoint is ok", health.get("status") == "ok", json.dumps(health))
    if args.expect_version:
        check("running expected version", health.get("version") == args.expect_version,
              f"(want {args.expect_version}, got {health.get('version')})")

    status, books = request(base, "GET", "/api/books?available=1")
    check("catalogue lists books", status == 200 and books.get("count", 0) > 0,
          f"({books.get('count', 0)} available)")

    email = f"smoke-{uuid.uuid4().hex[:10]}@example.com"
    status, reg = request(base, "POST", "/api/auth/register",
                          {"name": "Smoke Test", "email": email, "password": "Smoke-test-123"})
    check("member can register", status == 201, f"({status})")
    token = reg.get("token")

    if token and books.get("books"):
        book_id = books["books"][0]["id"]
        status, loan = request(base, "POST", "/api/loans", {"book_id": book_id}, token)
        check("member can borrow", status == 201, f"(book {book_id}, {status})")
        loan_id = loan.get("loan", {}).get("id")
        status, _ = request(base, "POST", f"/api/loans/{loan_id}/return", token=token)
        check("member can return", status == 200, f"({status})")
    else:
        check("member can borrow", False, "(no token or no books)")

    try:
        with urllib.request.urlopen(base + "/", timeout=10) as res:
            html = res.read().decode()
        check("website renders", res.status == 200 and "Find your next read" in html)
    except urllib.error.URLError as err:
        check("website renders", False, str(err))

    try:
        with urllib.request.urlopen(base + "/metrics", timeout=10) as res:
            check("metrics exposed", "library_active_loans" in res.read().decode())
    except urllib.error.URLError as err:
        check("metrics exposed", False, str(err))

    failed = [c for c in checks if not c["ok"]]
    if args.report:
        with open(args.report, "w") as fh:
            json.dump({"base_url": base, "checks": checks, "passed": not failed}, fh, indent=2)
    verdict = "PASSED" if not failed else "FAILED"
    print(f"Smoke test {verdict}: {len(checks) - len(failed)}/{len(checks)} checks")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
