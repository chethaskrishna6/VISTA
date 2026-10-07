"""Unified command-line entry point: `vista <command> [options]`."""
from __future__ import annotations

import importlib
import sys
from importlib import metadata

COMMANDS: dict[str, tuple[str, str]] = {
    "atpg": ("vista.atpg.generate", "stuck-at ATPG (PODEM; --hybrid adds the SAT fallback)"),
    "tdf-atpg": ("vista.atpg.transition_atpg", "transition-fault ATPG"),
    "fsim": ("vista.sim.pattern_sim", "stuck-at fault simulation of random/exhaustive patterns"),
    "tdf-sim": ("vista.sim.transition_sim", "transition-fault simulation"),
    "compact": ("vista.atpg.compact", "static compaction (reverse-order, greedy cover)"),
    "merge": ("vista.atpg.merge", "cube-merging compaction"),
    "schema": ("vista.schema", "export or validate the JSON contract"),
}


def _version() -> str:
    from vista.schema import SCHEMA_VERSION
    try:
        pkg = metadata.version("vista-eda")
    except metadata.PackageNotFoundError:
        pkg = "unknown (not installed)"
    return f"vista-eda {pkg} (JSON schema {SCHEMA_VERSION})"


def _help() -> str:
    width = max(map(len, COMMANDS))
    rows = "\n".join(f"  {name:<{width}}  {desc}" for name, (_, desc) in COMMANDS.items())
    return (f"usage: vista <command> [options]\n\ncommands:\n{rows}\n\n"
            "Run `vista <command> --help` for a command's options.")


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(_help())
        return 0
    if argv[0] == "--version":
        print(_version())
        return 0
    cmd, rest = argv[0], argv[1:]
    if cmd not in COMMANDS:
        print(f"vista: unknown command '{cmd}'\n\n{_help()}", file=sys.stderr)
        return 2
    module = importlib.import_module(COMMANDS[cmd][0])
    return module.main(rest) or 0


if __name__ == "__main__":
    raise SystemExit(main())