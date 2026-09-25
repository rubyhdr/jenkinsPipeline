# Config is baked into the image so the stack can be started from inside Jenkins (no bind mounts).
FROM prom/prometheus:latest
COPY prometheus.yml alert.rules.yml /etc/prometheus/
