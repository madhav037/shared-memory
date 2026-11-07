# pg_dump must match the Postgres major version in compose.yaml.
# Pinned, so its layers stay the ones the server has and a deploy needn't send them; Dependabot moves the pin.
FROM postgres:17@sha256:748a18a54d3842d43bc156f0840d78029b8d349e0feca98c12b9c4ce3404a6b3

# age encrypts the backup before it leaves the server. The release is pinned, and each download is checked against
# the SHA-256 of the release archive (amd64 and arm64), so a changed archive fails the build.
ARG TARGETARCH
ARG AGE_VERSION=1.2.1
ARG AGE_SHA256_AMD64=7df45a6cc87d4da11cc03a539a7470c15b1041ab2b396af088fe9990f7c79d50
ARG AGE_SHA256_ARM64=57fd79a7ece5fe501f351b9dd51a82fbee1ea8db65a8839db17f5c080245e99f

RUN apt-get update \
    && apt-get install -y --no-install-recommends git openssh-client ca-certificates curl \
    && arch="${TARGETARCH:-$(dpkg --print-architecture)}" \
    && case "$arch" in amd64) sha="$AGE_SHA256_AMD64" ;; arm64) sha="$AGE_SHA256_ARM64" ;; *) echo "no age for $arch" >&2; exit 1 ;; esac \
    && curl -fsSL -o /tmp/age.tgz "https://github.com/FiloSottile/age/releases/download/v${AGE_VERSION}/age-v${AGE_VERSION}-linux-${arch}.tar.gz" \
    && echo "${sha}  /tmp/age.tgz" | sha256sum -c - \
    && tar -xzf /tmp/age.tgz -C /usr/local/bin --strip-components=1 age/age age/age-keygen \
    && rm /tmp/age.tgz \
    && apt-get purge -y --auto-remove curl \
    && rm -rf /var/lib/apt/lists/*
COPY backup.sh /usr/local/bin/backup
RUN chmod +x /usr/local/bin/backup

HEALTHCHECK --interval=1h --start-period=1m CMD ["backup", "health"]
ENTRYPOINT ["backup"]
CMD ["schedule"]
