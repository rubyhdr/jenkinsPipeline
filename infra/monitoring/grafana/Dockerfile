FROM grafana/grafana:13.2.2
COPY provisioning /etc/grafana/provisioning
COPY dashboards /etc/grafana/dashboards
# 472 is the grafana user in the upstream image.
USER 472
HEALTHCHECK --interval=10s --timeout=3s CMD wget -qO- http://localhost:3000/api/health || exit 1
