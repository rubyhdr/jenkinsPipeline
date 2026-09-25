FROM python:3.12-alpine
RUN adduser -D -H receiver
COPY receiver.py /receiver.py
USER receiver
EXPOSE 5055
CMD ["python", "-u", "/receiver.py"]
