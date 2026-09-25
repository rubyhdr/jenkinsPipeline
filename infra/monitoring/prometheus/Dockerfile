# Config is baked into the image so the stack can be started from inside Jenkins (no bind mounts).
FROM prom/prometheus:v3.14.0
COPY prometheus.yml alert.rules.yml /etc/prometheus/
USER nobody
HEALTHCHECK --interval=10s --timeout=3s CMD wget -qO- http://localhost:9090/-/ready || exit 1
