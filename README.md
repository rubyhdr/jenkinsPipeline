# Shelf: Library System with a Jenkins DevOps Pipeline

Shelf is a small library management system (Flask + Postgres). It is delivered by a 7-stage Jenkins pipeline:
**Build → Test → Code Quality → Security → Deploy → Release → Monitoring**.
Everything (Jenkins, SonarQube, registry, staging, production and monitoring) runs locally with Docker Compose,
and all of it is configured as code in this repository.

**Repository:** https://github.com/rubyhdr/jenkinsPipeline (branch `main`)

| | |
|---|---|
| **App** | Browse and search the catalogue, borrow, return, renew, reserve, librarian dashboard, REST API with JWT |
| **Stack** | Python 3.12, Flask, SQLAlchemy, Postgres 16, gunicorn, Docker |
| **CI/CD** | Jenkins (Configuration-as-Code + Jenkinsfile), local Docker registry |
| **Quality** | pytest (unit + integration + Selenium E2E), coverage ≥ 80% gate, flake8, SonarQube quality gate |
| **Security** | Bandit (SAST), pip-audit (dependencies), Trivy (image CVEs + Dockerfile/Compose misconfigurations) |
| **Ops** | Staging and production via Compose, automatic rollback, Prometheus, Alertmanager, Grafana |

## Quick start (demo)

Prerequisites: Docker Desktop (about 6 GB of RAM for Docker) and Git.

```bash
git clone https://github.com/rubyhdr/jenkinsPipeline.git
cd jenkinsPipeline

# 1. Start the CI/CD tooling (the first build takes a few minutes)
docker compose -f infra/docker-compose.tools.yml up -d --build

# 2. Open Jenkins at http://localhost:8080 (admin / admin)
#    The "shelf-pipeline" job is created automatically by Configuration-as-Code.
#    It polls GitHub every 2 minutes, or click "Build with Parameters" → Build.
```

### How Jenkins gets the code

- The job clones **https://github.com/rubyhdr/jenkinsPipeline.git**, branch `main`, and runs its `Jenkinsfile`.
  The repository is public, so no credentials are needed to clone it.
- It polls GitHub every 2 minutes, so **every `git push` to `main` starts a build automatically**.
- You can override the source in `infra/.env`, which is git-ignored and read by Docker Compose. After editing it,
  run `docker compose -f infra/docker-compose.tools.yml up -d`:

  ```ini
  PIPELINE_REPO_URL=https://github.com/rubyhdr/jenkinsPipeline.git
  PIPELINE_BRANCH=*/main
  # Build uncommitted local work instead (the checkout is mounted read-only in Jenkins):
  # PIPELINE_REPO_URL=file:///workspace-src
  ```

### Pushing release tags to GitHub (optional)

On every successful release, the Release stage creates an annotated tag `v<version>` (for example `v1.0.14`).
To have Jenkins push that tag to GitHub:

1. Create a GitHub **fine-grained personal access token** limited to `rubyhdr/jenkinsPipeline`, with
   *Contents: Read and write* permission.
2. Add it to `infra/.env` (never commit it):
   ```ini
   GITHUB_USER=rubyhdr
   GITHUB_TOKEN=github_pat_...
   ```
3. Run `docker compose -f infra/docker-compose.tools.yml up -d`. Jenkins stores the token as the `github-push`
   credential and masks it in logs.

Without a token the tag is still created, but only in the Jenkins build workspace. The build log says so.

### Where everything lives

| Service | URL | Login |
|---|---|---|
| Shelf production | http://localhost:8000 | `member@shelf.local` / `Member1234`, `librarian@shelf.local` / `Librarian123` |
| Shelf staging | http://localhost:5001 | same demo accounts |
| Jenkins | http://localhost:8080 | admin / admin |
| SonarQube | http://localhost:9000 | admin / `Shelf-Sonar-Admin-2026!` |
| Grafana | http://localhost:3000 | anonymous viewer (admin / admin) |
| Prometheus | http://localhost:9091 | none |
| Alertmanager | http://localhost:9093 | none |
| On-call feed (webhook receiver) | http://localhost:5055 | none |
| Docker registry | http://localhost:5005/v2/_catalog | none |

You can override any password with environment variables before step 1, for example
`JENKINS_ADMIN_PASSWORD`, `SONAR_ADMIN_PASSWORD`, `GRAFANA_ADMIN_PASSWORD`, `PROD_SECRET_KEY` and `SHELF_DB_PASSWORD`.

