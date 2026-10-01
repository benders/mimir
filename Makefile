# mimir — Valheim data pipeline. Every target is non-interactive and exits non-zero on failure.
#
# Where the server runs:
#   - REMOTE set (user@host of a native x86_64 Linux box with Docker): `make remote-dump`
#   - x86_64 Linux with Docker: `make dump` directly
#   - macOS: `make dump` uses a qemu x86_64 colima VM (works, but slow)

BRANCH ?= public
REMOTE ?= nic@mini
export MIMIR_BRANCH := $(BRANCH)

.PHONY: help server bepinex plugin dump remote-dump verify check clean decompile

help:
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-12s %s\n", $$1, $$2}'

server: ## Download/update the dedicated server (anonymous Steam)
	scripts/fetch-server.sh

bepinex: ## Download the pinned BepInExPack_Valheim
	scripts/fetch-bepinex.sh >/dev/null

plugin: ## Build the Mimir.Dumper plugin
	scripts/build-plugin.sh >/dev/null

dump: ## Run the server headless here and write .cache/dump/$(BRANCH)/raw
	scripts/dump.sh

remote-dump: ## Run the dump on $(REMOTE) and pull it back
	MIMIR_REMOTE=$(REMOTE) scripts/remote.sh dump

verify: ## Check the dump in .cache/dump/$(BRANCH)/raw
	scripts/verify.py

check: remote-dump verify ## Full end-to-end: dump on $(REMOTE), then verify

decompile: ## Decompile game assemblies to .cache/decompiled (reference only, never commit)
	dotnet tool restore
	for a in assembly_valheim assembly_utils assembly_guiutils; do \
	  dotnet ilspycmd -p -o .cache/decompiled/$$a .cache/server/$(BRANCH)/valheim_server_Data/Managed/$$a.dll >/dev/null; done

clean: ## Remove build outputs and dumps (keeps the server download)
	rm -rf .cache/build .cache/dump
