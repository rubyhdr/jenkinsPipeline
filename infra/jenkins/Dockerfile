# Jenkins controller with everything the Shelf pipeline needs:
# Docker CLI + Compose (talks to the host daemon via the mounted socket), Python 3, git, curl, jq.
FROM docker:cli AS dockercli

FROM jenkins/jenkins:lts-jdk21

USER root
RUN apt-get update \
 && apt-get install -y --no-install-recommends python3 python3-venv python3-pip curl jq git ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && git config --system safe.directory '*' \
 && git config --system user.name "Jenkins" \
 && git config --system user.email "jenkins@shelf.local"

COPY --from=dockercli /usr/local/bin/docker /usr/local/bin/docker
COPY --from=dockercli /usr/local/libexec/docker/cli-plugins/ /usr/local/libexec/docker/cli-plugins/

COPY plugins.txt /usr/share/jenkins/ref/plugins.txt
RUN jenkins-plugin-cli --plugin-file /usr/share/jenkins/ref/plugins.txt

COPY casc.yaml /usr/share/jenkins/ref/casc.yaml
ENV CASC_JENKINS_CONFIG=/usr/share/jenkins/ref/casc.yaml \
    JAVA_OPTS="-Djenkins.install.runSetupWizard=false -Dhudson.plugins.git.GitSCM.ALLOW_LOCAL_CHECKOUT=true"
