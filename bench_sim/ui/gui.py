"""Графическая панель: команды, сигналы HAL, состояние цилиндра и журнал.

Контроллер здесь только вызывается, но логика конечного автомата находится
в controller.py. GUI также имитирует срабатывание датчика в режиме автоподтверждения.
"""

import logging
import sqlite3
import sys

from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QObject
from PyQt5.QtGui import QTextCursor
from PyQt5.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from bench_sim.logic.controller import ClampController, MachineState
from bench_sim.hal import MemoryHAL
from bench_sim.data.settings import SettingsRepository


STATE_LABELS = {
    MachineState.IDLE: "Положение не определено",
    MachineState.CLAMPING: "Зажатие",
    MachineState.UNCLAMPING: "Разжатие",
    MachineState.CLAMPED: "Зажато",
    MachineState.UNCLAMPED: "Разжато",
    MachineState.ERROR: "Ошибка",
}


class _LogBridge(QObject):
    message = pyqtSignal(str)


class _QtLogHandler(logging.Handler):
    def __init__(self, bridge: _LogBridge) -> None:
        super().__init__(logging.INFO)
        self.bridge = bridge
        self.setFormatter(logging.Formatter("%(asctime)s  %(levelname)s  %(message)s", "%H:%M:%S"))

    def emit(self, record: logging.LogRecord) -> None:
        self.bridge.message.emit(self.format(record))


