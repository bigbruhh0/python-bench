"""Проверки обновления панели, автоподтверждения и сохранения настроек."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import Qt
from PyQt5.QtTest import QTest

from bench_sim.logic.controller import ClampController, MachineState
from bench_sim.ui.gui import SimulatorWindow
from bench_sim.hal import MemoryHAL
from bench_sim.data.settings import SettingsRepository


def test_dashboard_updates_signals_state_and_saved_timeouts(qapp, tmp_path) -> None:
    repository = SettingsRepository(tmp_path / "settings.sqlite3")
    hal = MemoryHAL()
    controller = ClampController(hal, repository.load())
    window = SimulatorWindow(controller, hal, repository)
    try:
        window.show()
        QTest.qWait(20)
        assert window.state_label.text() == "Положение не определено"
        window.auto_confirm_button.setChecked(False)

        QTest.mouseClick(window.clamp_button, Qt.LeftButton)
        assert controller.state == MachineState.CLAMPING
        assert hal.read_output("out_clamp") is True
        assert window.output_labels["out_clamp"].text() == "● ВКЛ"

        window.sensor_clamped.setChecked(True)
        assert controller.state == MachineState.CLAMPED
        assert window.state_label.text() == "Зажато"
        assert hal.read_output("status_clamped") is True
        assert hal.read_output("out_clamp") is False

        window.clamp_timeout.setValue(3.5)
        window.unclamp_timeout.setValue(1.5)
        window.clamp_confirm_delay.setValue(0.3)
        window.unclamp_confirm_delay.setValue(0.2)
        QTest.mouseClick(window.save_settings_button, Qt.LeftButton)
        assert repository.load().t_clamp == 3.5
        assert repository.load().t_unclamp == 1.5
        assert repository.load().confirm_clamp_delay == 0.3
        assert repository.load().confirm_unclamp_delay == 0.2
        assert repository.load().auto_confirm is False
    finally:
        window.close()


def test_gui_timer_updates_timeout_without_manual_tick(qapp, tmp_path) -> None:
    repository = SettingsRepository(tmp_path / "settings.sqlite3")
    repository.set_value("t_clamp", 0.1)
    hal = MemoryHAL()
    controller = ClampController(hal, repository.load())
    window = SimulatorWindow(controller, hal, repository)
    try:
        window.show()
        QTest.mouseClick(window.clamp_button, Qt.LeftButton)
        assert controller.state == MachineState.CLAMPING

        QTest.qWait(250)
        assert controller.state == MachineState.ERROR
        assert hal.read_output("error_code") == "E001"
        assert hal.read_output("out_clamp") is False
        assert window.state_label.text() == "Ошибка"
    finally:
        window.close()


def test_auto_confirmation_uses_its_own_delay(qapp, tmp_path) -> None:
    repository = SettingsRepository(tmp_path / "settings.sqlite3")
    repository.set_value("confirm_clamp_delay", 0.1)
    repository.set_value("confirm_unclamp_delay", 0.1)
    hal = MemoryHAL()
    controller = ClampController(hal, repository.load())
    window = SimulatorWindow(controller, hal, repository)
    try:
        window.show()
        assert window.auto_confirm_button.isChecked()
        QTest.mouseClick(window.clamp_button, Qt.LeftButton)
        QTest.qWait(250)

        assert controller.state == MachineState.CLAMPED
        assert hal.read_input("sensor_clamped") is True
        assert hal.read_output("status_clamped") is True
        assert hal.read_output("out_clamp") is False

        QTest.mouseClick(window.unclamp_button, Qt.LeftButton)
        QTest.qWait(250)
        assert controller.state == MachineState.UNCLAMPED
        assert hal.read_input("sensor_clamped") is False
        assert hal.read_input("sensor_unclamped") is True
        assert hal.read_output("status_unclamped") is True
        assert hal.read_output("out_unclamp") is False
    finally:
        window.close()
