# SIT223/753 HD Task: Answer Sheet (draft)

> Copy each section into the provided Word template and export to PDF.
> Screenshots referenced below are in `docs/screenshots/`.

## A link to the demo video
Add the video link here once it is uploaded (10 minutes or less). A suggested running order is at the end of this file.

## Link to the GitHub repository
https://github.com/rubyhdr/jenkinsPipeline (branch `main`, Jenkinsfile at the repository root)

(Give both the **marker** and the **Unit Chair** read access, or make the repository public.)

## Number of stages implemented
**All 7 stages: Build, Test, Code Quality, Security, Deploy, Release, Monitoring & Alerting.** They are fully
automated with gates between them. The pipeline is triggered by SCM polling, needs no manual steps by default, and
has an optional manual approval before production.

## Project description and technologies
**Shelf** is a library management system. Members browse and search a catalogue, borrow and return books,
renew a loan once, and join a reservation queue when all copies are out. When a copy comes back it is held for
the next person in the queue. Librarians get a dashboard (loans, overdue items, late fees, most-borrowed books) and
screens to manage books and members. Business rules include a 14-day loan period, a 5-loan limit, late fees of
$0.50/day capped at $20, a one-renewal limit that is blocked if someone is waiting, and ISBN-10/13 checksum validation.
They live in a framework-free service layer so they can be unit tested. The same features are exposed through a
JWT-secured REST API.

| Area | Technologies |
|---|---|
| Application | Python 3.12, Flask 3.1, SQLAlchemy 2.1, Flask-Login, Flask-WTF (CSRF), PyJWT, gunicorn, PostgreSQL 16 |
| UI | Server-rendered Jinja templates, hand-written CSS (light and dark mode, responsive), vanilla JS live search |
| CI/CD | Jenkins LTS (Configuration-as-Code + Job DSL + declarative Jenkinsfile), Docker, Docker Compose, local Docker registry |
| Testing | pytest, pytest-cov, Selenium 4 (headless Chrome grid) |
| Quality | SonarQube Community Build (custom quality gate), flake8 |
| Security | Bandit, pip-audit, Trivy (image + IaC) |
| Monitoring | Prometheus, Alertmanager, Grafana, prometheus-flask-exporter, Jenkins Prometheus plugin |

The whole toolchain is defined in the repository (`infra/`). A single `docker compose up` gives a working Jenkins with
the job, credentials and SonarQube gate already configured.

## Screenshot of the Jenkins pipeline
Insert `docs/screenshots/jenkins-stage-view.png` and/or `jenkins-pipeline-graph.png`. A fresh screenshot of the
latest green build is best.

## Stage descriptions

### Build
- **Versioning:** `VERSION` (major.minor) + Jenkins build number → `1.0.<build>`. The build is labelled with the git commit.
- **Two artefacts:**
  - a Python **wheel** (`shelf_library-1.0.N-py3-none-any.whl`), archived and fingerprinted in Jenkins;
  - a **Docker image**, pushed to a local registry (`localhost:5005/shelf`) with the tags `1.0.N`, `<commit>` and `latest`.
- **Image design:** multi-stage build (wheels compiled in a builder stage), non-root user, read-only code, `HEALTHCHECK`,
  and OCI labels (version, revision, build date).
- **Traceability:** `build-info.json` records the version, commit, image digest, size and build URL.
- **Tools:** Docker BuildKit, Python `build`, Jenkins artefact archiving.

### Test
- **Test levels:** 114 unit and integration tests run **in parallel** branches, plus 3 Selenium end-to-end tests after deploy.
  - Unit tests cover the business rules (due dates, fee calculation and cap, loan limits, renewal rules, ISBN checksums)
    and the services (reservation queue promotion, holds, permissions).
  - Integration tests drive the Flask app through HTTP: API lifecycle, JWT expiry, role checks, website flows,
    CSRF enforcement, open-redirect protection, security headers and `/metrics`.
- **Gates:** coverage from both branches is combined and gated at **≥ 80%** (currently **97%** line+branch). Any failing test fails the build.
- **Reporting:** results are published as JUnit (Jenkins test trend chart) and coverage via the Coverage plugin plus an HTML report.
- **Tools:** pytest, pytest-cov/coverage.py, Jenkins JUnit + Coverage + HTML Publisher plugins.

### Code Quality
- **Analysis:** SonarQube analyses the code with the coverage report and flake8 results imported.
- **Custom gate:** a **"Shelf Gate"** is created as code (`infra/sonarqube/init_sonar.py`):
  - coverage ≥ 80%;
  - duplication ≤ 3%;
  - reliability, security and maintainability ratings must be **A**;
  - no new issues in new code (Clean-as-You-Code).
- **Exclusions:** static assets and demo seed data are excluded from coverage, and tests are excluded from duplication.
- **Enforcement:** `scripts/sonar_quality_gate.py` waits for the server-side analysis, prints every condition with its actual value,
  saves `sonar-quality-gate.json`, and fails the build if the gate is red.
- **What the gate caught:** it **failed builds #1–2** on real issues.
  - A regex with catastrophic backtracking (reliability C) was rewritten.
  - Unlabelled form controls were fixed.
  - A function with cognitive complexity 23 was refactored.
- **Current state:** gate passed, all ratings A, 0 bugs, 0 vulnerabilities, 0% duplication. The history shows as a trend in SonarQube.

### Security
Three scanners run in parallel, each with its own gate:
- **Bandit (SAST):** fails on Medium+. 0 open findings. Two Low "hard-coded password" false positives were reviewed and
  suppressed with justification: one is a sentinel value the app refuses to run with in production, the other is a test key.
