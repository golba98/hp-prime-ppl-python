#!/usr/bin/env python3
"""
Unified PPL Test Runner
========================
Auto-discovers every .hpprgm file under the 8-PPL directory and runs
each through three stages:

  Stage 1 — LINT      line-by-line static analysis (lint.py)
  Stage 2 — TRANSPILE PPL → Python  (transpiler.py)
  Stage 3 — EXECUTE   run the transpiled code through the emulator

A file only reaches Stage 3 if Stages 1 & 2 pass.

Usage:
  py test_all.py                  # run all (from 0-App folder)
  py test_all.py --verbose        # show detailed lint + transpiled Python on failure
  py test_all.py --lint-only      # only run the linter, skip execution
  py -m pytest test_all.py -v     # via pytest (coloured, individual test names)

Expected-output assertions:
  Create  <program>.expected  next to the .hpprgm file.
  Each line = one expected PRINT output line.
"""

import sys, os, io, contextlib, tempfile, glob
import pytest

# Ensure 0-App is on the path so all modules are importable
APP_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, APP_DIR)

from transpiler import transpile
from lint        import lint, lint_summary

# ── Discover all .hpprgm files ────────────────────────────────────────────────

PPL_ROOT = os.path.dirname(APP_DIR)   # the 8-PPL directory


def find_all_hpprgm():
    """Return every non-empty .hpprgm file under 8-PPL/, sorted."""
    files = sorted(glob.glob(os.path.join(PPL_ROOT, '**', '*.hpprgm'), recursive=True))
    return [f for f in files if os.path.getsize(f) > 0]


def label(path):
    """Short label:  FolderName/FileName.hpprgm"""
    return os.path.relpath(path, PPL_ROOT).replace('\\', '/')


# ── Stage helpers ─────────────────────────────────────────────────────────────

def stage_lint(filepath, ppl_code):
    """
    Run the static linter.
    Returns (issues, fatal) where fatal=True means there are ERRORs.
    """
    issues = lint(ppl_code, filename=os.path.basename(filepath))
    errors   = [x for x in issues if x.severity == 'ERROR']
    warnings = [x for x in issues if x.severity == 'WARNING']
    return issues, len(errors) > 0


def stage_transpile(filepath, ppl_code, out_png):
    """Transpile PPL → Python.  Returns py_code string.  Raises on error."""
    return transpile(ppl_code, out_path=out_png)


def stage_execute(filepath, py_code):
    """
    Execute the transpiled Python.
    Returns (stdout, stderr).  Raises on error.
    """
    stdout_buf = io.StringIO()
    stderr_buf = io.StringIO()
    ns = {'__name__': '__main__', '__file__': filepath}
    with contextlib.redirect_stdout(stdout_buf), contextlib.redirect_stderr(stderr_buf):
        exec(compile(py_code, filepath, 'exec'), ns)
    return stdout_buf.getvalue(), stderr_buf.getvalue()


def check_expected(filepath, stdout):
    """If a .expected file exists, assert PRINT output matches it."""
    expected_path = filepath.rsplit('.', 1)[0] + '.expected'
    if not os.path.exists(expected_path):
        return  # no assertion file — skip
    with open(expected_path, 'r', encoding='utf-8') as f:
        expected = f.read().strip()
    actual_lines   = [l.strip() for l in stdout.splitlines()   if l.strip()]
    expected_lines = [l.strip() for l in expected.splitlines() if l.strip()]
    assert actual_lines == expected_lines, (
        f'Output mismatch for {os.path.basename(filepath)}:\n'
        f'  Expected: {expected_lines}\n'
        f'  Got:      {actual_lines}'
    )


# ── Pytest parametrized tests ─────────────────────────────────────────────────

ALL_FILES = find_all_hpprgm()


