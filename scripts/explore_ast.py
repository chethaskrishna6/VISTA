"""Throwaway script: dump PyVerilog's AST for a netlist.
Not part of the vista package. Used to design Engine 1's real parser."""
import sys
from pathlib import Path

from pyverilog.vparser.parser import parse

BUILD_DIR = Path(".build")


def main(path: str) -> None:
    BUILD_DIR.mkdir(exist_ok=True)
    ast, _directives = parse([path], outputdir=str(BUILD_DIR), debug=False)

    print("=" * 60)
    print("FULL AST (pyverilog .show())")
    print("=" * 60)
    ast.show()

    print("\n" + "=" * 60)
    print("MODULE ITEM TYPES")
    print("=" * 60)
    module = ast.description.definitions[0]
    print(f"module name : {module.name}")
    for item in module.items:
        print(f"  {type(item).__name__}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "benchmarks/c17.v")