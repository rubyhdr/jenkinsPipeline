FROM python:3.12-alpine
RUN adduser -D -H receiver
COPY receiver.py /receiver.py
USER receiver
EXPOSE 5055
HEALTHCHECK --interval=10s --timeout=3s CMD wget -qO- http://localhost:5055/health || exit 1
CMD ["python", "-u", "/receiver.py"]
