# Valve's steamcmd, only used to read app info (build ids) anonymously. 32-bit, so it needs real x86_64
# (it segfaults under Rosetta, like the server).
FROM --platform=linux/amd64 mirror.gcr.io/library/ubuntu:22.04
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl lib32gcc-s1 \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /opt/steamcmd \
    && curl -fsSL https://steamcdn-a.akamaihd.net/client/installer/steamcmd_linux.tar.gz | tar -xz -C /opt/steamcmd \
    && /opt/steamcmd/steamcmd.sh +quit >/dev/null
ENTRYPOINT ["/opt/steamcmd/steamcmd.sh"]
