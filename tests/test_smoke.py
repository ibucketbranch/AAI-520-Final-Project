"""Smoke tests: the package imports, the CLI runs, and no key value leaks."""

import investment_committee
from investment_committee.cli import main
from investment_committee.config import MissingKeyError, load_settings

FAKE_KEY_VALUE = "sk-test-not-a-real-key-value-1234567890"


def test_package_imports():
    assert investment_committee.__version__


def test_cli_runs_without_env(capsys):
    exit_code = main(["NFLX"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "NFLX" in out
    assert "not implemented" in out.lower()


def test_cli_reports_key_names_not_values(monkeypatch, capsys):
    monkeypatch.setenv("OPENAI_API_KEY", FAKE_KEY_VALUE)
    exit_code = main(["NFLX"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "OPENAI_API_KEY: set" in out
    assert FAKE_KEY_VALUE not in out


def test_require_names_the_missing_key():
    settings = load_settings()
    try:
        settings.require("NEWSAPI_KEY")
    except MissingKeyError as error:
        assert "NEWSAPI_KEY" in str(error)
    else:
        raise AssertionError("require() should raise when the key is unset")


def test_require_returns_value_when_set(monkeypatch):
    monkeypatch.setenv("FRED_API_KEY", FAKE_KEY_VALUE)
    settings = load_settings()
    assert settings.require("FRED_API_KEY") == FAKE_KEY_VALUE
