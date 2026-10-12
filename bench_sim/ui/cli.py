"""Интерактивная консоль для ручной проверки команд, датчиков и таймаутов."""

import time

from bench_sim.logic.controller import ClampController
from bench_sim.hal import MemoryHAL


HELP = """Commands:
  clamp                 pulse the clamp command
  unclamp               pulse the unclamp command
  sensor clamped on|off change the clamped sensor
  sensor unclamped on|off change the unclamped sensor
  wait SECONDS          wait and check the timeout
  status                show current state and all outputs
  reset                 reset a latched error
  help                  show this help
  quit                  exit
"""


def run_console(controller: ClampController, hal: MemoryHAL) -> None:
    print("Pneumatic clamp simulator. Type 'help' for commands.")
    controller.tick()
    _print_status(controller, hal)
    while True:
        try:
            parts = input("bench> ").strip().lower().split()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not parts:
            continue
        command = parts[0]
        try:
            if command in ("quit", "exit"):
                return
            if command == "help":
                print(HELP)
            elif command in ("clamp", "unclamp"):
                # Команда короткая: контроллер видит импульс, даже если ввод в консоли уже завершён.
                signal = "cmd_clamp" if command == "clamp" else "cmd_unclamp"
                hal.set_input(signal, True)
                controller.tick()
                hal.set_input(signal, False)
                controller.tick()
            elif command == "sensor" and len(parts) == 3:
                sensor = {
                    "clamped": "sensor_clamped",
                    "unclamped": "sensor_unclamped",
                }.get(parts[1])
                if sensor is None or parts[2] not in ("on", "off"):
                    print("Usage: sensor clamped|unclamped on|off")
                    continue
                hal.set_input(sensor, parts[2] == "on")
                controller.tick()
            elif command == "wait" and len(parts) == 2:
                seconds = float(parts[1])
                if seconds < 0:
                    raise ValueError("Wait duration cannot be negative")
                time.sleep(seconds)
                controller.tick()
            elif command == "status":
                controller.tick()
            elif command == "reset":
                controller.reset_error()
            else:
                print("Unknown command. Type 'help' for available commands.")
                continue
            _print_status(controller, hal)
        except ValueError as error:
            print(f"Invalid value: {error}")


def _print_status(controller: ClampController, hal: MemoryHAL) -> None:
    outputs = hal.outputs
    print(
        f"state={controller.state.value} | "
        f"out_clamp={int(outputs['out_clamp'])} "
        f"out_unclamp={int(outputs['out_unclamp'])} | "
        f"status_clamped={int(outputs['status_clamped'])} "
        f"status_unclamped={int(outputs['status_unclamped'])} | "
        f"error_code={outputs['error_code'] or '-'}"
    )
