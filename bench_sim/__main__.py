"""Точка запуска: создаёт настройки, HAL, контроллер и выбирает GUI или CLI."""

import argparse
import logging
from pathlib import Path

from bench_sim.ui.cli import run_console
from bench_sim.logic.controller import ClampController
from bench_sim.hal import MemoryHAL
from bench_sim.data.settings import SettingsRepository


def main() -> None:
    parser = argparse.ArgumentParser(description="Pneumatic clamp simulator")
    parser.add_argument("--cli", action="store_true", help="run the terminal interface")
    arguments = parser.parse_args()

    project_root = Path(__file__).resolve().parent.parent
    logging.basicConfig(
        filename=project_root / "bench.log",
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    settings = SettingsRepository(project_root / "settings.sqlite3").load()
    hal = MemoryHAL()
    controller = ClampController(hal, settings)
    if arguments.cli:
        # GUI запускается по умолчанию; флаг --cli выбирает консольный сценарий.
        run_console(controller, hal)
    else:
        from bench_sim.ui.gui import run_gui

        raise SystemExit(run_gui(controller, hal, SettingsRepository(project_root / "settings.sqlite3")))


if __name__ == "__main__":
    main()
