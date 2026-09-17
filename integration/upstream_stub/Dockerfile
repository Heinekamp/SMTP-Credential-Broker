FROM python:3.14-slim

RUN apt-get update && apt-get install -y --no-install-recommends openssl \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir aiosmtpd==1.4.6

RUN mkdir -p /certs && openssl req -x509 -newkey rsa:2048 -keyout /certs/stub.key -out /certs/stub.crt \
    -days 3650 -nodes -subj "/CN=upstream-stub"

COPY server.py /server.py

EXPOSE 2525 2526

CMD ["python3", "/server.py"]
