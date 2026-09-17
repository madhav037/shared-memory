# pg_dump must match the Postgres major version in compose.yaml.
FROM postgres:17

RUN apt-get update \
    && apt-get install -y --no-install-recommends git openssh-client ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY backup.sh /usr/local/bin/backup
RUN chmod +x /usr/local/bin/backup

HEALTHCHECK --interval=1h --start-period=1m CMD ["backup", "health"]
ENTRYPOINT ["backup"]
CMD ["schedule"]
