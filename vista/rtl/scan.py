"""Engine 1: netlist transforms that make circuits safe for the fault model."""
from __future__ import annotations

from vista.rtl.model import Circuit, CircuitError, GateType

PO_SUFFIX = "$po"


def isolate_po_fanout(c: Circuit) -> Circuit:
    """For every PO net that also feeds gates, add an observation buffer `n -> n$po` and make `n$po`
    the primary output. Function is unchanged; the PO pin becomes a fault-site branch of `n`.
    Returns `c` itself when nothing needs isolating."""
    targets = c.po_with_fanout
    if not targets:
        return c
    clash = [n + PO_SUFFIX for n in targets if n + PO_SUFFIX in c.nets or n + PO_SUFFIX in c.gates]
    if clash:
        raise CircuitError(f"cannot add observation buffers, names already used: {clash}")
    out = Circuit(c.name)
    for name in c.nets:                                  # same net order -> same pi_order
        out.net(name)
    for name, net in c.nets.items():
        if net.is_pi:
            out.mark_pi(name)
        if net.is_po and name not in targets:
            out.mark_po(name)
    for g in c.gates.values():
        out.add_gate(g.name, g.type, g.output, list(g.inputs))
    for n in targets:
        buf = n + PO_SUFFIX
        out.add_gate(buf, GateType.BUF, buf, [n])
        out.mark_po(buf)
        out.po_buffers.append(buf)
    out.scan_cells = list(c.scan_cells)
    out.validate()
    return out