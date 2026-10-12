"""Проверки конечного автомата без реального времени и оборудования."""

from bench_sim.logic.controller import ClampController, MachineState
from bench_sim.hal import MemoryHAL
from bench_sim.data.settings import MachineSettings


class FakeClock:
    """Позволяет проверить таймауты, продвигая время без настоящих пауз."""

    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


def make_controller():
    hal = MemoryHAL()
    clock = FakeClock()
    settings = MachineSettings(2.0, 0.5, "E001", "E002", "E003")
    return hal, clock, ClampController(hal, settings, clock)


def pulse(hal: MemoryHAL, controller: ClampController, command: str) -> None:
    hal.set_input(command, True)
    controller.tick()
    hal.set_input(command, False)
    controller.tick()


def test_clamp_completes_when_sensor_activates() -> None:
    hal, _, controller = make_controller()
    pulse(hal, controller, "cmd_clamp")

    assert controller.state == MachineState.CLAMPING
    assert hal.read_output("out_clamp") is True
    assert hal.read_output("out_unclamp") is False

    hal.set_input("sensor_clamped", True)
    controller.tick()
    assert controller.state == MachineState.CLAMPED
    assert hal.read_output("out_clamp") is False
    assert hal.read_output("status_clamped") is True
    assert hal.read_output("status_unclamped") is False


def test_clamp_timeout_sets_error_and_stops_outputs() -> None:
    hal, clock, controller = make_controller()
    pulse(hal, controller, "cmd_clamp")
    clock.advance(2.0)

    controller.tick()
    assert controller.state == MachineState.ERROR
    assert hal.read_output("error_code") == "E001"
    assert hal.read_output("out_clamp") is False
    assert hal.read_output("out_unclamp") is False


def test_unclamp_uses_its_own_timeout_and_error() -> None:
    hal, clock, controller = make_controller()
    pulse(hal, controller, "cmd_unclamp")
    clock.advance(0.5)

    controller.tick()
    assert controller.state == MachineState.ERROR
    assert hal.read_output("error_code") == "E002"
    assert hal.read_output("out_unclamp") is False


def test_unclamp_completes_when_sensor_activates() -> None:
    hal, _, controller = make_controller()
    pulse(hal, controller, "cmd_unclamp")
    hal.set_input("sensor_unclamped", True)

    controller.tick()
    assert controller.state == MachineState.UNCLAMPED
    assert hal.read_output("out_unclamp") is False
    assert hal.read_output("status_unclamped") is True


def test_simultaneous_commands_fail_safe() -> None:
    hal, _, controller = make_controller()
    hal.set_input("cmd_clamp", True)
    hal.set_input("cmd_unclamp", True)

    controller.tick()
    assert controller.state == MachineState.ERROR
    assert hal.read_output("error_code") == "E003"
    assert hal.read_output("out_clamp") is False
    assert hal.read_output("out_unclamp") is False


def test_error_can_be_reset_after_sensor_conflict_is_removed() -> None:
    hal, _, controller = make_controller()
    hal.set_input("sensor_clamped", True)
    hal.set_input("sensor_unclamped", True)
    controller.tick()
    assert controller.state == MachineState.ERROR

    hal.set_input("sensor_unclamped", False)
    controller.reset_error()
    assert controller.state == MachineState.CLAMPED
    assert hal.read_output("error_code") == ""
    assert hal.read_output("status_clamped") is True