- **pip-audit:** checks pinned dependencies against PyPI/OSV advisories and fails on any vulnerability. 0 found.
- **Trivy image scan:** fails on HIGH/CRITICAL findings that have a fix.
  - **Build #3 was blocked** by msgpack GHSA-6v7p-g79w-8964 and setuptools CVE-2025-47273. Both were vendored inside `pip`.
    **Fixed** by removing pip from the runtime image.
  - The remaining 44 HIGH are 8 Debian CVEs with no fix yet (util-linux, acl, ncurses, systemd, perl). They were assessed as not
    reachable (non-root container, no mount capabilities, tools unused). They are picked up automatically when Debian ships
    fixes (`apt-get upgrade` in the build plus the fixable-only gate).
- **Trivy config (IaC):** found non-root and `:latest` issues in the tooling Dockerfiles. **Fixed** by pinning versions and
  adding explicit `USER` and `HEALTHCHECK` lines. Jenkins running as root (it needs the Docker socket) is an accepted risk.
- **Documentation:** full details in `docs/SECURITY_FINDINGS.md`. A summary table is archived on every build.

### Deploy (staging)
- **Deployment:** `scripts/deploy.sh` deploys the exact image built in this run to a **staging** environment (app + PostgreSQL)
  defined as code in `infra/docker-compose.staging.yml`.
  - Uses `docker compose up --wait`, which waits for the container health checks.
  - Secrets (`SECRET_KEY`, DB password) come from Jenkins credentials (masked in logs). Non-secret settings come from `infra/env/staging.env`.
- **Smoke test:** `scripts/smoke_test.py` checks health, that the *expected version* is running, the catalogue, and a real
  register → borrow → return through the API, the website and `/metrics`.
- **E2E:** Selenium runs in a disposable `selenium/standalone-chrome` container. It covers the home page, live search, and
  register → search → borrow → My loans → return → sign out, with screenshots on failure.
- **Rollback:** automatic. If the health check, smoke test or E2E tests fail, the previous image is restored.
  This is demonstrated with the `SIMULATE_BAD_DEPLOY` parameter: build #10 failed its smoke test and staging was restored to v1.0.9 automatically.

### Release (production)
- **Approval:** optional manual step (`input`, 30-minute timeout), controlled by the `AUTO_APPROVE_RELEASE` parameter.
- **Promotion:** the **same image digest** that passed staging is re-tagged `prod-<version>` and `prod` and deployed to
  **production** (`infra/docker-compose.production.yml`, port 8000). Production has its own env file, a shorter JWT
  expiry, a separate secret key and a memory limit.
- **Checks:** the same health check and smoke test, with automatic rollback to the previous production image.
- **Outputs:**
  - release notes generated from the git log since the last tag (`release-notes.md`);
  - an annotated git tag `v<version>`, pushed to GitHub when a token credential is configured.

### Monitoring & Alerting
- **Stack:** the pipeline brings up or updates Prometheus, Alertmanager, Grafana and a webhook receiver that acts as the on-call
  channel (Slack is configured as an option). All configuration is baked into images from the repository.
- **Metrics collected:** production and staging `/metrics`:
  - request rate, status codes and latency histograms;
  - CPU and memory;
  - business metrics: active and overdue loans, reservations, circulation events, sign-ins;
  - Jenkins build metrics.
- **Alert rules:**
  - production down (critical);
  - database unavailable (critical);
  - 5xx rate above 5%;
  - p95 latency above 500 ms;
  - memory above 400 MB;
  - more than 10 overdue loans;
  - last Jenkins build failed.
  - Alertmanager routes them, and critical alerts inhibit the related warnings.
- **Verification:** `scripts/check_monitoring.py` checks that Prometheus is scraping production *at the version just released*,
  that all 7 rules are loaded, and that Alertmanager and Grafana are healthy. It then adds a **release annotation** to the Grafana dashboard.
- **Incident simulation:** `SIMULATE_INCIDENT` stops production. The pipeline verifies that `ShelfProductionDown` fires
  (~30 s), that the on-call webhook receives it, and that it resolves after recovery (build #9). An `errors` mode drives the 5xx alert
  in the same way.

## Reflection (optional, for the "reflective insight" criterion)
- The gates proved their value: SonarQube and Trivy each stopped a build on real problems (a ReDoS-prone regex and
  vulnerable vendored packages). The fixes were made in the code rather than by relaxing thresholds.
- Deploying the *same digest* through staging and production, with smoke tests and automatic rollback, made releases
  repeatable. The rollback path was tested deliberately, not assumed to work.
- Local constraints shaped some decisions: Windows reserves port 5000 and port 9090 was already in use. Grafana 13's
  runtime plugin auto-update broke the Prometheus datasource, so it was disabled for reproducibility. That last one is a good argument
  for pinning *everything* in infrastructure-as-code.

## Suggested demo video outline (≈ 10 minutes)
1. (0:00) The app: browse, search, borrow, the librarian dashboard, dark mode, the version badge.
2. (1:30) Clone the repo → `docker compose -f infra/docker-compose.tools.yml up -d --build` → Jenkins is preconfigured (CasC).
3. (3:00) Trigger a build and walk through each stage while it runs: build info, test trend, coverage, SonarQube gate.
4. (5:30) Security reports and the Trivy block (build #3) → fix → green.
5. (6:30) Staging deploy + Selenium; show the `SIMULATE_BAD_DEPLOY` rollback (build #10).
6. (7:30) Release: prod tag, release notes, production on :8000 showing the new version.
7. (8:30) Grafana dashboard with release annotations; run `SIMULATE_INCIDENT` → alert fires in Alertmanager and the on-call feed → resolves.
