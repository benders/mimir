# Runtime for the Valheim dedicated server + BepInEx. Based on the Dockerfile Iron Gate ships
# inside the server depot. Game files are bind-mounted at run time, never baked in.
FROM --platform=linux/amd64 mirror.gcr.io/library/ubuntu:22.04
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates libatomic1 libpulse0 \
    && rm -rf /var/lib/apt/lists/*
COPY entrypoint.sh /entrypoint.sh
ENTRYPOINT ["/bin/bash", "/entrypoint.sh"]
