"""Конечный автомат зажатия/разжатия, не зависящий от графического интерфейса.

Интерфейс подаёт команды через HAL, а контроллер запускает выход клапана,
ждёт подтверждения датчика и завершает операцию либо фиксирует таймаут.
"""

import logging
import time
from enum import Enum
from typing import Callable

from bench_sim.hal import HAL
from bench_sim.data.settings import MachineSettings

logger = logging.getLogger(__name__)


class MachineState(str, Enum):
    """Состояния цилиндра, используемые автоматом и интерфейсом."""

    IDLE = "idle"
    CLAMPING = "clamping"
    UNCLAMPING = "unclamping"
    CLAMPED = "clamped"
    UNCLAMPED = "unclamped"
    ERROR = "error"


class ClampController:
    """Управляет одним циклом движения и безопасно гасит выходы при сбое."""

    def __init__(
        self,
        hal: HAL,
        settings: MachineSettings,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.hal = hal
        self.settings = settings
        # Внедряемые монотонные часы позволяют тестам двигать время без реального ожидания.
        self._clock = clock
        self.state = MachineState.IDLE
        self._started_at: float | None = None
        self._previous_commands = {"cmd_clamp": False, "cmd_unclamp": False}

    @property
    def active_timeout(self) -> float | None:
        if self.state == MachineState.CLAMPING:
            return self.settings.t_clamp
        if self.state == MachineState.UNCLAMPING:
            return self.settings.t_unclamp
        return None

    @property
    def elapsed_seconds(self) -> float:
        if self._started_at is None:
            return 0.0
        return max(0.0, self._clock() - self._started_at)

    @property
    def remaining_seconds(self) -> float | None:
        timeout = self.active_timeout
        if timeout is None:
            return None
        return max(0.0, timeout - self.elapsed_seconds)

    def tick(self) -> MachineState:
        clamp_command = self.hal.read_input("cmd_clamp")
        unclamp_command = self.hal.read_input("cmd_unclamp")
        # Команда запускается только при переходе 0→1, а не на каждом цикле опроса.
        clamp_edge = clamp_command and not self._previous_commands["cmd_clamp"]
        unclamp_edge = unclamp_command and not self._previous_commands["cmd_unclamp"]
        self._previous_commands = {
            "cmd_clamp": clamp_command,
            "cmd_unclamp": unclamp_command,
        }

        # Ошибка: до ручного сброса новые команды не запускают движение.
        if self.state == MachineState.ERROR:
            return self.state
        if clamp_command and unclamp_command:
            self._fail(self.settings.error_conflict, "Both clamp commands are active")
            return self.state
        if self.hal.read_input("sensor_clamped") and self.hal.read_input("sensor_unclamped"):
            self._fail(self.settings.error_conflict, "Both position sensors are active")
            return self.state

        if self.state in (MachineState.CLAMPING, MachineState.UNCLAMPING):
            # Во время движения встречная команда не разворачивает текущий цикл.
            if clamp_edge or unclamp_edge:
                logger.warning("Command ignored while the cylinder is moving")
        elif clamp_edge:
            self._begin_clamp()
        elif unclamp_edge:
            self._begin_unclamp()
        else:
            self._sync_idle_state()

        if self.state == MachineState.CLAMPING:
            if self.hal.read_input("sensor_clamped"):
                self._complete(MachineState.CLAMPED)
            elif self._timed_out(self.settings.t_clamp):
                self._fail(self.settings.error_clamp, "Clamp timeout")
        elif self.state == MachineState.UNCLAMPING:
            if self.hal.read_input("sensor_unclamped"):
                self._complete(MachineState.UNCLAMPED)
            elif self._timed_out(self.settings.t_unclamp):
                self._fail(self.settings.error_unclamp, "Unclamp timeout")
        return self.state

    def reset_error(self) -> None:
        if self.state != MachineState.ERROR:
            return
        if self.hal.read_input("sensor_clamped") and self.hal.read_input("sensor_unclamped"):
            logger.warning("Cannot reset while both position sensors are active")
            return
        self.hal.write_output("error_code", "")
        self.state = MachineState.IDLE
        self._sync_idle_state()
        logger.info("Error reset; state is %s", self.state.value)

    def _begin_clamp(self) -> None:
        previous = self.state
        self._clear_position_status()
        self.hal.write_output("out_unclamp", False)
        self.hal.write_output("out_clamp", True)
        self._started_at = self._clock()
        self.state = MachineState.CLAMPING
        logger.info("State transition: %s -> %s", previous.value, self.state.value)

    def _begin_unclamp(self) -> None:
        previous = self.state
        self._clear_position_status()
        self.hal.write_output("out_clamp", False)
        self.hal.write_output("out_unclamp", True)
        self._started_at = self._clock()
        self.state = MachineState.UNCLAMPING
        logger.info("State transition: %s -> %s", previous.value, self.state.value)

    def _complete(self, state: MachineState) -> None:
        self._stop_outputs()
        self._clear_position_status()
        if state == MachineState.CLAMPED:
            self.hal.write_output("status_clamped", True)
        else:
            self.hal.write_output("status_unclamped", True)
        self.hal.write_output("error_code", "")
        previous = self.state
        self.state = state
        self._started_at = None
        logger.info("State transition: %s -> %s", previous.value, state.value)

    def _fail(self, code: str, reason: str) -> None:
        # При любом отказе снимаем оба выхода, чтобы клапан не оставался под напряжением.
        previous = self.state
        self._stop_outputs()
        self._clear_position_status()
        self.hal.write_output("error_code", code)
        self.state = MachineState.ERROR
        self._started_at = None
        logger.error("State transition: %s -> error (%s): %s", previous.value, code, reason)

    def _sync_idle_state(self) -> None:
        clamped = self.hal.read_input("sensor_clamped")
        unclamped = self.hal.read_input("sensor_unclamped")
        self._clear_position_status()
        if clamped:
            self.hal.write_output("status_clamped", True)
            if self.state != MachineState.CLAMPED:
                logger.info("State transition: %s -> clamped", self.state.value)
            self.state = MachineState.CLAMPED
        elif unclamped:
            self.hal.write_output("status_unclamped", True)
            if self.state != MachineState.UNCLAMPED:
                logger.info("State transition: %s -> unclamped", self.state.value)
            self.state = MachineState.UNCLAMPED
        else:
            if self.state != MachineState.IDLE:
                logger.info("State transition: %s -> idle", self.state.value)
            self.state = MachineState.IDLE

    def _clear_position_status(self) -> None:
        self.hal.write_output("status_clamped", False)
        self.hal.write_output("status_unclamped", False)

    def _stop_outputs(self) -> None:
        self.hal.write_output("out_clamp", False)
        self.hal.write_output("out_unclamp", False)

    def _timed_out(self, timeout: float) -> bool:
        return self._started_at is not None and self._clock() - self._started_at >= timeout
