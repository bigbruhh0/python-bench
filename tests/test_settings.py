"""Проверки значений по умолчанию, сохранения и проверки настроек SQLite."""

import pytest

from bench_sim.data.settings import SettingsRepository


def test_settings_are_created_with_defaults_and_persisted(tmp_path) -> None:
    repository = SettingsRepository(tmp_path / "settings.sqlite3")
    defaults = repository.load()
    assert defaults.t_clamp == 5.0
    assert defaults.t_unclamp == 2.0
    assert defaults.error_clamp == "E001"
    assert defaults.error_unclamp == "E002"

    repository.set_value("t_clamp", 7.5)
    assert SettingsRepository(tmp_path / "settings.sqlite3").load().t_clamp == 7.5


def test_timeout_must_be_positive(tmp_path) -> None:
    repository = SettingsRepository(tmp_path / "settings.sqlite3")
    repository.set_value("t_unclamp", 0)

    with pytest.raises(ValueError, match="greater than zero"):
        repository.load()


def test_timeout_must_be_finite(tmp_path) -> None:
    repository = SettingsRepository(tmp_path / "settings.sqlite3")
    repository.set_value("t_clamp", "nan")

    with pytest.raises(ValueError, match="finite"):
        repository.load()
