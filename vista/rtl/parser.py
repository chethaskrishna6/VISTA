"""Engine 1: structural Verilog -> Circuit."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from pyverilog.vparser import ast
from pyverilog.vparser.parser import parse

from vista.rtl.model import Circuit, CircuitError, GateType

GATE_MAP = {t.value: t for t in GateType}


class VerilogParser:
    def __init__(self, build_dir: str | Path = ".build") -> None:
        self.build_dir = Path(build_dir)

    def parse_file(self, path: str | Path) -> Circuit:
        self.build_dir.mkdir(exist_ok=True)
        tree, _ = parse([str(path)], outputdir=str(self.build_dir), debug=False)
        modules = [d for d in tree.description.definitions if isinstance(d, ast.ModuleDef)]
        if len(modules) != 1:
            raise CircuitError(f"expected exactly 1 module, found {len(modules)}")
        return self._build(modules[0])

    # ---- internals ----------------------------------------------------
    def _build(self, module: ast.ModuleDef) -> Circuit:
        circuit = Circuit(module.name)
        decls: list = []
        instance_lists: list[ast.InstanceList] = []

        # ANSI-style ports: module m(input a, output y);
        if module.portlist is not None:
            for p in module.portlist.ports:
                if isinstance(p, ast.Ioport):
                    decls.append(p.first)

        for item in module.items:
            if isinstance(item, ast.Decl):
                decls.extend(item.list)
            elif isinstance(item, ast.InstanceList):
                instance_lists.append(item)
            else:
                raise CircuitError(
                    f"unsupported construct '{type(item).__name__}' (structural gates only)"
                )

        # Pass 1: declarations (so order of items in the file doesn't matter)
        for d in decls:
            if isinstance(d, (ast.Input, ast.Output, ast.Wire)):
                if d.width is not None:
                    raise CircuitError(f"vectors not supported yet: '{d.name}'")
                circuit.net(d.name)
                if isinstance(d, ast.Input):
                    circuit.mark_pi(d.name)
                elif isinstance(d, ast.Output):
                    circuit.mark_po(d.name)
            else:
                raise CircuitError(f"unsupported declaration '{type(d).__name__}'")

        # Pass 2: gate instances
        anon = 0
        for il in instance_lists:
            gtype = GATE_MAP.get(il.module.lower())
            if gtype is None:
                raise CircuitError(f"unsupported primitive/module '{il.module}'")
            for inst in il.instances:
                nets = []
                for arg in inst.portlist:
                    if not isinstance(arg.argname, ast.Identifier):
                        raise CircuitError(
                            f"instance '{inst.name}': only plain net connections supported"
                        )
                    nets.append(arg.argname.name)
                name = inst.name or f"_g{anon}"
                anon += 1 if not inst.name else 0
                circuit.add_gate(name, gtype, output=nets[0], inputs=nets[1:])

        circuit.validate()
        return circuit


if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else "benchmarks/c17.v"
    c = VerilogParser().parse_file(src)
    print(c)
    print(json.dumps(c.to_dict(), indent=2))