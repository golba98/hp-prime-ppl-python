# HP Prime PPL Emulator (Python)

This project provides a runtime and transpiler to execute HP Prime PPL (`.hpprgm`) code directly in Python. It's designed to help developers test and debug their PPL logic locally before deploying to hardware.

## Core Components
- **`transpiler.py`**: A regex-based engine that converts PPL's unique syntax (1-based arrays, block structures, math operators) into idiomatic Python.
- **`runtime.py`**: Emulates the HP Prime hardware environment, including a 320x240 screen (using Pillow) and built-in PPL functions.
- **`run_ppl.py`**: The CLI entry point for running individual files or inline code.
- **`test_all.py`**: A discovery script that runs all `.hpprgm` files in parent/sibling directories to ensure regressions aren't introduced.

## Key Conventions
- **PPL Syntax**: Remember that PPL uses `:=` for assignment and `1-based` indexing for lists.
- **Screen Output**: Any graphical output is rendered to `screen.png`.
- **Assertions**: The test runner looks for `.expected` files to verify `PRINT` output.

## Workflow for AI Assistants
1. **Transpilation Fixes**: If a PPL feature isn't working, check `transpiler.py` first. Most "bugs" are usually missing regex mappings for PPL keywords.
2. **Runtime Errors**: If a built-in function like `RECT` or `LINE` fails, check `runtime.py`. Ensure color handling matches HP's hexadecimal/decimal formats.
3. **Adding Tests**: To add a new test case, create a `.hpprgm` file and a corresponding `.expected` file.
4. **Validating Changes**: Always run `python run_ppl.py <file>` or `pytest` after modifying the core logic.
