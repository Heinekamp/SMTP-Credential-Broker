FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends openssl \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir aiosmtpd==1.4.6

# Self-signed, valid for the `upstream-stub` service name only. It's
# published to the shared `upstream_ca_test` volume at startup (CMD below)
# and the relay is pointed at it via RELAY_UPSTREAM_TLS_CA_FILE, so Postfix
# and the app verify it exactly as they would a real provider's
# certificate (#153). The `upstream-stub-mismatch` network alias reaches
# this same server under a name the certificate doesn't cover, for the
# hostname-verification tests.
RUN mkdir -p /certs && openssl req -x509 -newkey rsa:2048 -keyout /certs/stub.key -out /certs/stub.crt \
    -days 3650 -nodes -subj "/CN=upstream-stub" -addext "subjectAltName=DNS:upstream-stub"

COPY server.py /server.py

EXPOSE 2525 2526

CMD ["sh", "-c", "cp /certs/stub.crt /upstream-ca/stub.crt && exec python3 /server.py"]
