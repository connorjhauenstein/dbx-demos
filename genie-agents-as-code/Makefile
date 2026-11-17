# Run `make` to see the commands. TARGET picks the bundle target (default: dev), e.g. `make deploy TARGET=prod`.
# FORCE=1 skips the UI-edit safety checks; NO_COMMIT=1 makes explode leave its changes uncommitted.
TARGET ?= dev
AGENT  ?=
REF    ?=
PYTHON ?= python3
RUN     = $(PYTHON) genie_as_code.py
FLAGS   = --target $(TARGET) $(if $(FORCE),--force)
BUNDLE  = databricks bundle --target $(TARGET)

.DEFAULT_GOAL := help
.PHONY: help install setup build test test-sql deploy eval explode status rollback ci clean

help:  ## Show this list
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F ':.*## ' '{printf "  make %-9s %s\n", $$1, $$2}'

install:  ## Install Python dependencies
	$(PYTHON) -m pip install -r requirements.txt

setup:  ## Create the demo tables, metric views, and functions (separate bundle in demo/)
	cd demo && $(BUNDLE) deploy && $(BUNDLE) run setup_demo_data

build:  ## Turn the agent files into Genie specs and bundle resources (.build/)
	$(RUN) build --target $(TARGET)

test:  ## Check the files offline (no workspace needed)
	$(RUN) test

test-sql:  ## Check the files and run every query on the warehouse
	$(RUN) test --sql --target $(TARGET)

deploy: test build  ## Test, build, and deploy (stops if agents were edited in the UI)
	$(RUN) deploy $(FLAGS)

eval:  ## Run every agent's benchmarks in Genie; fails if any answer is wrong
	$(RUN) evaluate --target $(TARGET)

explode:  ## Pull UI edits into files and commit them: make explode AGENT=growth
	@test -n "$(AGENT)" || (echo "usage: make explode AGENT=<agent>" && exit 1)
	$(RUN) explode $(AGENT) $(FLAGS) $(if $(NO_COMMIT),--no-commit)

status:  ## Show which commit each agent was deployed from, and any UI edits since
	$(RUN) status --target $(TARGET)

rollback:  ## Deploy an earlier commit, without touching your checkout: make rollback REF=<commit>
	@test -n "$(REF)" || (echo "usage: make rollback REF=<commit> [TARGET=...]" && exit 1)
	rm -rf .build/rollback && git worktree add --detach .build/rollback $(REF)
	$(MAKE) -C .build/rollback/$$(git rev-parse --show-prefix) deploy TARGET=$(TARGET) FORCE=$(FORCE); \
	  status=$$?; git worktree remove --force .build/rollback; exit $$status

ci: test-sql deploy eval  ## Everything a pull request should pass

clean:  ## Remove generated files
	rm -rf .build
