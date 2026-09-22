# Thin façade over developer/tasks.py so Unix developers can use make.
# Windows developers run the same tasks directly:  py developer\tasks.py test
PY ?= python3
TASKS := $(PY) developer/tasks.py

.PHONY: help test e2e check manifest manifest-check lint fetch run clean ci

help:
	@$(TASKS) --help

test:            ; $(TASKS) test
e2e:             ; $(TASKS) e2e
check:           ; $(TASKS) check
manifest:        ; $(TASKS) manifest
manifest-check:  ; $(TASKS) manifest --check
lint:            ; $(TASKS) lint
fetch:           ; $(TASKS) fetch
run:             ; $(TASKS) run
clean:           ; $(TASKS) clean
ci:              ; $(TASKS) ci
