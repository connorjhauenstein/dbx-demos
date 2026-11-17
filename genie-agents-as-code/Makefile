# Run `make` to see the commands. TARGET picks the bundle target (default: dev), e.g. `make deploy TARGET=prod`.
TARGET ?= dev
AGENT  ?=
PYTHON ?= python3
RUN     = $(PYTHON) genie_as_code.py
BUNDLE  = databricks bundle --target $(TARGET)

.DEFAULT_GOAL := help
.PHONY: help install setup build test test-sql deploy eval explode ci clean

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

deploy: test build  ## Test, build, and deploy the agents
	$(BUNDLE) deploy

eval:  ## Run every agent's benchmarks in Genie; fails if any answer is wrong
	$(RUN) evaluate --target $(TARGET)

explode:  ## Pull UI edits back into files: make explode AGENT=growth
	@test -n "$(AGENT)" || (echo "usage: make explode AGENT=<agent>" && exit 1)
	$(RUN) explode $(AGENT) --target $(TARGET)

ci: test-sql deploy eval  ## Everything a pull request should pass

clean:  ## Remove generated files
	rm -rf .build
