# mimir — Valheim data pipeline. Every target is non-interactive and exits non-zero on failure.
#
# Where the server runs:
#   - REMOTE set (user@host of a native x86_64 Linux box with Docker): `make remote-dump`
#   - x86_64 Linux with Docker: `make dump` directly
#   - macOS: `make dump` uses a qemu x86_64 colima VM (works, but slow)

BRANCH ?= public
REMOTE ?= nic@mini
export MIMIR_BRANCH := $(BRANCH)

.PHONY: help server bepinex plugin dump icons extract remote-extract verify data verify-data check clean decompile

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

icons: ## Extract icons referenced by the dump -> .cache/dump/$(BRANCH)/icons
	scripts/icons.sh

extract: dump icons ## dump + icons on this host

remote-extract: ## Run dump + icons on $(REMOTE) and pull the results back
	MIMIR_REMOTE=$(REMOTE) scripts/remote.sh extract

verify: ## Check the dump (and icons) in .cache/dump/$(BRANCH)
	scripts/verify.py

DATA_DIR := $(if $(filter public,$(BRANCH)),data,.cache/data/$(BRANCH))

data: ## Normalize the raw dump -> data/ (public) or .cache/data/$(BRANCH)
	scripts/normalize.py .cache/dump/$(BRANCH)/raw $(DATA_DIR)

verify-data: ## Check normalized data (+ icons, if extracted)
	scripts/verify_data.py $(DATA_DIR) .cache/dump/$(BRANCH)/icons

check: remote-extract verify data verify-data ## Full end-to-end on $(REMOTE): extract, verify, normalize, verify

decompile: ## Decompile game assemblies to .cache/decompiled (reference only, never commit)
	dotnet tool restore
	for a in assembly_valheim assembly_utils assembly_guiutils; do \
	  dotnet ilspycmd -p -o .cache/decompiled/$$a .cache/server/$(BRANCH)/valheim_server_Data/Managed/$$a.dll >/dev/null; done

clean: ## Remove build outputs and dumps (keeps the server download)
	rm -rf .cache/build .cache/dump
