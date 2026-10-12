"""Упрощённая замена HAL для запуска симулятора без станка.

Здесь перечислены сигналы и описан контракт HAL. MemoryHAL хранит их значения
в обычных словарях Python; настоящий адаптер к LinuxCNC можно подключить вместо него.
"""

from typing import Protocol, TypeAlias

SignalValue: TypeAlias = bool | str

# Команды приходят от интерфейса, а датчики показывают положение цилиндра.
INPUTS = frozenset({"cmd_clamp", "cmd_unclamp", "sensor_clamped", "sensor_unclamped"})
# Выходы управляют клапанами и передают состояние автомата внешней стороне.
OUTPUTS = frozenset({"out_clamp", "out_unclamp", "status_clamped", "status_unclamped", "error_code"})


class HAL(Protocol):
    """Минимальный договор, которому должен соответствовать любой HAL-адаптер."""

    def read_input(self, name: str) -> bool: ...

    def write_output(self, name: str, value: SignalValue) -> None: ...


class MemoryHAL:
    """Хранит значения входов и выходов в памяти вместо настоящих контактов."""

    def __init__(self) -> None:
        # Датчики при старте выключены: положение цилиндра пока не подтверждено.
        self._inputs: dict[str, bool] = {name: False for name in INPUTS}
        self._outputs: dict[str, SignalValue] = {name: False for name in OUTPUTS}
        self._outputs["error_code"] = ""

    def set_input(self, name: str, value: bool) -> None:
        if name not in INPUTS:
            raise KeyError(f"Unknown HAL input: {name}")
        self._inputs[name] = bool(value)

    def read_input(self, name: str) -> bool:
        try:
            return self._inputs[name]
        except KeyError as error:
            raise KeyError(f"Unknown HAL input: {name}") from error

    def write_output(self, name: str, value: SignalValue) -> None:
        if name not in OUTPUTS:
            raise KeyError(f"Unknown HAL output: {name}")
        # Линии состояния — bool, но error_code передаёт строковый код вроде E001.
        if name == "error_code":
            if not isinstance(value, str):
                raise TypeError("error_code must be a string")
        elif not isinstance(value, bool):
            raise TypeError(f"{name} must be a boolean")
        self._outputs[name] = value

    def read_output(self, name: str) -> SignalValue:
        try:
            return self._outputs[name]
        except KeyError as error:
            raise KeyError(f"Unknown HAL output: {name}") from error

    @property
    def inputs(self) -> dict[str, bool]:
        return self._inputs.copy()

    @property
    def outputs(self) -> dict[str, SignalValue]:
        return self._outputs.copy()
