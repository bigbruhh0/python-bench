"""Загрузка, проверка и сохранение настроек симулятора в SQLite."""

import sqlite3
import math
from dataclasses import dataclass
from pathlib import Path

DEFAULTS: dict[str, str] = {
    # SQLite хранит настройки как текст; числовые значения преобразуются и проверяются при загрузке.
    "t_clamp": "5.0",
    "t_unclamp": "2.0",
    "error_clamp": "E001",
    "error_unclamp": "E002",
    "error_conflict": "E003",
    "confirm_clamp_delay": "1.0",
    "confirm_unclamp_delay": "0.5",
    "auto_confirm": "1",
}


@dataclass(frozen=True)
class MachineSettings:
    """Неизменяемый набор настроек, который контроллер получает при старте."""

    t_clamp: float
    t_unclamp: float
    error_clamp: str
    error_unclamp: str
    error_conflict: str
    confirm_clamp_delay: float = 1.0
    confirm_unclamp_delay: float = 0.5
    auto_confirm: bool = True


class SettingsRepository:
    """Небольшой слой доступа к таблице ключ-значение в SQLite."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.database_path)

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            # OR IGNORE добавляет новые настройки, но не затирает пользовательские значения.
            connection.executemany(
                "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                DEFAULTS.items(),
            )

    def load(self) -> MachineSettings:
        with self._connect() as connection:
            values = DEFAULTS | dict(connection.execute("SELECT key, value FROM settings"))
        try:
            t_clamp = float(values["t_clamp"])
            t_unclamp = float(values["t_unclamp"])
            confirm_clamp_delay = float(values["confirm_clamp_delay"])
            confirm_unclamp_delay = float(values["confirm_unclamp_delay"])
        except (KeyError, ValueError) as error:
            raise ValueError("Timeout and confirmation settings must be valid numbers") from error
        if not math.isfinite(t_clamp) or not math.isfinite(t_unclamp):
            raise ValueError("Timeout settings must be finite numbers")
        if t_clamp <= 0 or t_unclamp <= 0:
            raise ValueError("Timeout settings must be greater than zero")
        # Подтверждение датчика — задержка симуляции, отдельная от таймаута движения.
        if not math.isfinite(confirm_clamp_delay) or not math.isfinite(confirm_unclamp_delay):
            raise ValueError("Confirmation delays must be finite numbers")
        if confirm_clamp_delay < 0 or confirm_unclamp_delay < 0:
            raise ValueError("Confirmation delays cannot be negative")
        error_codes = (values["error_clamp"], values["error_unclamp"], values["error_conflict"])
        if any(not code.strip() for code in error_codes):
            raise ValueError("Error codes must not be empty")
        auto_confirm_value = values["auto_confirm"].strip().lower()
        if auto_confirm_value not in {"0", "1", "false", "true"}:
            raise ValueError("auto_confirm must be true or false")
        return MachineSettings(
            t_clamp=t_clamp,
            t_unclamp=t_unclamp,
            error_clamp=values["error_clamp"],
            error_unclamp=values["error_unclamp"],
            error_conflict=values["error_conflict"],
            confirm_clamp_delay=confirm_clamp_delay,
            confirm_unclamp_delay=confirm_unclamp_delay,
            auto_confirm=auto_confirm_value in {"1", "true"},
        )

    def set_value(self, key: str, value: str | float) -> None:
        if key not in DEFAULTS:
            raise KeyError(f"Unknown setting: {key}")
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, str(value)),
            )
