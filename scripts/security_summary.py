#!/usr/bin/env python3
"""Summarise Bandit, pip-audit and Trivy JSON reports into one table (reports/security-summary.md)."""
import json
import os
from collections import Counter

REPORTS = os.environ.get("REPORT_DIR", "reports")


def load(name):
    path = os.path.join(REPORTS, name)
    if not os.path.exists(path):
        return None
    with open(path) as fh:
        return json.load(fh)


def main():
    lines = ["# Security scan summary", "",
             "| Tool | Scope | Findings | Details |", "|---|---|---|---|"]

    bandit = load("bandit.json")
    if bandit is not None:
        sev = Counter(r["issue_severity"] for r in bandit.get("results", []))
        skipped = bandit.get("metrics", {}).get("_totals", {}).get("skipped_tests", 0)
        detail = ", ".join(f"{k}: {v}" for k, v in sev.items()) or "none"
        lines.append(f"| Bandit | Python source (SAST) | {sum(sev.values())} | {detail}; "
                     f"{skipped} reviewed & suppressed with `# nosec` |")

    audit = load("pip-audit.json")
    if audit is not None:
        deps = audit.get("dependencies", audit if isinstance(audit, list) else [])
        vulns = [(d["name"], v["id"]) for d in deps for v in d.get("vulns", [])]
        detail = ", ".join(f"{n} {i}" for n, i in vulns) or "none"
        lines.append(f"| pip-audit | {len(deps)} Python dependencies | {len(vulns)} | {detail} |")

    trivy = load("trivy-image.json")
    if trivy is not None:
        sev = Counter()
        for result in trivy.get("Results", []):
            for vuln in result.get("Vulnerabilities") or []:
                sev[vuln["Severity"]] += 1
        detail = ", ".join(f"{k}: {v}" for k, v in sorted(sev.items())) or "none"
        lines.append(f"| Trivy | Container image (OS + libraries), all severities | "
                     f"{sum(sev.values())} | {detail} |")

    config = load("trivy-config.json")
    if config is not None:
        mis = [m for r in config.get("Results", []) for m in (r.get("Misconfigurations") or [])]
        sev = Counter(m["Severity"] for m in mis)
        detail = ", ".join(f"{k}: {v}" for k, v in sorted(sev.items())) or "none"
        lines.append(f"| Trivy config | Dockerfile + Compose (IaC) | {len(mis)} | {detail} |")

    lines += ["", "Gate: the build fails on any Medium+ Bandit issue, any known-vulnerable dependency, "
              "or any HIGH/CRITICAL image vulnerability that has a fix available. "
              "Accepted risks are documented in docs/SECURITY_FINDINGS.md and `.trivyignore`."]
    text = "\n".join(lines) + "\n"
    with open(os.path.join(REPORTS, "security-summary.md"), "w") as fh:
        fh.write(text)
    print(text)


if __name__ == "__main__":
    main()
