# Accepted (docs/SECURITY_FINDINGS.md): one-shot bootstrap that writes the Jenkins token into a
# shared root-owned volume and exits. It has no exposed ports, so a HEALTHCHECK does not apply.
# trivy:ignore:AVD-DS-0002
# trivy:ignore:AVD-DS-0026
FROM python:3.12-alpine
COPY init_sonar.py /init_sonar.py
CMD ["python", "/init_sonar.py"]
