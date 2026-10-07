# VISTA JSON contract, version 1.x

Machine-readable schemas: `docs/schemas/*.schema.json` (regenerate with `vista schema export`).
Check any file: `vista schema validate file.json` (structure + cross-field consistency).

## Versioning
- Every document carries `schema_version` ("1.0") and `document` (its type).
- **Minor bump (1.1):** a field was added. Consumers MUST ignore fields they don't know.
- **Major bump (2.0):** a field was removed, renamed, or changed meaning. Consumers should reject unknown majors.

## Documents
| `document` | produced by |
|---|---|
| `circuit` | `Circuit.to_dict()` |
| `fault_list` | `universe_to_dict()` (uncollapsed), `collapsed_to_dict()` (collapsed) |
| `fault_sim_report` | `vista fsim --json` |
| `atpg_report` | `vista atpg --json` (add `--hybrid` for the SAT fallback) |
| `transition_sim_report` | `vista tdf-sim --json` |
| `transition_atpg_report` | `vista tdf-atpg --json` |

## Conventions
- **Bit strings** (`bits`, `cube`, `v1`, `v2`): one character per PI, in `pi_order`; `0`, `1`, or `X` (don't-care).
  A `bits` string is always a fill of its `cube`.
- **Fault ids:** stem `net/SA0`; branch `net->gate.pin/SA1`; transition faults end in `/STR` or `/STF`.
- **`class_size`:** how many uncollapsed faults a collapsed representative stands for.
  Weighted figures (`weighted_*`) use it, so collapsed runs report full-universe coverage.
- **Coverage** = detected / total. **Efficiency** = (detected + proven untestable) / total.
- **Statuses (`atpg_report`):** `detected`, `redundant` (proven untestable), `aborted` (unresolved).
  `summary.aborted` counts every PODEM give-up, including faults a later pattern happened to detect,
  so `summary.aborted >= number of faults with status "aborted"`.
- `algorithm` is informational; don't branch on it.

## Not in 1.0 yet
Compaction results (kept indices) and a detection-matrix export for an arbitrary pattern set.