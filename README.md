# HP Prime PPL Emulator

![HP Prime Screen Render](screen.png)

Transpiles and runs HP Prime PPL (`.hpprgm`) programs locally in Python.
Pipeline: **Lint → Transpile → Execute** — graphical output renders in a live pygame window (320×240).

---

## 🚀 Quick start

```powershell
ppl examples/FIREWORKS.hpprgm
```

---

## One-time setup — add `0-App` to your PATH

This lets you type `ppl` from **any project folder**.

1. Copy the full path to `0-App\` (e.g. `C:\Users\you\Desktop\8-PPL\0-App`).
2. **Windows**: Search "Edit the system environment variables" → Environment Variables → Path → Edit → New → paste the path.
3. Restart your terminal.

After setup, run from any subfolder (e.g. `27-Tester\`):

```powershell
ppl tester.hpprgm
```

---

## Running a file

```powershell
ppl <file.hpprgm>
```

Pass arguments to the exported function:

```powershell
ppl tester.hpprgm --args "50"
ppl solver.hpprgm --args "100,200"
```

---

## PRINT output mode

Choose where `PRINT()` (and `MSGBOX()`) output appears using `--print-mode`:

| Mode | Flag | PRINT goes to… | Graphics go to… |
|------|------|----------------|-----------------|
| **A — Screen only** | `--print-mode screen` | HP Prime display (pygame window) | HP Prime display |
| **B — Terminal** | `--print-mode terminal` | Terminal / stdout | HP Prime display |
| **Both** *(default)* | *(omit flag)* | Terminal **and** HP Prime display | HP Prime display |

### Option A — Screen only

`PRINT` output appears on the HP Prime display, just like the real calculator's Home view.
Nothing is printed to the terminal.

```powershell
ppl tester.hpprgm --args "50" --print-mode screen
```

### Option B — Terminal

Graphics render on the HP Prime display as normal.
`PRINT` output goes to the terminal / stdout only — nothing is drawn on the screen.
Useful for CI, scripting, or when you want clean terminal output alongside a graphical program.

```powershell
ppl FIREWORKS.hpprgm --print-mode terminal
```

### Default — Both

`PRINT` writes to the terminal **and** renders on the HP Prime display simultaneously.

```powershell
ppl tester.hpprgm --args "50"
```

---

## All flags

| Flag | Description |
|------|-------------|
| `--args "v1,v2,…"` | Pass arguments to the EXPORT function (e.g. `--args "50"`) |
| `--print-mode <mode>` | `screen` / `terminal` / `both` — where PRINT output goes (default: `both`) |
| `--dump-python` | Print the transpiled Python to the terminal (useful for debugging) |
| `--output <path>` | Save screen render to a custom PNG (default: `screen.png`) |
| `--save` | Force PNG save even when the live pygame window is open |
| `--code "PPL…"` | Run inline PPL code without a file |
| `--no-lint` | Suppress warnings-only lint output (syntax/semantic errors still block compile) |
| `--input <val>` | Queue a value for the next `INPUT()` call (repeatable) |

Examples:

```powershell
ppl BSTVisualizer.hpprgm --dump-python
ppl BSTVisualizer.hpprgm --output bst_screen.png
ppl --code "EXPORT T() BEGIN PRINT(42); END;"
ppl sieve.hpprgm --args "100" --print-mode screen
ppl sieve.hpprgm --args "100" --print-mode terminal
```

---

## Run all tests

Discovers every `.hpprgm` file under `8-PPL\` and runs each one:

```powershell
pytest tests/ -v
```

Unit tests only (transpiler + runtime internals):

```powershell
pytest tests/test_compiler.py -v
```

Integration tests only:

```powershell
pytest tests/test_integration.py -v
```

Run a specific test:

```powershell
pytest tests/test_compiler.py -v -k "test_for_loop"
```

Front-end validation regression suite (invalid PPL must fail before transpile/execute):

```powershell
py -m pytest tests/test_frontend_regressions.py -v
```

Quick manual invalid-source check:

```powershell
py -m src.ppl_emulator.cli --code "EXPORT 2TEST() BEGIN PRINT(1); END;" --dump-python
```

Expected result: compile failure with a front-end diagnostic (and no successful run).

---

## Expected output assertions

Create a `.expected` file next to any `.hpprgm` to assert its `PRINT` output:

```
27-Tester\
  tester.hpprgm
  tester.expected   ← one expected PRINT line per line
```

The integration test suite compares actual output against the `.expected` file and fails if they differ.

---

## Output files

| File | Description |
|------|-------------|
| `screen.png` | 320×240 screen render saved after each headless run |
| stdout | `PRINT` output (when `--print-mode terminal` or `both`) |
| pygame window | Live 320×240 display with HP Prime G1 bezel |

---

## Project structure

```
8-PPL\
  0-App\
    src\ppl_emulator\
      cli.py              ← CLI entry point  (ppl command)
      linter.py           ← Static analysis (27+ checks)
      transpiler\
        core.py           ← PPL → Python line-by-line transpiler
        expressions.py    ← Expression transformer (operators, indexing)
        constants.py      ← Keyword/operator mappings
      runtime\
        engine.py         ← HP Prime builtins + pygame/Pillow renderer
        types.py          ← PPLList (1-based), PPLMatrix, PPLString
    tests\
      test_compiler.py    ← Unit tests (transpiler + runtime)
      test_integration.py ← Integration tests (all .hpprgm files)
    examples\
      FIREWORKS.hpprgm
      test_draw.hpprgm
    README.md
```