@pytest.mark.parametrize('filepath', ALL_FILES, ids=[label(f) for f in ALL_FILES])
def test_hpprgm(filepath):
    """Stage 1 lint → Stage 2 transpile → Stage 3 execute."""
    with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
        ppl_code = f.read()

    out_png = os.path.join(tempfile.gettempdir(), '_ppl_test_screen.png')

    # Stage 1 — Lint
    issues, fatal = stage_lint(filepath, ppl_code)
    errors   = [x for x in issues if x.severity == 'ERROR']
    warnings = [x for x in issues if x.severity == 'WARNING']

    lint_report = lint_summary(issues)

    assert not fatal, (
        f'Lint errors in {os.path.basename(filepath)}:\n{lint_report}'
    )

    # Stage 2 — Transpile
    py_code = stage_transpile(filepath, ppl_code, out_png)

    # Stage 3 — Execute
    stdout, _ = stage_execute(filepath, py_code)

    # Optional expected-output assertion
    check_expected(filepath, stdout)


# ── Standalone runner (without pytest) ───────────────────────────────────────

def main():
    import argparse

    parser = argparse.ArgumentParser(description='Unified PPL Test Runner')
    parser.add_argument('--verbose',   '-v', action='store_true',
                        help='Show full lint report + transpiled Python on failure')
    parser.add_argument('--lint-only', '-l', action='store_true',
                        help='Only run the linter, skip transpile/execute')
    parser.add_argument('--warnings',  '-w', action='store_true',
                        help='Treat warnings as failures')
    args = parser.parse_args()

    files = find_all_hpprgm()
    if not files:
        print('No .hpprgm files found.')
        return

    passed = failed = 0
    failures = []

    width = 60
    print(f'\nFound {len(files)} PPL program(s)\n{"-"*width}')

    for filepath in files:
        name = label(filepath)
        py_code = ''

        try:
            with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
                ppl_code = f.read()

            out_png = os.path.join(tempfile.gettempdir(), '_ppl_test_screen.png')

            # ── Stage 1: Lint ─────────────────────────────────────────────────
            issues, fatal = stage_lint(filepath, ppl_code)
            errors   = [x for x in issues if x.severity == 'ERROR']
            warnings = [x for x in issues if x.severity == 'WARNING']

            if fatal or (args.warnings and warnings):
                raise AssertionError(
                    f'Lint failed ({len(errors)} error(s), {len(warnings)} warning(s))'
                )

            if args.lint_only:
                status = '  PASS' if not issues else f'  WARN ({len(warnings)} warning(s))'
                print(f'{status}  {name}')
                if issues and args.verbose:
                    print(lint_summary(issues))
                passed += 1
                continue

            # ── Stage 2: Transpile ────────────────────────────────────────────
            py_code = stage_transpile(filepath, ppl_code, out_png)

            # ── Stage 3: Execute ──────────────────────────────────────────────
            stdout, _ = stage_execute(filepath, py_code)

            # ── Optional expected-output check ────────────────────────────────
            check_expected(filepath, stdout)

            # Print result line
            warn_tag = f'  ({len(warnings)} warning(s))' if warnings else ''
            print(f'  PASS  {name}{warn_tag}')
            if warnings and args.verbose:
                for w in warnings:
                    print(f'        {w}')
            passed += 1

        except Exception as e:
            print(f'  FAIL  {name}')
            print(f'        {type(e).__name__}: {e}')
            if args.verbose:
                # Full lint report
                try:
                    full_issues = lint(ppl_code)
                    if full_issues:
                        print('\n        Lint report:')
                        for iss in full_issues:
                            print(f'       {iss}')
                except Exception:
                    pass
                # Transpiled Python
                if py_code:
                    print('\n        Transpiled Python:')
                    for j, ln in enumerate(py_code.splitlines(), 1):
                        print(f'          {j:4}: {ln}')
            failed += 1
            failures.append((name, e))

    print(f'{"-"*width}')
    print(f'\n{passed} passed,  {failed} failed  out of {len(files)} total\n')

    if failures:
        print('Failed programs:')
        for name, e in failures:
            print(f'  {name}:  {e}')
        sys.exit(1)


if __name__ == '__main__':
    main()
