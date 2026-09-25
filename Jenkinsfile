// Shelf library system: CI/CD pipeline
// Build → Test → Code Quality → Security → Deploy (staging) → Release (production) → Monitoring
//
// Runs on the Jenkins controller defined in infra/ (Docker CLI talks to the host daemon).
// Tool containers (sonar-scanner, Trivy, Selenium) share this workspace via --volumes-from jenkins.

pipeline {
  agent any

  parameters {
    booleanParam(name: 'AUTO_APPROVE_RELEASE', defaultValue: true,
                 description: 'Promote to production without waiting for manual approval')
    booleanParam(name: 'RUN_E2E', defaultValue: true,
                 description: 'Run Selenium browser tests against staging')
    booleanParam(name: 'SIMULATE_INCIDENT', defaultValue: false,
                 description: 'After release, stop production briefly and verify the alert fires and resolves')
    booleanParam(name: 'SIMULATE_BAD_DEPLOY', defaultValue: false,
                 description: 'Make the staging smoke test fail to demonstrate automatic rollback')
  }

  triggers {
    pollSCM('H/2 * * * *')
  }

  options {
    timestamps()
    disableConcurrentBuilds()
    buildDiscarder(logRotator(numToKeepStr: '30', artifactNumToKeepStr: '10'))
    timeout(time: 60, unit: 'MINUTES')
  }

  environment {
    REGISTRY        = 'localhost:5005'
    IMAGE_REPO      = "${REGISTRY}/shelf"
    DOCKER_NET      = 'devops-net'
    SONAR_HOST_URL  = 'http://sonarqube:9000'
    PIP_CACHE_DIR   = '/var/jenkins_home/.cache/pip'
    VENV            = '.venv/bin'
    REPORT_DIR      = 'reports'
  }

  stages {

    stage('Checkout & Version') {
      steps {
        script {
          env.GIT_SHORT = sh(script: 'git rev-parse --short=8 HEAD', returnStdout: true).trim()
          env.VERSION   = "${readFile('VERSION').trim()}.${env.BUILD_NUMBER}"
          env.IMAGE     = "${env.IMAGE_REPO}:${env.VERSION}"
          currentBuild.displayName = "#${env.BUILD_NUMBER} v${env.VERSION}"
          currentBuild.description = "commit ${env.GIT_SHORT}"
        }
        sh '''
          rm -rf reports && mkdir -p reports
          echo "Version ${VERSION} (commit ${GIT_SHORT})"
          git log -1 --pretty='format:%h %an: %s%n'
        '''
      }
    }

    stage('Build') {
      steps {
        sh '''
          python3 -m venv .venv
          $VENV/pip install --quiet --upgrade pip
          $VENV/pip install --quiet -r requirements-dev.txt

          # Python package artefact (wheel) versioned with the build number
          echo "${VERSION}" > VERSION
          $VENV/python -m build --wheel --outdir dist . > reports/build-wheel.log

          # Container artefact, tagged with the version and commit, pushed to the registry
          docker build \
            --build-arg APP_VERSION="${VERSION}" \
            --build-arg GIT_COMMIT="${GIT_COMMIT}" \
            --build-arg BUILD_DATE="$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
            --label "jenkins.build=${BUILD_URL}" \
            -t "${IMAGE}" -t "${IMAGE_REPO}:${GIT_SHORT}" -t "${IMAGE_REPO}:latest" .
          docker push --quiet "${IMAGE}"
          docker push --quiet "${IMAGE_REPO}:${GIT_SHORT}"
          docker push --quiet "${IMAGE_REPO}:latest"

          DIGEST=$(docker inspect --format '{{index .RepoDigests 0}}' "${IMAGE}")
          SIZE=$(docker image inspect --format '{{.Size}}' "${IMAGE}")
          cat > reports/build-info.json <<EOF
{"version": "${VERSION}", "commit": "${GIT_COMMIT}", "image": "${IMAGE}",
 "digest": "${DIGEST}", "image_size_bytes": ${SIZE}, "build_url": "${BUILD_URL}",
 "wheel": "$(ls dist/*.whl | xargs -n1 basename)"}
EOF
          cat reports/build-info.json
        '''
      }
      post {
        success {
          archiveArtifacts artifacts: 'dist/*.whl, reports/build-info.json', fingerprint: true
        }
      }
    }

    stage('Test') {
      parallel {
        stage('Unit tests') {
          steps {
            sh '''
              COVERAGE_FILE=.coverage.unit $VENV/pytest tests/unit -m unit \
                --junitxml=reports/junit-unit.xml --cov=app --cov-branch --cov-report= -q
            '''
          }
        }
        stage('Integration tests') {
          steps {
            sh '''
              COVERAGE_FILE=.coverage.integration $VENV/pytest tests/integration -m integration \
                --junitxml=reports/junit-integration.xml --cov=app --cov-branch --cov-report= -q
            '''
          }
        }
      }
      post {
        always {
          junit testResults: 'reports/junit-*.xml', allowEmptyResults: false
        }
      }
    }

    stage('Coverage gate') {
      steps {
        sh '''
          $VENV/coverage combine .coverage.unit .coverage.integration
          $VENV/coverage xml -o coverage.xml
          $VENV/coverage html -d reports/coverage-html
          $VENV/coverage report --fail-under=80 | tee reports/coverage.txt
        '''
      }
      post {
        always {
          recordCoverage(tools: [[parser: 'COBERTURA', pattern: 'coverage.xml']],
                         id: 'coverage', name: 'Python coverage', sourceCodeRetention: 'EVERY_BUILD')
          publishHTML(target: [reportDir: 'reports/coverage-html', reportFiles: 'index.html',
                               reportName: 'Coverage report', keepAll: true, allowMissing: true,
                               alwaysLinkToLastBuild: true])
        }
      }
    }

    stage('Code Quality') {
      steps {
        sh '$VENV/flake8 app tests --output-file=reports/flake8.txt --exit-zero && echo "flake8 issues: $(wc -l < reports/flake8.txt)"'
        script {
          env.SONAR_TOKEN = sh(script: 'cat /var/sonar/token', returnStdout: true).trim()
        }
        sh '''
          docker run --rm --user root --network "${DOCKER_NET}" --volumes-from jenkins \
            -w "${WORKSPACE}" -e SONAR_HOST_URL -e SONAR_TOKEN \
            sonarsource/sonar-scanner-cli:latest \
            -Dsonar.projectBaseDir="${WORKSPACE}" \
            -Dsonar.projectVersion="${VERSION}" \
            -Dsonar.scm.revision="${GIT_COMMIT}"
          python3 scripts/sonar_quality_gate.py
        '''
      }
      post {
        always {
          archiveArtifacts artifacts: 'reports/flake8.txt, reports/sonar-quality-gate.json', allowEmptyArchive: true
        }
      }
    }

    stage('Security') {
      parallel {
        stage('SAST: Bandit') {
          steps {
            sh '''
              $VENV/bandit -r app -f json -o reports/bandit.json --exit-zero
              $VENV/bandit -r app -f html -o reports/bandit.html --exit-zero
              # Gate: fail on any medium or high severity finding
              $VENV/bandit -r app --severity-level medium --confidence-level medium
            '''
          }
        }
        stage('Dependencies: pip-audit') {
          steps {
            sh '''
              $VENV/pip-audit -r requirements.txt -f json -o reports/pip-audit.json || true
              $VENV/pip-audit -r requirements.txt --desc on
            '''
          }
        }
        stage('Image: Trivy') {
          steps {
            sh '''
              TRIVY="docker run --rm -v /var/run/docker.sock:/var/run/docker.sock -v trivy-cache:/root/.cache/ --volumes-from jenkins -w ${WORKSPACE} aquasec/trivy:latest"
              # Full inventory for the report, then the gate: HIGH/CRITICAL with a fix available
              $TRIVY image --quiet --format json -o reports/trivy-image.json "${IMAGE}"
              $TRIVY config --quiet --skip-dirs .venv --format json -o reports/trivy-config.json --exit-code 0 .
              $TRIVY config --quiet --skip-dirs .venv --severity HIGH,CRITICAL --exit-code 0 .
              $TRIVY image --quiet --severity HIGH,CRITICAL --ignore-unfixed \
                --ignorefile .trivyignore --exit-code 1 "${IMAGE}"
            '''
          }
        }
      }
      post {
        always {
          sh 'python3 scripts/security_summary.py || true'
          archiveArtifacts artifacts: 'reports/bandit.*, reports/pip-audit.json, reports/trivy-*.json, reports/security-summary.md',
                           allowEmptyArchive: true
          publishHTML(target: [reportDir: 'reports', reportFiles: 'bandit.html', reportName: 'Bandit report',
                               keepAll: true, allowMissing: true, alwaysLinkToLastBuild: true])
        }
      }
    }

    stage('Deploy: Staging') {
      steps {
        withCredentials([string(credentialsId: 'shelf-staging-secret-key', variable: 'SECRET_KEY'),
                         string(credentialsId: 'shelf-db-password', variable: 'DB_PASSWORD')]) {
          sh '''
            EXPECTED="${VERSION}"
            if [ "${SIMULATE_BAD_DEPLOY}" = "true" ]; then EXPECTED="broken-${VERSION}"; fi
            bash scripts/deploy.sh staging "${IMAGE}" "${EXPECTED}"
          '''
        }
      }
    }

    stage('E2E: Staging') {
      when { expression { params.RUN_E2E } }
      steps {
        sh '''
          docker rm -f "selenium-${BUILD_NUMBER}" >/dev/null 2>&1 || true
          docker run -d --rm --name "selenium-${BUILD_NUMBER}" --network "${DOCKER_NET}" --shm-size=2g \
            selenium/standalone-chrome:latest
        '''
        script {
          try {
            sh '''
              BASE_URL=http://library-staging:8000 \
              SELENIUM_URL="http://selenium-${BUILD_NUMBER}:4444" \
              E2E_SCREENSHOT_DIR=reports/e2e-screenshots \
                $VENV/pytest tests/e2e -m e2e --junitxml=reports/junit-e2e.xml -v
            '''
          } catch (err) {
            withCredentials([string(credentialsId: 'shelf-staging-secret-key', variable: 'SECRET_KEY'),
                             string(credentialsId: 'shelf-db-password', variable: 'DB_PASSWORD')]) {
              sh 'bash scripts/rollback.sh staging || true'
            }
            throw err
          }
        }
      }
      post {
        always {
          sh 'docker rm -f "selenium-${BUILD_NUMBER}" >/dev/null 2>&1 || true'
          junit testResults: 'reports/junit-e2e.xml', allowEmptyResults: true
          archiveArtifacts artifacts: 'reports/e2e-screenshots/**, reports/staging-*.json', allowEmptyArchive: true
        }
      }
    }

    stage('Release: Production') {
      steps {
        script {
          if (!params.AUTO_APPROVE_RELEASE) {
            timeout(time: 30, unit: 'MINUTES') {
              input message: "Promote v${env.VERSION} to production?", ok: 'Release'
            }
          }
        }
        // Promote the exact image that passed staging: same digest, new tags.
        sh '''
          docker tag "${IMAGE}" "${IMAGE_REPO}:prod-${VERSION}"
          docker tag "${IMAGE}" "${IMAGE_REPO}:prod"
          docker push --quiet "${IMAGE_REPO}:prod-${VERSION}"
          docker push --quiet "${IMAGE_REPO}:prod"
        '''
        withCredentials([string(credentialsId: 'shelf-prod-secret-key', variable: 'SECRET_KEY'),
                         string(credentialsId: 'shelf-db-password', variable: 'DB_PASSWORD')]) {
          sh 'bash scripts/deploy.sh production "${IMAGE_REPO}:prod-${VERSION}" "${VERSION}"'
        }
        withCredentials([usernamePassword(credentialsId: 'github-push', usernameVariable: 'GH_USER',
                                          passwordVariable: 'GH_TOKEN')]) {
          sh '''
            PREV_TAG=$(git describe --tags --abbrev=0 2>/dev/null || true)
            {
              echo "# Shelf v${VERSION}"
              echo ""
              echo "- Image: ${IMAGE_REPO}:prod-${VERSION}"
              echo "- Commit: ${GIT_COMMIT}"
              echo "- Build: ${BUILD_URL}"
              echo ""
              echo "## Changes since ${PREV_TAG:-the first release}"
              if [ -n "$PREV_TAG" ]; then git log --pretty='- %h %s (%an)' "${PREV_TAG}..HEAD"; else git log --pretty='- %h %s (%an)' -20; fi
            } > reports/release-notes.md
            cat reports/release-notes.md

            git tag -f -a "v${VERSION}" -m "Release v${VERSION} (build ${BUILD_NUMBER})"
            ORIGIN=$(git config --get remote.origin.url || true)
            case "$ORIGIN" in
              https://github.com/*)
                if [ -n "$GH_TOKEN" ]; then
                  git push "https://${GH_USER}:${GH_TOKEN}@${ORIGIN#https://}" "v${VERSION}" \
                    && echo "Pushed tag v${VERSION} to GitHub"
                else
                  echo "No GitHub token configured; tag v${VERSION} created locally only"
                fi ;;
              *) echo "Origin is ${ORIGIN}; tag v${VERSION} recorded in the Jenkins workspace" ;;
            esac
          '''
        }
      }
      post {
        success {
          archiveArtifacts artifacts: 'reports/release-notes.md, reports/production-*.json', allowEmptyArchive: true
        }
      }
    }

    stage('Monitoring & Alerting') {
      steps {
        withCredentials([string(credentialsId: 'grafana-admin-password', variable: 'GRAFANA_ADMIN_PASSWORD')]) {
          sh '''
            docker compose -p shelf-monitoring -f infra/docker-compose.monitoring.yml up -d --build --wait --wait-timeout 180
            # Reload Prometheus so rule changes in this commit take effect
            curl -fsS -X POST http://prometheus:9090/-/reload || true
            GRAFANA_PASSWORD="${GRAFANA_ADMIN_PASSWORD}" RELEASE_VERSION="${VERSION}" python3 scripts/check_monitoring.py
          '''
        }
        script {
          if (params.SIMULATE_INCIDENT) {
            sh 'python3 scripts/simulate_incident.py outage'
          }
        }
      }
      post {
        always {
          archiveArtifacts artifacts: 'reports/monitoring-check.json', allowEmptyArchive: true
        }
      }
    }
  }

  post {
    success {
      echo """
      ✅ Shelf v${env.VERSION} released
         Production : http://localhost:5000   Staging : http://localhost:5001
         Grafana    : http://localhost:3000   Prometheus : http://localhost:9090
         Alerts     : http://localhost:9093   On-call feed : http://localhost:5055
         SonarQube  : http://localhost:9000/dashboard?id=shelf
      """
      sh '''curl -fsS -X POST http://alert-receiver:5055/events -H 'Content-Type: application/json' \
            -d "{\\"event\\": \\"pipeline\\", \\"status\\": \\"succeeded\\", \\"message\\": \\"Shelf v${VERSION} released to production\\"}" || true'''
    }
    failure {
      echo "❌ Pipeline failed in build #${env.BUILD_NUMBER}. See stage logs and archived reports."
      sh '''curl -fsS -X POST http://alert-receiver:5055/events -H 'Content-Type: application/json' \
            -d "{\\"event\\": \\"pipeline\\", \\"status\\": \\"failed\\", \\"message\\": \\"Build ${BUILD_NUMBER} (v${VERSION}) failed: ${BUILD_URL}\\"}" || true'''
    }
    always {
      archiveArtifacts artifacts: 'reports/*.txt, reports/*.log', allowEmptyArchive: true
    }
    cleanup {
      sh 'docker rm -f "selenium-${BUILD_NUMBER}" >/dev/null 2>&1 || true'
      cleanWs(deleteDirs: true, notFailBuild: true, patterns: [[pattern: '.venv/**', type: 'EXCLUDE']])
    }
  }
}
