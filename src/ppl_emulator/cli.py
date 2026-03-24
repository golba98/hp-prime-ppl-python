#!/usr/bin/env python3
# ─────────────────────────────────────────────────────────────────
#  HP Prime PPL Emulator — CLI
#
#  Usage:
#    ppl program.hpprgm
#    ppl program.hpprgm --output out.png
#    ppl --code "EXPORT Hello() BEGIN PRINT(42); END;"
#    ppl program.hpprgm --dump-python
# ─────────────────────────────────────────────────────────────────

import sys
import os
import argparse
import traceback
import re

# Force UTF-8 output so Unicode characters in error messages display correctly
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')  # type: ignore
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')  # type: ignore

# ── Ensure 0-App root is on sys.path (works both as script and -m module) ──
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))   # .../src/ppl_emulator
_APP_ROOT   = os.path.dirname(os.path.dirname(_SCRIPT_DIR)) # .../0-App
if _APP_ROOT not in sys.path:
    sys.path.insert(0, _APP_ROOT)

from src.ppl_emulator.linter import lint  # pyre-ignore


# ─────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────
#  Colors & UI
# ─────────────────────────────────────────────────────────────────

def _color_enabled():
    """Enable ANSI escape sequences on Windows if possible."""
    if not sys.stdout.isatty():
        return False
    if os.name == 'nt':
        # Standard way to enable ANSI on Windows 10+
        import ctypes
        kernel32 = ctypes.windll.kernel32  # type: ignore
        # ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
        kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
    return True

_HAS_COLOR = _color_enabled()

_CLR_RED = '\033[91m' if _HAS_COLOR else ''
_CLR_GRN = '\033[92m' if _HAS_COLOR else ''
_CLR_YEL = '\033[93m' if _HAS_COLOR else ''
_CLR_BLU = '\033[94m' if _HAS_COLOR else ''
_CLR_CYN = '\033[96m' if _HAS_COLOR else ''
_CLR_GRY = '\033[90m' if _HAS_COLOR else ''
_CLR_BLD = '\033[1m'  if _HAS_COLOR else ''
_CLR_RST = '\033[0m'  if _HAS_COLOR else ''

# Width of the output panel
_W = 64

def _divider(char='-', color=_CLR_GRY):
    print(f"{color}{char * _W}{_CLR_RST}")

def _find_col(source_line: str, issue_msg: str) -> int:
    """
    Best-effort: return 0-based column of the problem on this line.
    Returns -1 if we can't determine a column.
    """
    safe = source_line

    # '=' instead of ':=' — find the bare = sign
    if 'Use ":="' in issue_msg:
        m = re.search(r'(?<![:<>!=])([A-Za-z_]\w*)\s*=(?!=)', safe)
        if m:
            return m.start(0) + len(m.group(1).rstrip())

    # Unbalanced ( — find the first unclosed (
    if 'unclosed "("' in issue_msg:
        depth = 0
        in_str = False
        for idx, ch in enumerate(safe):
            if ch == '"':
                in_str = not in_str
            elif not in_str:
                if ch == '(':
                    depth += 1
                elif ch == ')':
                    depth -= 1
                    if depth < 0:
                        return idx
        # Find last ( if all unclosed
        return safe.rfind('(')

    # Extra ) — find the first )  that closes too early
    if 'extra ")"' in issue_msg:
        depth = 0
        in_str = False
        for idx, ch in enumerate(safe):
            if ch == '"':
                in_str = not in_str
            elif not in_str:
                if ch == '(':
                    depth += 1
                elif ch == ')':
                    depth -= 1
                    if depth < 0:
                        return idx
        return -1

    # Unbalanced { — find the first unclosed {
    if 'unclosed "{"' in issue_msg or 'unclosed "{' in issue_msg:
        return safe.rfind('{')

    # Extra } — find the extra }
    if 'extra "}"' in issue_msg or 'extra "}"' in issue_msg:
        depth = 0
        for idx, ch in enumerate(safe):
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth < 0:
                    return idx
        return -1

    return -1   # no column info


def _show_issue(filename: str, lines: list, issue) -> None:
    """Print one issue in a clean, professional format."""
    is_err = (issue.severity == 'ERROR')
    tag    = 'error' if is_err else 'warning'
    color  = _CLR_RED if is_err else _CLR_YEL
    msg    = issue.message
    ln     = issue.line_no

    # Header:   error: Duplicate function name "foo"
    print(f'  {color}{_CLR_BLD}{tag}:{_CLR_RST} {_CLR_BLD}{msg}{_CLR_RST}')

    # Path:     --> path/to/file:12
    short_path = os.path.relpath(filename) if os.path.exists(filename) else filename
    loc_info = f'{short_path}:{ln}' if ln > 0 else short_path
    print(f'     {_CLR_BLU}-->{_CLR_RST} {_CLR_GRY}{loc_info}{_CLR_RST}')

    # Source snippet removed as per request ("remove the line results")
    pass

    print()


