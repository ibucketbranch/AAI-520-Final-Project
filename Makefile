# Day-to-day commands for the AAI-520 final project repo. Run from the repo root.
.PHONY: setup lint format typecheck test check nb-clean reqs run ui

PYTHON ?= python3.11

setup:            ## create the venv, install the package and hooks
	$(PYTHON) -m venv .venv
	.venv/bin/pip install --upgrade pip
	.venv/bin/pip install -e ".[dev]"
	.venv/bin/python -m spacy download en_core_web_sm
	.venv/bin/pre-commit install

lint:             ## report problems, change nothing
	.venv/bin/ruff check .
	.venv/bin/ruff format --check .

format:           ## fix what ruff can fix
	.venv/bin/ruff check --fix .
	.venv/bin/ruff format .

typecheck:        ## mypy over the package
	.venv/bin/mypy src/

test:             ## pytest with coverage
	.venv/bin/pytest

check: lint typecheck test  ## everything CI runs, in CI order
	.venv/bin/python scripts/check_notebooks_clean.py $$(find notebooks/dev -name '*.ipynb' 2>/dev/null)
	.venv/bin/python scripts/check_ascii.py README.md $$(find docs -name '*.md' 2>/dev/null) $$(find notebooks -name '*.ipynb' 2>/dev/null)
	.venv/bin/pre-commit run gitleaks --all-files

nb-clean:         ## strip outputs from dev notebooks
	.venv/bin/nbstripout notebooks/dev/*.ipynb

reqs:             ## regenerate requirements files from pyproject.toml
	.venv/bin/python -c "import tomllib, pathlib; d = tomllib.load(open('pyproject.toml', 'rb')); p = d['project']; pathlib.Path('requirements.txt').write_text('# Generated from pyproject.toml by make reqs. Do not edit by hand.\n' + '\n'.join(p['dependencies']) + '\n'); pathlib.Path('requirements-dev.txt').write_text('# Generated from pyproject.toml by make reqs. Do not edit by hand.\n-r requirements.txt\n' + '\n'.join(p['optional-dependencies']['dev']) + '\n')"

run:              ## show the CLI help
	.venv/bin/python -m investment_committee --help

ui:               ## start the local Streamlit interface
	.venv/bin/streamlit run app.py
