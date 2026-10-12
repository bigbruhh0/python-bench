"""Сборка компонентов симулятора и запуск выбранного интерфейса."""

import argparse
import logging
from pathlib import Path

from bench_sim.data.settings import SettingsRepository
from bench_sim.hal import MemoryHAL
from bench_sim.logic.controller import ClampController
from bench_sim.ui.cli import run_console


def main() -> int:
    parser = argparse.ArgumentParser(description="Pneumatic clamp simulator")
    parser.add_argument("--cli", action="store_true", help="run the terminal interface")
    arguments = parser.parse_args()

    project_root = Path(__file__).resolve().parent.parent
    settings_path = project_root / "settings.sqlite3"
    logging.basicConfig(
        filename=project_root / "bench.log",
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    settings_repository = SettingsRepository(settings_path)
    settings = settings_repository.load()
    hal = MemoryHAL()
    controller = ClampController(hal, settings)

    if arguments.cli:
        # GUI запускается по умолчанию; флаг --cli выбирает консольный сценарий.
        run_console(controller, hal)
        return 0

    from bench_sim.ui.gui import run_gui

    return run_gui(controller, hal, settings_repository)