def _show_lint_report(filename: str, source: str, issues: list) -> None:
    """Pretty-print all lint issues with source context."""
    lines   = source.splitlines()
    errors  = [x for x in issues if x.severity == 'ERROR']
    warns   = [x for x in issues if x.severity == 'WARNING']

    if not issues:
        return

    print()
    for issue in issues:
        _show_issue(filename, lines, issue)

    if errors:
        summary_color = _CLR_RED
        status = 'fix errors before running'
    elif warns:
        summary_color = _CLR_YEL
        status = 'some warnings to check'
    else:
        summary_color = _CLR_GRN
        status = 'CLEAN'

    print(f'  {summary_color}{_CLR_BLD}{len(errors)} error(s), {len(warns)} warning(s){_CLR_RST}'
          f'  --  {status}\n')
    _divider()
    print()


# ─────────────────────────────────────────────────────────────────
#  Runtime error display
# ─────────────────────────────────────────────────────────────────

def _show_runtime_error(filename: str, exc: Exception, py_code: str) -> None:
    """Print a runtime crash in a readable way."""
    short = os.path.basename(filename) if filename else '<code>'
    print(f'  {_CLR_RED}{_CLR_BLD}runtime error:{_CLR_RST} {_CLR_BLD}{short}{_CLR_RST}')
    print(f'     {_CLR_BLU}-->{_CLR_RST} {_CLR_GRY}{filename}{_CLR_RST}')
    print()
    print(f'  {_CLR_RED}{type(exc).__name__}:{_CLR_RST} {exc}')
    print()
    _divider()



# ─────────────────────────────────────────────────────────────────
#  PPL language detection (for .txt files)
# ─────────────────────────────────────────────────────────────────

def _looks_like_ppl(code: str) -> bool:
    """
    Score a text file to decide if it contains HP Prime PPL code.
    Returns True if the score is high enough to be confident.
    """
    # Normalise for matching (upper-case copy, keep original for neg checks)
    up = code.upper()

    score = 0

    # ── Strong PPL indicators ─────────────────────────────────────
    # EXPORT FuncName() BEGIN  — the canonical PPL function header
    if re.search(r'EXPORT\s+\w+\s*\(', up):                 score += 4
    # HP Prime pragma header
    if '#PRAGMA MODE(' in up:                                    score += 4
    # := assignment  (Pascal/PPL, not Python/JS/C)
    if ':=' in code:                                             score += 3
    # BEGIN / END block structure
    if re.search(r'\bBEGIN\b', up):                            score += 2
    if re.search(r'\bEND;', up):                                score += 2
    # PPL-specific keywords
    for kw in ('LOCAL ', 'IFERR ', 'THEN\n', 'THEN ', 'UNTIL '):
        if kw in up:                                             score += 1
    # Common PPL built-ins unlikely to appear in other languages
    for fn in ('PRINT(', 'MSGBOX(', 'RECT(', 'PIXON(', 'DISP(', 'WAIT(', 'MAKELIST('):
        if fn in up:                                             score += 1

    # ── Negative indicators — other languages ────────────────────
    lines = code.splitlines()
    for line in lines[:40]:              # only check the top of the file
        s = line.strip()
        if s.startswith('def ')    or s.startswith('import ') or s.startswith('from '):
            score -= 3               # Python
        if s.startswith('#include') or s.startswith('int main'):
            score -= 3               # C / C++
        if s.startswith('function ') or s.startswith('const ') or s.startswith('let ') or s.startswith('var '):
            score -= 3               # JavaScript / TypeScript
        if s.startswith('public ') or s.startswith('private ') or s.startswith('class '):
            score -= 3               # Java / C#
        if s.startswith('fn ') or s.startswith('use ') or s.startswith('mod '):
            score -= 3               # Rust

    return score >= 5


