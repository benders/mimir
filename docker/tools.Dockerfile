# Build/fetch toolchain, for hosts that only have Docker (CI runners, the remote Linux box).
# Scripts re-exec themselves in here when dotnet/unzip are missing (see in_tools in lib.sh).
FROM mcr.microsoft.com/dotnet/sdk:10.0
RUN apt-get update && apt-get install -y --no-install-recommends unzip python3 python3-venv \
    && rm -rf /var/lib/apt/lists/*
ENV DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_NOLOGO=1
