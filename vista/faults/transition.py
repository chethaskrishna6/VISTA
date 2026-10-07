"""Engine 2: transition-delay fault model (slow-to-rise / slow-to-fall)."""
from __future__ import annotations

from dataclasses import dataclass

from vista.faults.stuck_at import Fault, generate_stuck_at_faults
from vista.rtl.model import Circuit


@dataclass(frozen=True)
class TransitionFault:
    """Stem fault if gate is None; otherwise a branch fault on input `pin` of `gate`."""
    net: str
    rising: bool                  # True = slow-to-rise (STR), False = slow-to-fall (STF)
    gate: str | None = None
    pin: int | None = None

    def __post_init__(self) -> None:
        if (self.gate is None) != (self.pin is None):
            raise ValueError("gate and pin must be given together")

    @property
    def is_branch(self) -> bool:
        return self.gate is not None

    @property
    def init_value(self) -> int:
        """Value V1 must put on the site (also the capture-cycle stuck value)."""
        return 0 if self.rising else 1

    @property
    def stuck(self) -> Fault:
        """The stuck-at fault this behaves as during the capture cycle."""
        return Fault(self.net, self.init_value, self.gate, self.pin)

    @property
    def id(self) -> str:
        loc = self.stuck.id.rsplit("/", 1)[0]
        return f"{loc}/{'STR' if self.rising else 'STF'}"

    def to_dict(self) -> dict:
        return {"id": self.id, "net": self.net, "transition": "rise" if self.rising else "fall",
                "kind": "branch" if self.is_branch else "stem", "gate": self.gate, "pin": self.pin}


def generate_transition_faults(circuit: Circuit) -> list[TransitionFault]:
    """One STR (stuck value 0) and one STF (stuck value 1) per stuck-at fault site."""
    return [TransitionFault(f.net, f.value == 0, f.gate, f.pin)
            for f in generate_stuck_at_faults(circuit)]