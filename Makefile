# mimir — Valheim data pipeline. Every target is non-interactive and exits non-zero on failure.
#
# Where the server runs:
#   - REMOTE set (user@host of a native x86_64 Linux box with Docker): `make remote-dump`
#   - x86_64 Linux with Docker: `make dump` directly
#   - macOS: `make dump` uses a qemu x86_64 colima VM (works, but slow)

BRANCH ?= public
REMOTE ?= nic@mini
export MIMIR_BRANCH := $(BRANCH)

.PHONY: help server buildid bepinex plugin dump icons extract remote-extract verify data verify-data site serve test check check-local clean decompile

help:
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-12s %s\n", $$1, $$2}'

server: ## Download/update the dedicated server (anonymous Steam)
	scripts/fetch-server.sh

buildid: ## Print the Steam build id of the public server (steamcmd; needs x86_64)
	@scripts/steam-buildid.sh

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

SITE_DIR := .cache/site/$(BRANCH)

site: ## Build the static site from $(DATA_DIR) + icons -> .cache/site/$(BRANCH)
	scripts/build-site.py $(DATA_DIR) .cache/dump/$(BRANCH)/icons $(SITE_DIR)

serve: site ## Build the site and serve it on http://localhost:8000
	python3 -m http.server -d $(SITE_DIR) 8000

test: ## Offline tests: unit + golden files (tests/), site smoke test, verify committed data/
	python3 -m unittest discover -s tests
	scripts/verify_data.py data .cache/no-icons

check: remote-extract verify data verify-data ## Full end-to-end on $(REMOTE): extract, verify, normalize, verify

check-local: test extract verify data verify-data site ## Tests, then full end-to-end on this x86_64 Linux host + site (CI)

decompile: ## Decompile game assemblies to .cache/decompiled (reference only, never commit)
	dotnet tool restore
	for a in assembly_valheim assembly_utils assembly_guiutils; do \
	  dotnet ilspycmd -p -o .cache/decompiled/$$a .cache/server/$(BRANCH)/valheim_server_Data/Managed/$$a.dll >/dev/null; done

clean: ## Remove build outputs and dumps (keeps the server download)
	rm -rf .cache/build .cache/dump .cache/site
