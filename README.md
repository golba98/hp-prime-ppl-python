# HP Prime PPL Emulator

![HP Prime Screen Render](screen.png)

Transpiles and runs HP Prime PPL (`.hpprgm`) code locally so you can test before pushing to your HP Prime G1.

## 🚀 Examples

Check out the `examples/` directory for cool programs to run:
- **`FIREWORKS.hpprgm`**: Dynamic graphical firework display.
- **`test_draw.hpprgm`**: Comprehensive graphics function test.

To run an example:
```powershell
ppl examples/FIREWORKS.hpprgm
```

---

## One-time setup — add this folder to your PATH

This lets you run `ppl` and `test` from **any project folder** without typing the full path.

1. **Locate this folder** (where `run_ppl.py` is stored).
2. **Add to PATH**:
   - **Windows**: Search for "Edit the system environment variables" → Environment Variables → Path → Edit → New → [Paste folder path].
   - **macOS/Linux**: Add `export PATH="$PATH:/path/to/this/folder"` to your `~/.zshrc` or `~/.bashrc`.
3. **Restart your terminal.**

After setup you can run from any subfolder like `1-Binary Search Tree Visualizer\`:

```powershell
ppl BSTVisualizer.hpprgm
test
```

---

## Run a single PPL file

From inside a project folder (after PATH setup):
```powershell
ppl <file.hpprgm>
```

Without PATH setup (from project folder):
```powershell
py "../0-App/run_ppl.py" <file.hpprgm>
```

From the `0-App` folder directly:
```powershell
py run_ppl.py <file.hpprgm>
```

---

## Common flags

| Flag | Description |
|------|-------------|
| `--dump-python` | Print the transpiled Python to the terminal (great for debugging) |
| `--output <path>` | Save the screen render to a custom PNG path (default: `screen.png`) |
| `--code "PPL..."` | Run inline PPL code without a file |

Examples:
```powershell
ppl BSTVisualizer.hpprgm --dump-python
ppl BSTVisualizer.hpprgm --output bst_screen.png
ppl --code "EXPORT T() BEGIN PRINT(42); END;"
```

---

## Run ALL tests with one command

Discovers and runs every `.hpprgm` file under `8-PPL\` automatically:

```powershell
test
```

Verbose mode — shows transpiled Python on any failure:
```powershell
test -v
```

Via pytest (coloured output + individual test names):
```powershell
py -m pytest "../0-App/test_all.py" -v
```

---

## Expected output assertions

To assert what a program should PRINT, create a `.expected` file next to the `.hpprgm` with the same base name:

```
1-Binary Search Tree Visualizer\
  BSTVisualizer.hpprgm
  BSTVisualizer.expected   ← one expected PRINT line per line
```

`test_all.py` will compare actual PRINT output against it and fail if they differ.

---

## Unit tests (transpiler + runtime internals)

```powershell
py -m pytest "../0-App/test_ppl.py" -v
```

Run a specific test:
```powershell
py -m pytest "../0-App/test_ppl.py" -v -k "test_for_loop"
```

---

## Output files

| File | Description |
|------|-------------|
| `screen.png` | 320×240 screen render saved after each run |
| stdout | Everything your program sends to `PRINT` |
| stderr | Emulator status messages (`[EMU]`, `[CHOOSE]`, etc.) |

---

## Project structure

```
8-PPL\
  0-App\
    run_ppl.py       ← CLI runner
    test_all.py      ← unified test runner (discovers all .hpprgm files)
    test_ppl.py      ← unit tests for transpiler/runtime
    transpiler.py    ← PPL → Python transpiler
    runtime.py       ← HP Prime runtime emulation
    ppl.bat          ← shortcut: ppl <file.hpprgm>
    test.bat         ← shortcut: test
    README.md        ← this file
  1-Binary Search Tree Visualizer\
    BSTVisualizer.hpprgm
  2-Your Next Program\
    ...
```
