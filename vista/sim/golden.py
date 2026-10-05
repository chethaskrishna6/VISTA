"""Golden check: compare LogicSimulator against Icarus Verilog, exhaustively."""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from vista.rtl.model import Circuit
from vista.rtl.parser import VerilogParser
from vista.sim.logic import to_str
from vista.sim.simulator import LogicSimulator


def build_testbench(circuit: Circuit) -> str:
    pis, pos = circuit.primary_inputs, circuit.primary_outputs
    pi_cat = "{" + ", ".join(pis) + "}"                 # first PI is the MSB
    po_cat = "{" + ", ".join(f"o_{p}" for p in pos) + "}"
    conns = [f".{p}({p})" for p in pis] + [f".{p}(o_{p})" for p in pos]
    return "\n".join([
        "module tb;",
        *[f"  reg {p};" for p in pis],
        *[f"  wire o_{p};" for p in pos],
        "  integer i;",
        f"  {circuit.name} dut ({', '.join(conns)});",
        "  initial begin",
        f"    for (i = 0; i < {2 ** len(pis)}; i = i + 1) begin",
        f"      {pi_cat} = i;",
        "      #1;",
        f'      $display("%b %b", {pi_cat}, {po_cat});',
        "    end",
        "    $finish;",
        "  end",
        "endmodule",
    ])


def iverilog_truth_table(circuit: Circuit, dut_path: str | Path) -> list[tuple[str, str]]:
    """Run Icarus on the DUT; return [(input_bits, output_bits), ...]."""
    if shutil.which("iverilog") is None:
        raise RuntimeError("iverilog not found on PATH")
    with tempfile.TemporaryDirectory() as tmp:
        tb, vvp = Path(tmp) / "tb.v", Path(tmp) / "sim.vvp"
        tb.write_text(build_testbench(circuit))
        subprocess.run(["iverilog", "-g2005", "-o", str(vvp), str(tb), str(dut_path)],
                       check=True, capture_output=True, text=True)
        run = subprocess.run(["vvp", str(vvp)], check=True, capture_output=True, text=True)
    rows = []
    for line in run.stdout.splitlines():
        parts = line.split()
        if len(parts) == 2 and set(parts[0] + parts[1]) <= set("01xXzZ"):
            rows.append((parts[0], parts[1]))
    return rows


def compare_with_golden(sim: LogicSimulator, dut_path: str | Path) -> tuple[int, list[str]]:
    """Return (vectors_checked, mismatch_descriptions)."""
    rows = iverilog_truth_table(sim.circuit, dut_path)
    bad = []
    for ins, golden in rows:
        got = to_str(sim.outputs(sim.pattern_from_string(ins)).values())
        if got.upper() != golden.upper():
            bad.append(f"inputs={ins}: vista={got} icarus={golden}")
    return len(rows), bad


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "benchmarks/c17.v"
    sim = LogicSimulator(VerilogParser().parse_file(path))
    n, bad = compare_with_golden(sim, path)
    print(f"{n - len(bad)}/{n} vectors match Icarus Verilog")
    for b in bad:
        print("MISMATCH", b)