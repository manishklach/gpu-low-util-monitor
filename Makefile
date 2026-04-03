PYTHON ?= python

.PHONY: test
test:
	$(PYTHON) -m pytest

.PHONY: simulate-once
simulate-once:
	$(PYTHON) -m gpu_low_util_monitor --simulate --once --verbose

.PHONY: simulate
simulate:
	$(PYTHON) -m gpu_low_util_monitor --simulate --out-dir ./out --jsonl --csv
