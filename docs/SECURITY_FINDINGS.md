# Security Findings and Remediation

The **Security** stage runs three independent scanners in parallel on every build. Each one has an
explicit gate. This document records what they found, how severe it was, and what was done about it.
The latest machine-generated summary is archived with each build as `reports/security-summary.md`.

| Tool | What it scans | Gate (build fails when…) |
|---|---|---|
| **Bandit** (SAST) | Python source in `app/` | any Medium or High severity issue |
| **pip-audit** | pinned dependencies in `requirements.txt` (PyPI/OSV advisories) | any known vulnerability |
| **Trivy image** | final container image: Debian OS packages + Python packages | any HIGH/CRITICAL vulnerability **that has a fix available** |
| **Trivy config** | Dockerfiles and Compose files (IaC misconfiguration) | informational: reported, reviewed and fixed below |

Separately, SonarQube's reliability and security ratings are part of the quality gate in the Code Quality stage.

---

## 1. Found by the pipeline and fixed

### 1.1 Vulnerable packages vendored inside `pip`: HIGH (Trivy), fixed
Build #3 **was blocked by the Trivy gate**:

| Package | Advisory | Severity | Issue |
|---|---|---|---|
| msgpack 1.1.2 | GHSA-6v7p-g79w-8964 | HIGH | Out-of-bounds read or crash when an `Unpacker` is reused after an error |
| setuptools 70.3.0 | CVE-2025-47273 | HIGH | Path traversal in `PackageIndex`, which can write files outside the target directory |

**Analysis.** Neither package is an application dependency. `pip list` inside the image showed no
`msgpack` or `setuptools`: both are *vendored inside pip itself* (`pip/_vendor/msgpack` and
`pip/_vendor/pkg_resources`). The app never uses pip at runtime.

**Fix (commit "Remove pip from runtime image…").** The runtime stage now uninstalls pip after installing
the pre-built wheels and deletes `ensurepip`'s bundled copy. This removes both vulnerable
components and shrinks the attack surface: an attacker who gets code execution can no longer `pip install`
tools. Build #4 passed the gate and the container still reports `healthy`.

### 1.2 Regular expression with super-linear backtracking: MEDIUM reliability (SonarQube python:S8786), fixed
The email check `^[^@\s]+@[^@\s]+\.[^@\s]+$` can backtrack polynomially on crafted input such as a
long string with many dots. This is a **ReDoS** (regex denial of service) vector on the public
registration endpoint. SonarQube rated reliability **C**, and the quality gate failed builds #1 and #2.

**Fix.** Replaced the regex with a linear structural check (`accounts.is_valid_email`), with new unit tests for
malformed addresses. Reliability rating is now **A**.

### 1.3 Accessibility: form labels not associated with inputs (SonarQube Web:S6853), fixed
Labels now use explicit `for=`/`id` pairs, and errors are linked with `aria-describedby` and `aria-invalid`.

### 1.4 Container misconfigurations (Trivy config), fixed
| ID | Severity | Where | Fix |
|---|---|---|---|
| DS-0002 "image user should not be root" | HIGH | Prometheus, Alertmanager and Grafana Dockerfiles | explicit `USER nobody` / `USER 472` |
| DS-0001 "`:latest` tag used" | MEDIUM | the same three | pinned to `v3.14.0`, `v0.34.1`, `13.2.2` |
| DS-0026 "no HEALTHCHECK" | LOW | Jenkins, monitoring images | added `HEALTHCHECK` instructions |

The **application** Dockerfile had no findings. It is multi-stage, runs as a dedicated non-root user, keeps its code read-only, applies OS
updates, and has a healthcheck.

---

## 2. Reviewed and accepted (with mitigation)

### 2.1 Unfixed Debian vulnerabilities in the base image: HIGH, accepted until Debian ships fixes
Trivy reports 44 HIGH findings in the `python:3.12-slim` (Debian 13.7) layer. These are **8 unique CVEs**
repeated across related packages. **None has a fixed version available yet** (status `affected`).

| CVE | Packages | Why the risk is low for Shelf |
|---|---|---|
| CVE-2026-76642, -78408, -78409, -78410 | util-linux family (`mount`, `libmount1`, `libblkid1`, `login`…) | mount/namespace tools. The container runs as an unprivileged user with no capabilities to mount or enter namespaces, and the app never calls them |
| CVE-2026-54369 | libacl1 | symlink traversal via ACL helpers. The app does not manipulate ACLs, and its code directory is read-only |
| CVE-2025-69720 | ncurses | terminal library. Not used by a headless web server |
| CVE-2026-16742 | libsystemd0 / libudev1 | systemd is not running in the container |
| CVE-2026-9538 | perl-base | perl is not invoked by the application |

**Mitigations:**
- The image runs `apt-get upgrade` on every build, so Debian's fixes are picked up automatically as soon as they are released.
- The gate uses `--ignore-unfixed`. As soon as any of these gains a fix, Trivy treats it as blocking, so the build fails until the upgraded image is produced.
- The runtime is non-root with read-only code and a 512 MB memory limit, and exposes only port 8000.
- The full inventory, including unfixed and lower-severity issues, is archived as `trivy-image.json` on every build, so the trend is visible over time.

### 2.2 Bandit B105 "possible hardcoded password": LOW, false positive, suppressed with `# nosec`
| Location | Value | Why it's safe |
|---|---|---|
| `app/__init__.py` `DEFAULT_SECRET` | `dev-only-secret-change-me` | This is a sentinel. `create_app` **refuses to start** in staging or production if `SECRET_KEY` is this value or empty (covered by `test_production_requires_secret_key`) |
| `app/config.py` `TestingConfig.SECRET_KEY` | test-only key | Used only by the in-memory test configuration |

Real secrets (`SECRET_KEY` and the DB password for each environment) are stored as **Jenkins credentials**, injected with
`withCredentials`, and masked in logs. They are never written to the repository.

### 2.3 Jenkins runs as root: HIGH (Trivy DS-0002), accepted
Jenkins needs access to the host Docker socket to build and deploy containers (Docker-outside-of-Docker on
Docker Desktop). Mitigations: Jenkins listens only on localhost, requires login (anonymous access disabled),
has no external agents, and runs only the repository's own Jenkinsfile. In a real deployment this would be replaced
by rootless BuildKit or dedicated build agents. The exception is annotated inline (`# trivy:ignore:AVD-DS-0002`).

### 2.4 SonarQube bootstrap container runs as root: HIGH (Trivy DS-0002), accepted
This is a one-shot container that writes the Jenkins analysis token into a shared root-owned volume and exits. It has no
open ports and never runs alongside user traffic.

### 2.5 Demo-only chaos endpoints
`/_chaos/error` and `/_chaos/slow` exist so that the alerting can be demonstrated. They are **disabled by default**
(`CHAOS_ENABLED=false`) and only enabled through `infra/env/*.env` for this assignment. A real deployment sets
it to `false`.

---

## 3. Other security controls in the application
- Passwords are hashed with Werkzeug's `generate_password_hash` (scrypt/pbkdf2), with a minimum length and complexity rule.
- CSRF protection on every form (Flask-WTF). The JSON API is CSRF-exempt but requires a signed JWT (HS256) with a 30–60 minute expiry.
- Authorisation checks in the service layer: members can only act on their own loans and reservations, and librarian routes require that role (tested).
- Open-redirect protection on `?next=` after login (tested).
- Security headers: `Content-Security-Policy`, `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy`.
- Session cookies are `HttpOnly` and `SameSite=Lax`.
- SQLAlchemy ORM only, so no string-built SQL.