## Pipeline stages

| # | Stage | What happens | Gate (build fails if…) |
|---|---|---|---|
| 1 | **Build** | Version `1.0.<build>`: builds a wheel and a Docker image tagged `<version>`, `<commit>` and `latest`, pushes them to the registry, and records the digest in `build-info.json` | image or wheel fails to build |
| 2 | **Test** | Unit and integration tests run in parallel (pytest). JUnit results are published, coverage is combined, and an HTML report is produced | any test fails; coverage < 80% |
| 3 | **Code Quality** | flake8 plus SonarQube analysis with coverage and lint imports. A custom **Shelf Gate** is created by `infra/sonarqube/init_sonar.py` | coverage < 80%, duplication > 3%, or reliability, security or maintainability rating worse than A |
| 4 | **Security** | In parallel: Bandit (SAST), pip-audit (dependency CVEs), Trivy (image CVEs + IaC misconfigurations). Results go to a summary table | Bandit Medium+, any vulnerable dependency, or a fixable HIGH/CRITICAL image CVE |
| 5 | **Deploy (staging)** | `scripts/deploy.sh` runs Compose `up --wait`, then a smoke test (health, version, API borrow and return, UI, metrics), then Selenium E2E in headless Chrome | health or smoke test or E2E fails → **automatic rollback** to the previous image |
| 6 | **Release (production)** | Optional manual approval. The *same image* is re-tagged `prod-<version>` and deployed to production with its own env config and secrets. Release notes and a `v<version>` git tag are created | smoke test fails → automatic rollback |
| 7 | **Monitoring** | Monitoring stack is brought up or updated. Checks that Prometheus scrapes production at the new version, the rules are loaded, and Alertmanager and Grafana are healthy. Adds a release annotation in Grafana. Optional incident simulation | any check fails; simulated incident not alerted |

Build parameters: `AUTO_APPROVE_RELEASE` (manual gate), `RUN_E2E`, `SIMULATE_INCIDENT` (stops production and
verifies that the alert fires, notifies and resolves) and `SIMULATE_BAD_DEPLOY` (demonstrates the automatic rollback).

## Alert rules

| Alert | Condition | Severity |
|---|---|---|
| ShelfProductionDown | production not scrapeable for 20 s | critical |
| ShelfDatabaseUnavailable | business metrics report DB errors for 30 s | critical |
| ShelfHighErrorRate | 5xx ratio > 5% over 1 min | warning |
| ShelfHighLatency | p95 latency > 500 ms for 1 min | warning |
| ShelfHighMemory | RSS > 400 MB for 2 min (limit 512 MB) | warning |
| ShelfManyOverdueLoans | > 10 overdue loans for 5 min | info |
| JenkinsLastBuildFailed | last pipeline build not successful | warning |

Alerts are routed by Alertmanager to the webhook receiver (a Slack example is included, commented out in
`alertmanager.yml`). To try it by hand:

```bash
docker exec shelf-jenkins python3 /var/jenkins_home/workspace/shelf-pipeline/scripts/simulate_incident.py outage
docker exec shelf-jenkins python3 /var/jenkins_home/workspace/shelf-pipeline/scripts/simulate_incident.py errors
```

## Running the app locally without Docker

```bash
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
flask --app wsgi init-db && flask --app wsgi seed
flask --app wsgi run --port 5050                  # http://127.0.0.1:5050
pytest --cov=app                                  # 114 tests
```

## Repository layout

```
app/                Flask app: models, services (business rules), api/ (JSON), web/ (UI), templates, static
tests/              unit/, integration/, e2e/ (Selenium)
Dockerfile          multi-stage, non-root, HEALTHCHECK
Jenkinsfile         the pipeline
infra/              tools, staging, production and monitoring Compose files; Jenkins CasC; SonarQube bootstrap
scripts/            deploy/rollback, smoke test, quality gate, security summary, monitoring checks, incident simulation
docs/               security findings, report draft
```

## Stopping and cleaning up

```bash
docker compose -p shelf-monitoring -f infra/docker-compose.monitoring.yml down
docker compose -p shelf-production -f infra/docker-compose.production.yml down
docker compose -p shelf-staging -f infra/docker-compose.staging.yml down
docker compose -f infra/docker-compose.tools.yml down        # add -v to delete all data volumes
```