class SimulatorWindow(QMainWindow):
    """Главное окно симулятора с настройками, индикаторами и журналом событий."""

    def __init__(
        self,
        controller: ClampController,
        hal: MemoryHAL,
        settings_repository: SettingsRepository,
    ) -> None:
        super().__init__()
        self.controller = controller
        self.hal = hal
        self.settings_repository = settings_repository
        self.setWindowTitle("Симулятор пневмоцилиндра")
        self.resize(1050, 760)
        self._build_ui()
        self._connect_logging()

        self.timer = QTimer(self)
        self.timer.setInterval(50)
        self.timer.timeout.connect(self._on_timer)
        self.timer.start()
        self._refresh()

    def _build_ui(self) -> None:
        central = QWidget(self)
        root = QVBoxLayout(central)

        heading = QHBoxLayout()
        title = QLabel("Пневмоцилиндр · симуляция HAL", central)
        title.setStyleSheet("font-size: 20px; font-weight: bold")
        self.state_label = QLabel(central)
        self.state_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.state_label.setStyleSheet("font-size: 18px; font-weight: bold")
        heading.addWidget(title)
        heading.addStretch(1)
        heading.addWidget(self.state_label)
        root.addLayout(heading)

        self.error_banner = QLabel("Ошибок нет", central)
        self.error_banner.setAlignment(Qt.AlignCenter)
        self.error_banner.setMinimumHeight(34)
        self.error_banner.setStyleSheet("background: #e8f5e9; color: #1b5e20; padding: 6px")
        root.addWidget(self.error_banner)

        # Таймер показывает оставшееся время до ошибки, а не длительность движения.
        operation_box = QGroupBox("Таймер операции", central)
        operation_layout = QVBoxLayout(operation_box)
        self.operation_label = QLabel("Операция не выполняется", operation_box)
        self.progress_bar = QProgressBar(operation_box)
        self.progress_bar.setRange(0, 1000)
        self.progress_bar.setTextVisible(False)
        self.timer_label = QLabel("", operation_box)
        operation_layout.addWidget(self.operation_label)
        operation_layout.addWidget(self.progress_bar)
        operation_layout.addWidget(self.timer_label)
        root.addWidget(operation_box)

        signal_layout = QGridLayout()
        inputs_box = QGroupBox("Входы HAL", central)
        inputs_layout = QVBoxLayout(inputs_box)
        command_row = QHBoxLayout()
        self.clamp_button = QPushButton("Команда зажать", inputs_box)
        self.unclamp_button = QPushButton("Команда разжать", inputs_box)
        self.clamp_button.clicked.connect(lambda: self._pulse_command("cmd_clamp"))
        self.unclamp_button.clicked.connect(lambda: self._pulse_command("cmd_unclamp"))
        command_row.addWidget(self.clamp_button)
        command_row.addWidget(self.unclamp_button)
        inputs_layout.addLayout(command_row)
        self.sensor_clamped = QCheckBox("sensor_clamped", inputs_box)
        self.sensor_unclamped = QCheckBox("sensor_unclamped", inputs_box)
        self.sensor_clamped.toggled.connect(
            lambda value: self._set_sensor("sensor_clamped", value)
        )
        self.sensor_unclamped.toggled.connect(
            lambda value: self._set_sensor("sensor_unclamped", value)
        )
        inputs_layout.addWidget(self.sensor_clamped)
        inputs_layout.addWidget(self.sensor_unclamped)
        self.command_status = QLabel("cmd_clamp=0  ·  cmd_unclamp=0", inputs_box)
        inputs_layout.addWidget(self.command_status)

        outputs_box = QGroupBox("Симулятор · состояние", central)
        outputs_layout = QFormLayout(outputs_box)
        self.output_labels: dict[str, QLabel] = {}
        for signal_name, label in (
            ("out_clamp", "Клапан зажатия"),
            ("out_unclamp", "Клапан разжатия"),
        ):
            value_label = QLabel("", outputs_box)
            self.output_labels[signal_name] = value_label
            outputs_layout.addRow(label, value_label)
        self.simulator_status = QLabel("", outputs_box)
        outputs_layout.addRow("Статус", self.simulator_status)

        signal_layout.addWidget(inputs_box, 0, 0)
        signal_layout.addWidget(outputs_box, 0, 1)
        root.addLayout(signal_layout)

        # Таймауты операции и задержки имитации датчиков — разные настройки.
        settings_box = QGroupBox("Симулятор · настройки", central)
        settings_layout = QGridLayout(settings_box)
        self.clamp_timeout = self._make_timeout_spin(self.controller.settings.t_clamp)
        self.unclamp_timeout = self._make_timeout_spin(self.controller.settings.t_unclamp)
        self.clamp_confirm_delay = self._make_timeout_spin(
            self.controller.settings.confirm_clamp_delay, allow_zero=True,
        )
        self.unclamp_confirm_delay = self._make_timeout_spin(
            self.controller.settings.confirm_unclamp_delay, allow_zero=True,
        )
        self.auto_confirm_button = QPushButton("Подтверждать автоматически", settings_box)
        self.auto_confirm_button.setCheckable(True)
        self.auto_confirm_button.setChecked(self.controller.settings.auto_confirm)
        self.auto_confirm_button.toggled.connect(self._auto_confirm_toggled)
        self._style_auto_confirm_button(self.auto_confirm_button.isChecked())
        timeout_heading = QLabel("Таймауты операций", settings_box)
        timeout_heading.setStyleSheet("font-weight: bold")
        confirmation_heading = QLabel("Автоподтверждение датчиков", settings_box)
        confirmation_heading.setStyleSheet("font-weight: bold")
        settings_layout.addWidget(timeout_heading, 0, 0, 1, 2)
        settings_layout.addWidget(QLabel("Зажатие T_clamp:"), 1, 0)
        settings_layout.addWidget(self.clamp_timeout, 1, 1)
        settings_layout.addWidget(QLabel("Разжатие T_unclamp:"), 2, 0)
        settings_layout.addWidget(self.unclamp_timeout, 2, 1)
        settings_layout.addWidget(confirmation_heading, 0, 2, 1, 2)
        settings_layout.addWidget(self.auto_confirm_button, 1, 2, 1, 2)
        settings_layout.addWidget(QLabel("Зажатие через:"), 2, 2)
        settings_layout.addWidget(self.clamp_confirm_delay, 2, 3)
        settings_layout.addWidget(QLabel("Разжатие через:"), 3, 2)
        settings_layout.addWidget(self.unclamp_confirm_delay, 3, 3)
        self.save_settings_button = QPushButton("Сохранить", settings_box)
        self.save_settings_button.clicked.connect(self._save_settings)
        settings_layout.addWidget(self.save_settings_button, 3, 0, 1, 2)
        root.addWidget(settings_box)

        log_box = QGroupBox("Журнал событий", central)
        log_layout = QVBoxLayout(log_box)
        self.log_view = QPlainTextEdit(log_box)
        self.log_view.setReadOnly(True)
        self.log_view.document().setMaximumBlockCount(500)
        log_layout.addWidget(self.log_view)
        root.addWidget(log_box, 1)

        footer = QHBoxLayout()
        footer.addWidget(QLabel("Ошибка остаётся до сброса после устранения причины.", central))
        footer.addStretch(1)
        self.full_logs_button = QPushButton("Посмотреть полные логи", central)
        self.full_logs_button.clicked.connect(self._open_full_logs)
        footer.addWidget(self.full_logs_button)
        self.reset_button = QPushButton("Сбросить ошибку", central)
        self.reset_button.clicked.connect(self._reset_error)
        footer.addWidget(self.reset_button)
        root.addLayout(footer)

        self.setCentralWidget(central)
        self.statusBar().hide()

    @staticmethod
    def _make_timeout_spin(value: float, *, allow_zero: bool = False) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(0.0 if allow_zero else 0.1, 3600.0)
        spin.setDecimals(1)
        spin.setSingleStep(0.5)
        spin.setSuffix(" с")
        spin.setValue(value)
        return spin

    def _connect_logging(self) -> None:
        self._log_bridge = _LogBridge(self)
        self._log_bridge.message.connect(self.log_view.appendPlainText)
        self._log_handler = _QtLogHandler(self._log_bridge)
        logging.getLogger().addHandler(self._log_handler)

    def _pulse_command(self, signal_name: str) -> None:
        # Контроллер реагирует на фронт команды, поэтому кнопка создаёт короткий импульс.
        self.hal.set_input(signal_name, True)
        self.controller.tick()
        self.hal.set_input(signal_name, False)
        self.controller.tick()
        self._refresh()

    def _set_sensor(self, signal_name: str, value: bool) -> None:
        self.hal.set_input(signal_name, value)
        self.controller.tick()
        self._refresh()

    def _on_timer(self) -> None:
        self.controller.tick()
        self._apply_auto_confirmation()
        # После имитации датчика проверяем его сразу, не ожидая следующего 50-мс цикла.
        self.controller.tick()
        self._refresh()

    def _apply_auto_confirmation(self) -> None:
        if not self.auto_confirm_button.isChecked():
            return
        if self.controller.state == MachineState.CLAMPING:
            delay = self.controller.settings.confirm_clamp_delay
            target_sensor, opposite_sensor = "sensor_clamped", "sensor_unclamped"
        elif self.controller.state == MachineState.UNCLAMPING:
            delay = self.controller.settings.confirm_unclamp_delay
            target_sensor, opposite_sensor = "sensor_unclamped", "sensor_clamped"
        else:
            return

        # Эта задержка задаёт поведение виртуального датчика.
        if self.controller.elapsed_seconds >= delay and not self.hal.read_input(target_sensor):
            self.hal.set_input(opposite_sensor, False)
            self.hal.set_input(target_sensor, True)
            logging.getLogger(__name__).info("Simulation auto-confirmed %s", target_sensor)

    def _auto_confirm_toggled(self, enabled: bool) -> None:
        self.sensor_clamped.setEnabled(not enabled)
        self.sensor_unclamped.setEnabled(not enabled)
        self._style_auto_confirm_button(enabled)

    def _style_auto_confirm_button(self, enabled: bool) -> None:
        color = "#c8e6c9" if enabled else "#eeeeee"
        self.auto_confirm_button.setStyleSheet(f"QPushButton {{ background-color: {color}; }}")

    def _refresh(self) -> None:
        self.state_label.setText(STATE_LABELS[self.controller.state])
        state = self.controller.state
        status_text = {
            MachineState.IDLE: "Положение не определено",
            MachineState.CLAMPING: "Зажимается",
            MachineState.UNCLAMPING: "Разжимается",
            MachineState.CLAMPED: "Зажато",
            MachineState.UNCLAMPED: "Разжато",
            MachineState.ERROR: str(self.hal.read_output("error_code") or "Ошибка"),
        }[state]
        self.simulator_status.setText(status_text)
        self.simulator_status.setStyleSheet(
            "color: #b71c1c; font-weight: bold" if state == MachineState.ERROR
            else "color: #1b5e20; font-weight: bold"
            if state in (MachineState.CLAMPED, MachineState.UNCLAMPED)
            else "color: #555; font-weight: bold"
        )
        if state == MachineState.ERROR:
            error_code = self.hal.read_output("error_code")
            self.error_banner.setText(f"Ошибка {error_code}")
            self.error_banner.setStyleSheet("background: #ffebee; color: #b71c1c; padding: 6px")
        else:
            self.error_banner.setText("Ошибок нет")
            self.error_banner.setStyleSheet("background: #e8f5e9; color: #1b5e20; padding: 6px")

        if state in (MachineState.CLAMPING, MachineState.UNCLAMPING):
            timeout = self.controller.active_timeout or 0.0
            elapsed = self.controller.elapsed_seconds
            remaining = self.controller.remaining_seconds or 0.0
            self.operation_label.setText("Цилиндр зажимается" if state == MachineState.CLAMPING else "Цилиндр разжимается")
            self.timer_label.setText(f"Осталось {remaining:.1f} с")
            self.progress_bar.setValue(max(0, min(1000, int(remaining / timeout * 1000))))
        else:
            self.operation_label.setText("Операция не выполняется")
            self.timer_label.setText("")
            self.progress_bar.setValue(0)

        self.sensor_clamped.blockSignals(True)
        self.sensor_unclamped.blockSignals(True)
        # Обновляем чекбоксы из HAL, не вызывая их обработчики повторно.
        self.sensor_clamped.setChecked(self.hal.read_input("sensor_clamped"))
        self.sensor_unclamped.setChecked(self.hal.read_input("sensor_unclamped"))
        self.sensor_clamped.blockSignals(False)
        self.sensor_unclamped.blockSignals(False)
        auto_confirm = self.auto_confirm_button.isChecked()
        self.sensor_clamped.setEnabled(not auto_confirm)
        self.sensor_unclamped.setEnabled(not auto_confirm)
        self.command_status.setText(
            f"cmd_clamp={int(self.hal.read_input('cmd_clamp'))}  ·  "
            f"cmd_unclamp={int(self.hal.read_input('cmd_unclamp'))}"
        )

        for signal_name, label in self.output_labels.items():
            value = self.hal.read_output(signal_name)
            label.setText("● ВКЛ" if value else "○ Выкл")
            label.setStyleSheet("color: #1b5e20; font-weight: bold" if value else "color: #666")

        self.reset_button.setEnabled(state == MachineState.ERROR)

    def _save_settings(self) -> None:
        # Иначе изменение таймаута посреди движения поменяло бы предел уже начатой операции.
        if self.controller.active_timeout is not None:
            QMessageBox.information(self, "Операция выполняется", "Дождитесь завершения операции перед изменением таймаутов.")
            return
        try:
            self.settings_repository.set_value("t_clamp", self.clamp_timeout.value())
            self.settings_repository.set_value("t_unclamp", self.unclamp_timeout.value())
            self.settings_repository.set_value(
                "confirm_clamp_delay", self.clamp_confirm_delay.value(),
            )
            self.settings_repository.set_value(
                "confirm_unclamp_delay", self.unclamp_confirm_delay.value(),
            )
            self.settings_repository.set_value(
                "auto_confirm", self.auto_confirm_button.isChecked(),
            )
            self.controller.settings = self.settings_repository.load()
        except (OSError, ValueError, sqlite3.Error) as error:
            QMessageBox.warning(self, "Не удалось сохранить", str(error))
            return
        self.statusBar().showMessage("Таймауты сохранены в SQLite", 4000)

    def _open_full_logs(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("Полный журнал событий")
        dialog.resize(850, 520)
        layout = QVBoxLayout(dialog)
        viewer = QPlainTextEdit(dialog)
        viewer.setReadOnly(True)
        viewer.document().setMaximumBlockCount(0)
        log_path = self.settings_repository.database_path.with_name("bench.log")

        def load_log() -> None:
            try:
                content = log_path.read_text(encoding="utf-8", errors="replace")
            except FileNotFoundError:
                content = "Журнал пока пуст. Записи появятся после переходов и ошибок."
            except OSError as error:
                content = f"Не удалось прочитать журнал: {error}"
            viewer.setPlainText(content)
            viewer.moveCursor(QTextCursor.End)

        load_log()
        layout.addWidget(viewer, 1)
        buttons = QHBoxLayout()
        refresh_button = QPushButton("Обновить", dialog)
        refresh_button.clicked.connect(load_log)
        close_button = QPushButton("Закрыть", dialog)
        close_button.clicked.connect(dialog.accept)
        buttons.addStretch(1)
        buttons.addWidget(refresh_button)
        buttons.addWidget(close_button)
        layout.addLayout(buttons)
        dialog.exec_()

    def _reset_error(self) -> None:
        self.controller.reset_error()
        self._refresh()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt callback name
        logging.getLogger().removeHandler(self._log_handler)
        self.timer.stop()
        super().closeEvent(event)


def run_gui(controller: ClampController, hal: MemoryHAL, repository: SettingsRepository) -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Pneumatic Clamp Simulator")
    window = SimulatorWindow(controller, hal, repository)
    window.show()
    return app.exec_()
