FROM prom/alertmanager:v0.34.1
COPY alertmanager.yml /etc/alertmanager/alertmanager.yml
USER nobody
HEALTHCHECK --interval=10s --timeout=3s CMD wget -qO- http://localhost:9093/-/ready || exit 1
