# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## What This Project Does

Transpiles and executes HP Prime PPL (`.hpprgm`) calculator programs locally in Python. The pipeline is: **Lint → Transpile → Execute**, with graphical output rendered to `screen.png` (320×240 via Pillow).

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run a PPL file
python src/ppl_emulator/cli.py examples/FIREWORKS.hpprgm

# Run with flags
python src/ppl_emulator/cli.py examples/FIREWORKS.hpprgm --dump-python   # show transpiled Python
python src/ppl_emulator/cli.py --code "EXPORT T() BEGIN PRINT(42); END;" # inline code
python src/ppl_emulator/cli.py program.hpprgm --no-lint                  # skip linter

# Run all tests
pytest -v

# Run unit tests only
pytest tests/test_compiler.py -v

# Run integration tests only
pytest tests/test_integration.py -v

# Run a specific test
pytest tests/test_compiler.py -v -k "test_for_loop"
```

## Architecture

The pipeline runs in three sequential stages inside `cli.py`:

1. **Lint** (`linter.py`) — Static analysis on raw PPL code. 27+ checks: block balance (`IF/END`, `FOR/DO/END`), undefined variables, invalid function signatures, 1-indexed array misuse. Outputs colored errors with line numbers.

2. **Transpile** (`transpiler/`) — Converts PPL to Python:
   - `core.py`: Line-by-line state machine. Preprocessing expands one-liners; first pass scans function/variable declarations; main pass tracks indent and emits Python blocks.
   - `expressions.py`: Transforms PPL expressions — operators, array indexing, string escaping.
   - `constants.py`: Operator/keyword mappings (`:=`→`=`, `=`→`==`, `^`→`**`, `AND`→`and`, `DIV`→`//`, Unicode `≠≤≥`).

3. **Execute** (`runtime/`) — Runs transpiled Python via `exec()` with an `HPPrimeRuntime` namespace:
   - `engine.py`: Emulates 70+ HP Prime builtins (graphics: `RECT`, `LINE`, `CIRCLE_P`; I/O: `PRINT`, `INPUT`, `CHOOSE`; math/string functions). `INPUT`/`CHOOSE` return defaults in headless mode.
   - `types.py`: `PPLList` — 1-based indexed list (auto-expands on set). `CASMock` — stub for CAS operations.

## Key PPL→Python Conventions

- **Assignment**: `:=` → `=`; **Equality**: `=` → `==`
- **Arrays**: PPL is 1-indexed. `PPLList` handles this transparently.
- **Globals**: Variables assigned outside a `LOCAL` declaration get `global <var>` emitted. HP Prime reserves `A-Z`, `G0-G9`, `L0-L9`, `M0-M9` as globals.
- **String escaping**: PPL uses `""` for a literal quote inside strings (also accepts `\"`).

## Tests

- `tests/test_compiler.py` — Unit tests for transpiler and runtime internals.
- `tests/test_integration.py` — Discovers all `.hpprgm` files in the `8-PPL/` directory tree and runs them. If a `.expected` file exists alongside a `.hpprgm`, the test validates `PRINT` output against it.

To add a test case: create a `.hpprgm` file and optionally a `.expected` file with one expected `PRINT` line per line.

## Debugging Transpilation Issues

- Use `--dump-python` to inspect the generated Python code.
- Most transpilation bugs are missing regex/keyword mappings — check `transpiler/constants.py` and `transpiler/expressions.py` first.
- Runtime builtin failures (e.g., `RECT`, `LINE`) are in `runtime/engine.py`; verify color format handling (HP uses both decimal and `#FFh` hex).
- `patcher.py` auto-patches known bugs in `linter.py` — if the linter has a regression, check this file for context on what was patched and why.
