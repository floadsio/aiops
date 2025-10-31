UV ?= uv
PYTHON_SPEC ?= 3.12
VENV_DIR ?= .venv
VENV_BIN ?= $(VENV_DIR)/bin
PYTHON ?= $(VENV_BIN)/python
FLASK ?= $(VENV_BIN)/flask
PID_FILE ?= .aiops.pid
FLASK_APP ?= manage.py
FLASK_HOST ?= 127.0.0.1
FLASK_PORT ?= 8060

.PHONY: all venv sync sync-dev seed seed-identities format lint test check clean start stop restart status

all: sync-dev start

$(VENV_DIR)/pyvenv.cfg:
	$(UV) venv --python $(PYTHON_SPEC) $(VENV_DIR)

venv: $(VENV_DIR)/pyvenv.cfg

sync: venv
	$(UV) pip sync --python $(VENV_DIR) requirements.txt

sync-dev: venv
	$(UV) pip sync --python $(VENV_DIR) requirements-dev.txt

seed: sync-dev
	@if [ -z "$(AIOPS_ADMIN_EMAIL)" ]; then \
		echo "AIOPS_ADMIN_EMAIL is required for make seed"; exit 1; \
	fi
	$(VENV_BIN)/flask --app $(FLASK_APP) db upgrade
	$(VENV_BIN)/flask --app $(FLASK_APP) seed-data --owner-email $(AIOPS_ADMIN_EMAIL)

seed-identities: sync-dev
	@if [ -z "$(AIOPS_ADMIN_EMAIL)" ]; then \
		echo "AIOPS_ADMIN_EMAIL is required for make seed-identities"; exit 1; \
	fi
	$(VENV_BIN)/flask --app $(FLASK_APP) seed-identities --owner-email $(AIOPS_ADMIN_EMAIL) $(if $(SEED_SOURCE),--source-dir $(SEED_SOURCE),)

format:
	$(VENV_BIN)/ruff check --select I --fix .
	$(VENV_BIN)/ruff format .

lint:
	$(VENV_BIN)/ruff check .
	$(VENV_BIN)/mypy app

test:
	$(VENV_BIN)/pytest

check: lint test

start:
	@if [ -f $(PID_FILE) ] && kill -0 $$(cat $(PID_FILE)) >/dev/null 2>&1; then \
		echo "aiops already running (PID $$(cat $(PID_FILE)))"; \
	else \
		if lsof -ti tcp:$(FLASK_PORT) >/dev/null 2>&1; then \
			PORT_PID=$$(lsof -ti tcp:$(FLASK_PORT)); \
			if [ "$${FORCE_PORT_KILL}" = "1" ]; then \
				echo "Port $(FLASK_PORT) is in use by PID $$PORT_PID; terminating due to FORCE_PORT_KILL=1."; \
				kill $$PORT_PID || true; \
				sleep 1; \
				if lsof -ti tcp:$(FLASK_PORT) >/dev/null 2>&1; then \
					echo "Failed to free port $(FLASK_PORT). Stop PID $$PORT_PID manually."; \
					exit 1; \
				fi; \
			else \
				echo "Port $(FLASK_PORT) is already in use by PID $$PORT_PID. Stop that process, set FORCE_PORT_KILL=1, or set FLASK_PORT to a free port."; \
				exit 1; \
			fi; \
		fi; \
		echo "Starting aiops on $(FLASK_HOST):$(FLASK_PORT)"; \
		($(VENV_BIN)/flask --app $(FLASK_APP) run --host $(FLASK_HOST) --port $(FLASK_PORT) >/tmp/aiops.log 2>&1 & echo $$! > $(PID_FILE)); \
		sleep 1; \
		if kill -0 $$(cat $(PID_FILE)) >/dev/null 2>&1; then \
			echo "aiops started (PID $$(cat $(PID_FILE)))"; \
		else \
			echo "Failed to start aiops. See /tmp/aiops.log"; \
			rm -f $(PID_FILE); \
			exit 1; \
		fi; \
	fi

stop:
	@if [ -f $(PID_FILE) ]; then \
		if kill -0 $$(cat $(PID_FILE)) >/dev/null 2>&1; then \
			echo "Stopping aiops (PID $$(cat $(PID_FILE)))"; \
			kill $$(cat $(PID_FILE)) && rm -f $(PID_FILE); \
		else \
			echo "Stale PID file detected; removing"; \
			rm -f $(PID_FILE); \
		fi; \
	else \
		if lsof -ti tcp:$(FLASK_PORT) >/dev/null 2>&1; then \
			PORT_PID=$$(lsof -ti tcp:$(FLASK_PORT)); \
			if [ "$${FORCE_PORT_KILL}" = "1" ]; then \
				echo "Port $(FLASK_PORT) is in use by PID $$PORT_PID; terminating due to FORCE_PORT_KILL=1."; \
				kill $$PORT_PID || true; \
			else \
				echo "aiops PID file missing, but port $(FLASK_PORT) is used by PID $$PORT_PID. Stop it manually, set FORCE_PORT_KILL=1, or choose another port."; \
			fi; \
		else \
			echo "aiops not running"; \
		fi; \
	fi

restart: stop start

status:
	@if [ -f $(PID_FILE) ] && kill -0 $$(cat $(PID_FILE)) >/dev/null 2>&1; then \
		echo "aiops running (PID $$(cat $(PID_FILE)))"; \
	elif [ -f $(PID_FILE) ]; then \
		echo "aiops not running (stale PID file)"; \
	else \
		echo "aiops not running"; \
	fi

clean:
	find . -type d -name "__pycache__" -prune -exec rm -rf {} +
	rm -rf .pytest_cache .mypy_cache $(PID_FILE)