# ─────────────────────────────────────────────────────────────────
#  Main
# ─────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='HP Prime PPL Emulator',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  ppl BSTVisualizer.hpprgm
  ppl BSTVisualizer.hpprgm --output bst_screen.png
  ppl --code "EXPORT T() BEGIN PRINT(1+1); END;"
  ppl BSTVisualizer.hpprgm --dump-python
        """
    )
    parser.add_argument('file',            nargs='?',            help='PPL source file (.hpprgm or .txt)')
    parser.add_argument('--code',  '-c',                         help='Inline PPL code string')
    parser.add_argument('--output','-o',   default='screen.png', help='Output PNG path (default: screen.png)')
    parser.add_argument('--dump-python',   action='store_true',  help='Print transpiled Python to stderr')
    parser.add_argument('--no-lint',       action='store_true',  help='Skip linting, run directly')
    parser.add_argument('--warnings-only', action='store_true',  help='Show warnings but do not fail on them')
    args = parser.parse_args()

    # ── Read source ──────────────────────────────────────────────
    filename = args.file or '<inline>'
    if args.code:
        ppl_code = args.code
    elif args.file:
        try:
            with open(args.file, 'r', encoding='utf-8', errors='replace') as f:
                ppl_code = f.read()
        except FileNotFoundError:
            print(f'  {_CLR_RED}{_CLR_BLD}error:{_CLR_RST} File not found: {_CLR_BLD}{args.file}{_CLR_RST}')
            sys.exit(1)
    else:
        ppl_code = sys.stdin.read()

    if not ppl_code.strip():
        print(f'  {_CLR_RED}{_CLR_BLD}error:{_CLR_RST} No PPL code provided.')
        sys.exit(1)

    # ── .txt files: verify the content is actually PPL ───────────
    if args.file and os.path.splitext(args.file)[1].lower() == '.txt':
        if not _looks_like_ppl(ppl_code):
            print(f'  {_CLR_RED}{_CLR_BLD}error:{_CLR_RST} {_CLR_BLD}{args.file}{_CLR_RST} does not appear to be PPL code.')
            print(f'  {_CLR_GRY}Hint: PPL files should contain EXPORT functions with BEGIN/END blocks and := assignments.{_CLR_RST}')
            sys.exit(1)

    # ── Stage 1: Lint ────────────────────────────────────────────
    if not args.no_lint:
        issues = lint(ppl_code, filename=filename)
        errors  = [x for x in issues if x.severity == 'ERROR']

        # Always show report so user knows it's OK
        _show_lint_report(filename, ppl_code, issues)

        if errors:
            sys.exit(1)   # stop here — don't run broken code

    # ── Stage 2: Transpile ───────────────────────────────────────
    from src.ppl_emulator.transpiler.core import transpile  # pyre-ignore
    try:
        python_code = transpile(ppl_code, out_path=args.output)
    except Exception as e:
        print(f'  {_CLR_RED}{_CLR_BLD}transpile error:{_CLR_RST} {os.path.basename(filename)}')
        print(f'     {_CLR_BLU}-->{_CLR_RST} {_CLR_GRY}{filename}{_CLR_RST}')
        print(f'\n  {_CLR_RED}SyntaxError:{_CLR_RST} {e}\n')
        _divider()
        if args.dump_python:
            traceback.print_exc()
        sys.exit(1)

    if args.dump_python:
        _divider('=', _CLR_BLU)
        print(f' {_CLR_BLD}TRANSPILED PYTHON{_CLR_RST}', file=sys.stderr)
        _divider('=', _CLR_BLU)
        for i, ln in enumerate(python_code.splitlines(), 1):
            print(f'{_CLR_GRY}{i:4}:{_CLR_RST} {ln}', file=sys.stderr)
        _divider('=', _CLR_BLU)

    # ── Stage 3: Execute ─────────────────────────────────────────
    ns = {'__name__': '__main__', '__file__': args.file or '<ppl>'}
    try:
        short = os.path.basename(filename) if filename else 'inline code'
        print(f"  {_CLR_CYN}{_CLR_BLD}RUNNING{_CLR_RST}  {short}")
        print(f"  {_CLR_GRY}(Close the graphics window or press Ctrl+C to stop){_CLR_RST}")
        _divider()
        print()
        exec(compile(python_code, '<ppl_transpiled>', 'exec'), ns)
        rt = ns.get('_rt')
        if rt and getattr(rt, '_input_cancelled', 0) > 0:
            n = rt._input_cancelled
            print(f"\n  {_CLR_YEL}note:{_CLR_RST} {n} INPUT call(s) were cancelled (headless mode). Results may be empty or default.")
        pass
    except KeyboardInterrupt:
        print(f"\n  {_CLR_YEL}{_CLR_BLD}[STOPPED]{_CLR_RST}  Execution interrupted by user.")
    except Exception as e:
        _show_runtime_error(filename, e, python_code)
        if args.dump_python:
            traceback.print_exc(file=sys.stderr)
        sys.exit(1)



if __name__ == '__main__':
    main()
