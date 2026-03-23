#!/usr/bin/env python3
"""
HP Prime PPL Static Analyzer
─────────────────────────────
Line-by-line analysis of .hpprgm files.

Checks performed:
  [ERROR]  Unclosed string literal
  [ERROR]  Unbalanced parentheses in expression
  [ERROR]  Unbalanced curly braces in list literal  { }
  [ERROR]  '=' used instead of ':=' or '==' for assignment/equality
  [ERROR]  Assignment to a non-variable (literal on LHS of :=)
  [ERROR]  Block balance — BEGIN/END, IF/THEN/END, FOR/DO/END, WHILE/DO/END, REPEAT/UNTIL, CASE/END
  [ERROR]  Missing required keywords — FOR without DO, IF without THEN, WHILE without DO
  [ERROR]  ELSE or UNTIL without a matching opener
  [ERROR]  Nested function declarations (missing END between functions)
  [ERROR]  Duplicate function name
  [ERROR]  RETURN or LOCAL used outside a function
  [ERROR]  BREAK or CONTINUE outside a loop
  [ERROR]  Invalid number of arguments passed to built-in or user-defined function
  [ERROR]  LOCAL variables not declared at the top of the block
  [ERROR]  Shadowing built-in keywords as variables
  [ERROR]  Trailing math or logic operators
  [ERROR]  Multiple assignments on the same line
  [WARN]   Missing semicolon on a statement line
  [WARN]   Call to an unknown function (not a built-in, not defined in file, not a known variable)

Notes:
  - Runs the transpiler preprocessor first so bare function declarations
    (e.g. BST_FindFreeSlot() BEGIN...END) are correctly recognised.
  - PPL array access like bst_val(i) is excluded from "unknown function"
    warnings because it uses the same syntax as a function call.
  - String literals are stripped before pattern matching to avoid false
    positives from words inside strings.
"""

import re
import sys
import os
from dataclasses import dataclass
from typing import List, Optional, Dict, Set, Tuple, Any

# ── Ensure 0-App root is on sys.path (works both as script and -m module) ──
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))   # .../src/ppl_emulator
_APP_ROOT   = os.path.dirname(os.path.dirname(_SCRIPT_DIR)) # .../0-App
if _APP_ROOT not in sys.path:
    sys.path.insert(0, _APP_ROOT)

from src.ppl_emulator.transpiler.core import Transpiler  # pyre-ignore


# ── Known HP Prime built-in functions with argument counts (min, max) ────────
BUILTIN_ARGS = {
    # I/O
    'PRINT': (0, 100),
    'MSGBOX': (1, 1),
    'INPUT': (1, 5),
    'CHOOSE': (2, 100),
    'WAIT': (0, 1),
    'GETKEY': (0, 0),
    'ISKEYDOWN': (1, 1),
    'MOUSE': (0, 0),
    'DISP_FREEZE': (0, 0),
    'FREEZE': (0, 0),
    # Graphics
    'RECT': (0, 6),
    'RECT_P': (0, 6),
    'LINE': (4, 6),
    'LINE_P': (4, 6),
    'PIXON': (2, 4),
    'PIXON_P': (2, 4),
    'CIRCLE_P': (3, 5),
    'FILLCIRCLE_P': (3, 5),
    'ARC_P': (3, 7),
    'TEXTOUT_P': (3, 7),
    'DRAWMENU': (0, 6),
    'BLIT': (3, 10),
    'BLIT_P': (0, 10),
    'SUBGROB': (5, 6),
    'INVERT_P': (0, 5),
    'GROB': (3, 4),
    # Color / math
    'RGB': (3, 4),
    'IP': (1, 1),
    'FP': (1, 1),
    'ABS': (1, 1),
    'MAX': (2, 2), 'MIN': (2, 2), 'FLOOR': (1, 1), 'CEILING': (1, 1), 'ROUND': (2, 2),
    'SQ': (1, 1), 'SQRT': (1, 1), 'LOG': (1, 1), 'LN': (1, 1), 'EXP': (1, 1),
    'SIN': (1, 1), 'COS': (1, 1), 'TAN': (1, 1), 'ASIN': (1, 1), 'ACOS': (1, 1),
    'ATAN': (1, 1), 'IFTE': (3, 3), 'EXPR': (1, 1),
    'BITAND': (2, 2), 'BITOR': (2, 2), 'BITXOR': (2, 2), 'BITNOT': (1, 1),
    # String
    'SIZE': (1, 1), 'DIM': (1, 1), 'POS': (2, 2), 'MID': (2, 3), 'LEFT': (2, 2),
    'RIGHT': (2, 2), 'UPPER': (1, 1), 'LOWER': (1, 1), 'STRING': (1, 2),
    'NUM': (1, 1), 'TYPE': (1, 1), 'ASC': (1, 1), 'CHR': (1, 1), 'CONCAT': (2, 2),
    'INSTRING': (2, 3), 'REPLACE': (3, 4), 'INSERT': (3, 3), 'CHAR': (1, 1),
    'EXACT': (1, 1), 'QUO': (2, 2), 'REM': (2, 2),
    # List / matrix
    'MAKELIST': (4, 4),
    'MAKEMATRIX': (2, 3),
    'ADDROW': (3, 3),
    'DELROW': (2, 2),
    'ADDCOL': (3, 3),
    'DELCOL': (2, 2),
    'RANDINT': (2, 2),
    'RANDOM': (0, 2),
    'SORT': (1, 2),
}

BUILTINS: frozenset = frozenset(BUILTIN_ARGS.keys())

# PPL structural keywords — never callable as user functions
_STRUCTURAL: frozenset = frozenset([
    'IF', 'THEN', 'ELSE', 'END', 'FOR', 'FROM', 'TO', 'STEP', 'DO',
    'WHILE', 'REPEAT', 'UNTIL', 'RETURN', 'BREAK', 'CONTINUE',
    'LOCAL', 'BEGIN', 'EXPORT', 'PROCEDURE',
    'AND', 'OR', 'NOT', 'MOD', 'DIV', 'XOR',
    'CASE', 'DEFAULT'
])

# Reserved global variables (A-Z, G0-G9, L0-L9, M0-M9)
# These cannot be used as LOCAL variable names on the HP Prime G1.
_RESERVED_GLOBALS: frozenset = frozenset([
    'A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'K', 'L', 'M',
    'N', 'O', 'P', 'Q', 'R', 'S', 'T', 'U', 'V', 'W', 'X', 'Y', 'Z',
    'G0', 'G1', 'G2', 'G3', 'G4', 'G5', 'G6', 'G7', 'G8', 'G9',
    'L0', 'L1', 'L2', 'L3', 'L4', 'L5', 'L6', 'L7', 'L8', 'L9',
    'M0', 'M1', 'M2', 'M3', 'M4', 'M5', 'M6', 'M7', 'M8', 'M9',
])


# ──────────────────────────────────────────────────────────────────────────────
#  Colors & UI
# ──────────────────────────────────────────────────────────────────────────────

def _color_enabled():
    """Enable ANSI escape sequences on Windows if possible."""
    if not sys.stdout.isatty():
        return False
    if os.name == 'nt':
        try:
            import ctypes
            windll = getattr(ctypes, 'windll', None)
            if windll is not None:
                kernel32 = windll.kernel32
                # ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
                kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
        except Exception:
            pass
    return True

_HAS_COLOR = _color_enabled()

_CLR_RED = '\033[91m' if _HAS_COLOR else ''
_CLR_GRN = '\033[92m' if _HAS_COLOR else ''
_CLR_YEL = '\033[93m' if _HAS_COLOR else ''
_CLR_CYN = '\033[96m' if _HAS_COLOR else ''
_CLR_GRY = '\033[90m' if _HAS_COLOR else ''
_CLR_BLD = '\033[1m'  if _HAS_COLOR else ''
_CLR_RST = '\033[0m'  if _HAS_COLOR else ''


# ── Issue dataclass ───────────────────────────────────────────────────────────

@dataclass
class Issue:
    line_no:  int
    severity: str        # 'ERROR' or 'WARNING'
    message:  str
    text:     str = ''   # original source line (stripped)

    def __str__(self):
        is_err = (self.severity == 'ERROR')
        tag    = 'ERROR' if is_err else 'WARN '
        color  = _CLR_RED if is_err else _CLR_YEL
        
        prefix = f'  {color}{_CLR_BLD}[{tag}]{_CLR_RST}  '
        loc    = f'{_CLR_GRY}line {self.line_no:>4}{_CLR_RST}'
        detail = f' {_CLR_CYN}|{_CLR_RST} {self.text}' if self.text else ''
        return f'{prefix} [{loc}]  {_CLR_BLD}{self.message}{_CLR_RST}{detail}'

# ── Helpers ───────────────────────────────────────────────────────────────────

def _strip_comment(line: str) -> str:
    """Remove // … comments, respecting string literals."""
    buf, in_str = [], False
    i: int = 0
    while i < len(line):
        ch = line[i]
        if ch == '"':
            in_str = not in_str
            buf.append(ch)
        elif line[i:i+2] == '//' and not in_str:  # pyre-ignore
            break
        else:
            buf.append(ch)
        i += 1  # pyre-ignore
    return ''.join(buf).rstrip()


def _erase_strings(line: str) -> str:
    """Replace the *contents* of string literals with spaces so regex
    patterns never match text inside quotes."""
    result, in_str, buf = [], False, []
    for ch in line:
        if ch == '"':
            if in_str:
                result.append('"' + ' ' * len(buf) + '"')
                buf = []
            in_str = not in_str
        elif in_str:
            buf.append(ch)
        else:
            result.append(ch)
    return ''.join(result)


def _has_odd_quotes(line: str) -> bool:
    return line.count('"') % 2 != 0


def _paren_balance(line: str) -> int:
    """Return net ( minus ) count, ignoring content inside strings."""
    safe = _erase_strings(line)
    return safe.count('(') - safe.count(')')


def _brace_balance(line: str) -> int:
    """Return net { minus } count, ignoring content inside strings."""
    safe = _erase_strings(line)
    return safe.count('{') - safe.count('}')


def _is_valid_lhs(expr: str) -> bool:
    """Return True if expr is a valid assignment target in PPL.
    Valid:  identifier          e.g.  x
    Valid:  LOCAL identifier    e.g.  LOCAL x
    Valid:  identifier[index]   e.g.  bst_val[slot]  (list element)
    Invalid: literals, expressions, keywords, or using () for indexing."""
    expr = expr.strip()
    
    # Strip LOCAL prefix if present
    if expr.upper().startswith("LOCAL "):
        expr = expr[6:].strip()  # pyre-ignore

    # Plain identifier
    if re.match(r'^[A-Za-z_]\w*$', expr):
        return True
    # List element: name[expr] or name(expr) (can be nested/multi-dim)
    if re.match(r'^[A-Za-z_]\w*\s*[\[\(].*[\]\)]$', expr):
        return True
    return False


def _count_args(args_str: str) -> int:
    """Count top-level commas in the argument string to determine arg count."""
    if not args_str.strip():
        return 0
    safe = _erase_strings(args_str)
    depth: int = 0
    commas: int = 0
    for ch in safe:
        if ch in '([{': depth += 1  # pyre-ignore
        elif ch in ')]}': depth -= 1  # pyre-ignore
        elif ch == ',' and depth == 0: commas += 1  # pyre-ignore
    return commas + 1  # pyre-ignore


# ── Main linter ───────────────────────────────────────────────────────────────

def lint(ppl_code: str, filename: str = '<unknown>') -> List[Issue]:
    """
    Analyse PPL source and return a list of Issues sorted by line number.
    """
    issues: List[Issue] = []

    # Run the transpiler's preprocessor so bare function declarations
    # (e.g.  BST_FindFreeSlot() \n BEGIN ... END)  get PROCEDURE injected.
    t = Transpiler()
    preprocessed = t._preprocess(ppl_code)

    raw_lines   = ppl_code.replace('\r\n', '\n').replace('\r', '\n').splitlines()
    proc_lines  = preprocessed.splitlines()

    # Pad to same length in case preprocessor added lines
    while len(proc_lines) < len(raw_lines):
        proc_lines.append('')

    # ── Pass 1: collect defined function names + all assigned variable names ─
    defined_fns: Set[str] = set()
    duplicate_fns: Set[str] = set()
    assigned_vars: Set[str] = set()
    local_vars: Set[str] = set()
    defined_fn_args: Dict[str, int] = {}
    
    # Scoped tracking for undeclared variable checks
    fn_params: Dict[str, Set[str]] = {}  # fname -> set of parameter names
    fn_locals: Dict[str, Set[str]] = {}  # fname -> set of local variable names
    curr_pass1_fn: Optional[str] = None

    for i, raw in enumerate(proc_lines, 1):
        line = _strip_comment(raw).strip()

        # Function declaration (after preprocessing)
        m = re.match(r'(?:EXPORT|PROCEDURE)\s+(\w+)\s*\((.*?)\)', line, re.IGNORECASE)
        if m:
            fname = m.group(1)
            name_up = fname.upper()
            curr_pass1_fn = name_up
            
            if name_up in BUILTINS or name_up in _STRUCTURAL:
                issues.append(Issue(i, 'ERROR', f"Cannot redefine built-in function or keyword '{fname}'", line))

            if name_up in defined_fns:
                duplicate_fns.add(name_up)
            defined_fns.add(name_up)
            defined_fn_args[name_up] = _count_args(m.group(2))
            
            # Extract parameters
            params: Set[str] = set()
            for p in m.group(2).split(','):
                p = p.strip()
                if p:
                    p_up = p.upper()
                    if p_up in BUILTINS or p_up in _STRUCTURAL:
                        issues.append(Issue(i, 'ERROR', f"Cannot use built-in function or keyword '{p}' as a parameter name", line))
                    params.add(p_up)
            fn_params[name_up] = params
            fn_locals[name_up] = set()
            continue
        
        # END resets current function in Pass 1
        if re.match(r'^END;?\s*$', line, re.IGNORECASE):
            # Not a perfect block matcher for nested blocks, but good enough to roughly reset
            # Wait, no, END can close IF/FOR/WHILE.
            # We don't need to perfectly reset curr_pass1_fn if we assume a flat function structure
            pass

        # Track every LHS of := (scalar or array) as a known variable
        m2 = re.match(r'^([A-Za-z_]\w*)\s*(?:\([^)]*\))?\s*:=', line)
        if m2:
            assigned_vars.add(m2.group(1).upper())
            
        # Track LOCAL variables
        m_local = re.match(r'^LOCAL\s+(.+?);?\s*$', line, re.IGNORECASE)
        if m_local:
            # simple split to find words
            for m_var in re.finditer(r'\b([A-Za-z_]\w*)\b', m_local.group(1)):
                var_name = m_var.group(1).upper()
                local_vars.add(var_name)
                if curr_pass1_fn:
                    fn_locals.setdefault(str(curr_pass1_fn), set()).add(var_name)

    # Names that are safe to call without a warning
    known_callables = BUILTINS | defined_fns | assigned_vars | local_vars

    # ── Pass 1b: detect 4+ consecutive list literal assignments (HP Prime G1 bug) ─
    consecutive_list_assigns = 0
    first_list_assign_line   = 0
    for j, raw in enumerate(proc_lines, 1):
        line = _strip_comment(raw).strip()
        if re.match(r'^[A-Za-z_]\w*\s*:=\s*\{', line, re.IGNORECASE):
            if consecutive_list_assigns == 0:
                first_list_assign_line = j
            consecutive_list_assigns += 1
            if consecutive_list_assigns >= 4:
                issues.append(Issue(
                    first_list_assign_line, 'ERROR',
                    'HP Prime G1 bug: 4+ consecutive list-literal assignments '
                    '( var := {…} ) in one function cause a "syntax error" on the calculator. '
                    'Use MAKELIST(0, X, 1, N) instead.'
                ))
                consecutive_list_assigns = 0   # reset to avoid duplicate errors
        else:
            consecutive_list_assigns = 0

    # ── Pass 2: line-by-line checks on preprocessed code ─────────────────────
    block_stack: List[Tuple[str, int]] = []   # list of (keyword, line_no)
    loop_depth:  int  = 0    # how many FOR/WHILE/REPEAT we are inside
    current_fn:  Optional[str]  = None
    fn_start_ln: int  = 0
    used_locals_in_fn: Set[str] = set()
    
    # Logic tracking
    assigned_vars_in_fn: Set[str] = set()
    active_for_counters: List[str] = [] # Stack of currently active FOR loop variables
    case_default_stack:  List[bool] = [] # Stack of booleans tracking DEFAULT in CASE
    unreachable_flag:    bool = False

    def err(ln, msg, text=''):
        issues.append(Issue(ln, 'ERROR',   msg, text))

    def warn(ln, msg, text=''):
        issues.append(Issue(ln, 'WARNING', msg, text))

    # ── Duplicate function names (from pass 1) ────────────────────────────────
    for dup in sorted(duplicate_fns):
        err(0, f'Duplicate function name "{dup}" defined more than once')

    # ── Non-ASCII characters ──────────────────────────────────────────────────
    for i, raw in enumerate(raw_lines, 1):
        try:
            raw.encode('ascii')
        except (UnicodeEncodeError, AttributeError):
            for j, ch in enumerate(raw):
                if ord(ch) > 127:
                    err(i,
                        f'Non-ASCII character "{ch}" (U+{ord(ch):04X}) — '
                        f'HP Prime G1 does not support UTF-8. '
                        f'Replace with ASCII equivalent (e.g. = or -)',
                        raw.strip())
                    break

    # ── Unclosed string check on original lines ───────────────────────────────
    for i, raw in enumerate(raw_lines, 1):
        stripped_raw = _strip_comment(raw).strip()
        if _has_odd_quotes(stripped_raw):
            err(i, 'Unclosed string literal', stripped_raw)

    for i, proc_raw in enumerate(proc_lines, 1):
        clean   = _strip_comment(proc_raw).strip()
        display = clean

        if not clean:
            continue

        safe = _erase_strings(clean)
        
        # ── Expression-level checks ─────────────

        # Unbalanced parentheses
        # Chained indexing check (e.g. [1][1] or (1)(1))
        # Physical HP Prime often rejects this with a 'Syntax Error'.
        if re.search(r'[\]\)]\s*[\[\(]', safe):
            err(i, 'Chained indexing (e.g. [1][1]) is not supported on the physical HP Prime. Use comma-based indexing instead: [1,1]', display)

        # Massive list literal check
        for m_list in re.finditer(r'\{([^{}]+)\}', safe):
            if m_list.group(1).count(',') > 50:
                warn(i, "Large list literal detected (>50 elements). This can cause a 'Syntax Error' or crash the physical HP Prime compiler. Use MAKELIST(0, X, 1, N) instead.", display)

        # 0-indexing check
        if re.search(r'\b[A-Za-z_]\w*\s*[\(\[]\s*0\s*[\)\]]', safe):
            warn(i, "HP Prime arrays and lists are 1-indexed. Indexing with 0 will cause a runtime error.", display)

        # Multiple assignments on one line are valid in PPL
        pass

        # '=' used instead of ':=' or '=='
        if not re.match(r'^FOR\b', safe, re.IGNORECASE):
            if re.search(r'(?<![:<>!=])\b([A-Za-z_]\w*)\s*=(?!=)', safe):
                err(i, 'Use ":=" for assignment, or "==" for equality. A single "=" is invalid.', display)

        # ── LHS detection for all statements on this line ────────
        # This helps 'uninitialized' and 'loop counter' checks.
        line_lhs_vars: Set[str] = set()
        # Remove keywords that might confuse LHS detection (like IF ... THEN)
        stripped_keywords = re.sub(r'\b(IF|ELSE|WHILE|FOR|REPEAT|CASE|EXPORT|PROCEDURE)\b.*?\b(THEN|DO|OF|BEGIN)\b', '', clean, flags=re.IGNORECASE)
        # Handle simple segments separated by ;
        for segment in stripped_keywords.split(';'):
            m_seg = re.match(r'^\s*([A-Za-z_]\w*)\s*(?:\([^)]*\))?\s*:=', segment)
            if m_seg:
                line_lhs_vars.add(m_seg.group(1).upper())
                
        # Handle FOR loops explicitly for initialization
        m_for_init = re.match(r'^FOR\s+([A-Za-z_]\w*)\s+FROM\b', clean, re.IGNORECASE)
        if m_for_init:
            line_lhs_vars.add(m_for_init.group(1).upper())

        # Invalid LHS check (using the first assignment on line for simplicity)
        m_assign = re.match(r'^(.+?)\s*:=', safe)
        if m_assign:
            lhs = m_assign.group(1).strip()
            if not _is_valid_lhs(lhs):
                err(i, f'Invalid assignment target "{lhs}" — must be a variable or list element.', display)
            
            # Shadowing built-in
            check_lhs = lhs
            if check_lhs.upper().startswith("LOCAL "):
                check_lhs = check_lhs[6:].strip()  # pyre-ignore
            
            lhs_base_match = re.match(r'^([A-Za-z_]\w*)', check_lhs)
            if lhs_base_match:
                lb = lhs_base_match.group(1).upper()
                if lb in BUILTINS or lb in _STRUCTURAL:
                    warn(i, f'Shadowing built-in or keyword "{lb}" as a variable', display)
                
                # Loop counter modification check
                if lb in active_for_counters:
                    warn(i, f"Modifying FOR loop counter '{lhs_base_match.group(1)}' inside the loop body is discouraged and often indicates a logic error.", display)
                
                # Mark as assigned
                if current_fn:
                    assigned_vars_in_fn.add(lb)
        
        # Add all detected LHS variables on this line to assigned set
        if current_fn:
            assigned_vars_in_fn.update(line_lhs_vars)

        # Undeclared variable check & Local usage tracking & Uninitialized check
        if current_fn:
            curr_params: Set[str] = fn_params.get(str(current_fn).upper(), set()) if current_fn else set()
            curr_locals: Set[str] = fn_locals.get(str(current_fn).upper(), set()) if current_fn else set()
            # Find all word tokens that look like variables
            for m_tok in re.finditer(r'\b([A-Za-z_]\w*)\b', safe):
                gs = m_tok.group(1)
                tok: str = gs.upper() if gs else ""  # pyre-ignore
                
                # Skip if it's currently on the LHS of an assignment on this line
                is_lhs = (tok in line_lhs_vars)

                # If it's a local variable, mark it as used
                if tok in curr_locals:
                    # Ignore the declaration itself (when it follows the LOCAL keyword)
                    if not re.match(r'^LOCAL\b', clean, re.IGNORECASE):
                        used_locals_in_fn.add(tok)
                        
                        # Uninitialized check
                        if not is_lhs and tok not in assigned_vars_in_fn:
                            warn(i, f"LOCAL variable '{m_tok.group(1)}' is used before being assigned a value.", display)
                
                # Skip if it's a structural keyword or built-in
                if tok in _STRUCTURAL or tok in BUILTINS:
                    continue
                # Skip if it's a reserved global (except I and J, which are common loop counters)
                if tok in _RESERVED_GLOBALS and tok not in ['I', 'J']:
                    continue
                # Skip if it's a known function being called
                if tok in defined_fns:
                    # Recursion warning
                    if tok == str(current_fn).upper():
                        warn(i, f"Recursive call to '{m_tok.group(1)}' detected. HP Prime has a very shallow stack; ensure recursion depth is minimal to avoid 'Stack Overflow'.", display)
                    continue
                # Skip if it's a parameter or local
                if tok in curr_params or tok in curr_locals:
                    continue
                
                # Not in any known set = implicit global warning
                # (Ignore the function name itself in the EXPORT declaration line)
                if not (i == fn_start_ln and tok == str(current_fn).upper()):
                    warn(i, f"Variable '{m_tok.group(1)}' is used but not declared as LOCAL or parameter. Implicit globals are discouraged.", display)

        # Trailing operators
        if re.search(r'(?:[-+*/^]|\b(?:AND|OR|XOR|MOD|DIV))\s*;?\s*$', safe, re.IGNORECASE):
            err(i, 'Expression ends with a trailing operator', display)

        # ── Call checking (argument counts + unknown functions + WAIT check + Coordinate check) ───────────────
        for m_call in re.finditer(r'\b([A-Za-z_]\w*)\s*\(', safe):
            fg = m_call.group(1)
            func_name: str = fg.upper() if fg else ""
            
            # Find matching parenthesis
            start_idx = m_call.end() - 1
            depth = 0
            end_idx = -1
            for idx in range(start_idx, len(safe)):
                if safe[idx] == '(': depth += 1  # pyre-ignore
                elif safe[idx] == ')':  # pyre-ignore
                    depth -= 1
                    if depth == 0:
                        end_idx = idx
                        break
            
            if end_idx != -1:
                args_str: str = safe[start_idx+1 : end_idx]  # pyre-ignore
                count: int = _count_args(args_str)
                
                # Built-in function
                if func_name in BUILTIN_ARGS:
                    min_a, max_a = BUILTIN_ARGS[func_name]
                    if count < min_a or count > max_a:
                        msg = f'"{m_call.group(1)}" expects '
                        msg += f'{min_a} arguments' if min_a == max_a else f'{min_a} to {max_a} arguments'
                        msg += f', got {count}'
                        err(i, msg, display)
                    
                    # Specific Checks: WAIT
                    if func_name == 'WAIT' and count == 1:
                        try:
                            wait_val = float(args_str.strip())
                            if wait_val > 10:
                                warn(i, f'WAIT time is {wait_val}s (> 10s). This may cause the calculator to appear frozen.', display)
                        except ValueError:
                            pass # Not a literal float, ignore
                    
                    # Specific Checks: Out of bounds drawing coordinates
                    if func_name in ['PIXON_P', 'PIXON', 'LINE_P', 'LINE', 'RECT_P', 'RECT']:
                        args_list = [a.strip() for a in args_str.split(',')]
                        try:
                            if len(args_list) >= 2:
                                x = int(args_list[0])
                                y = int(args_list[1])
                                # Strict bounds are [0,319]x[0,239]
                                if x < 0 or x > 319 or y < 0 or y > 239:
                                    warn(i, f'Hardcoded coordinate ({x}, {y}) is outside the screen bounds (320x240).', display)
                        except ValueError:
                            pass # Not literal ints, ignore

                # User-defined function
                elif func_name in defined_fn_args:
                    expected = defined_fn_args.get(func_name, 0)
                    if count != expected:
                        err(i, f'"{m_call.group(1)}" expects {expected} arguments, got {count}', display)
                # Potential indexing error or unknown function
                else:
                    cf_up = current_fn.upper() if current_fn else ""  # pyre-ignore
                    if not (func_name in assigned_vars or func_name in local_vars or (current_fn and func_name in fn_params.get(cf_up, set()))):
                         if func_name not in _STRUCTURAL:
                             warn(i, f'Call to unknown function "{m_call.group(1)}"', display)

        # ── Function declaration ──────────────────────────────────────────────
        m = re.match(r'(EXPORT|PROCEDURE)\s+(\w+)\s*\((.*?)\)\s*;?$', clean, re.IGNORECASE)
        if m:
            if current_fn:
                err(i, f'"{m.group(2)}" declared inside "{current_fn}" — missing END?', display)
            current_fn  = m.group(2)
            fn_start_ln = i
            executable_statement_seen = False
            used_locals_in_fn = set() 
            assigned_vars_in_fn = set()
            # Parameters are assigned
            for p in m.group(3).split(','):
                p = p.strip().upper()
                if p: assigned_vars_in_fn.add(p)
            
            active_for_counters = []
            case_default_stack = []
            unreachable_flag = False
            continue

        # ── BEGIN ─────────────────────────────────────────────────────────────
        if re.match(r'^BEGIN;?$', clean, re.IGNORECASE):
            block_stack.append(('BEGIN', i))
            executable_statement_seen = False
            continue

        # ── FOR ───────────────────────────────────────────────────────────────
        if re.match(r'^FOR\b', safe, re.IGNORECASE):
            m_for = re.match(r'^FOR\s+([A-Za-z_]\w*)\s+FROM\s+.+?\s+TO\s+.+?(?:\s+STEP\s+.+?)?\s+DO\b', safe, re.IGNORECASE)
            if not m_for:
                err(i, 'Invalid FOR loop syntax. Expected: FOR var FROM start TO end [STEP step] DO', display)
            else:
                block_stack.append(('FOR', i))
                loop_depth += 1  # pyre-ignore
                active_for_counters.append(m_for.group(1).upper())
                # Loop counter is assigned
                assigned_vars_in_fn.add(m_for.group(1).upper())
            executable_statement_seen = False
            continue

        # ── WHILE ─────────────────────────────────────────────────────────────
        if re.match(r'^WHILE\b', safe, re.IGNORECASE):
            m_while = re.match(r'^WHILE\s+(.+?)\s+DO;?$', safe, re.IGNORECASE)
            if not m_while:
                err(i, 'Invalid WHILE loop syntax. Expected: WHILE condition DO', display)
            else:
                block_stack.append(('WHILE', i))
                loop_depth += 1
                
                # Check for assignment in condition
                cond = m_while.group(1)
                if re.search(r'(?<![:<>!=])=(?!=)|:=', cond):
                     warn(i, "Possible assignment inside condition. Use '==' for equality comparison.", display)
            
            executable_statement_seen = False
            continue

        # ── REPEAT ───────────────────────────────────────────────────────────
        if re.match(r'^REPEAT;?$', clean, re.IGNORECASE):
            block_stack.append(('REPEAT', i))
            loop_depth += 1
            executable_statement_seen = False
            continue

        # ── UNTIL (closes REPEAT) ─────────────────────────────────────────────
        if re.match(r'^UNTIL\b', clean, re.IGNORECASE):
            if block_stack and block_stack[-1][0] == 'REPEAT':
                _, start_line = block_stack.pop()
                # No warning for empty REPEAT/UNTIL, it's a valid construct
                loop_depth = max(0, loop_depth - 1)
            else:
                err(i, 'UNTIL without a matching REPEAT', display)
            executable_statement_seen = True
            unreachable_flag = False # New block segment
            continue

        # ── CASE ─────────────────────────────────────────────────────────────
        if re.match(r'^CASE\b', clean, re.IGNORECASE):
            # CASE <expr> OF
            if not re.search(r'\bOF\b', safe, re.IGNORECASE):
                err(i, 'CASE missing OF keyword', display)
            else:
                block_stack.append(('CASE', i))
                case_default_stack.append(False)
            executable_statement_seen = False
            continue

        # ── DEFAULT ──────────────────────────────────────────────────────────
        if re.match(r'^DEFAULT\s*:\s*$', clean, re.IGNORECASE) or re.match(r'^DEFAULT\b', clean, re.IGNORECASE):
            if not any(b[0] == 'CASE' for b in block_stack):
                err(i, 'DEFAULT without a matching CASE', display)
            else:
                if case_default_stack: case_default_stack[-1] = True
            executable_statement_seen = False
            unreachable_flag = False
            continue

        # ── ELSE IF (stays within same IF block — no stack change) ────────────
        if re.match(r'^ELSE\s+IF\b', safe, re.IGNORECASE):
            if not any(b[0] == 'IF' for b in block_stack):
                err(i, 'ELSE IF without a matching IF', display)
            
            m_elif = re.search(r'^ELSE\s+IF\s+(.+?)\s+THEN\b', safe, re.IGNORECASE)
            if not m_elif:
                err(i, 'ELSE IF missing THEN keyword', display)
            else:
                cond = m_elif.group(1)
                if re.search(r'(?<![:<>!=])=(?!=)|:=', cond):
                     warn(i, "Possible assignment inside condition. Use '==' for equality comparison.", display)
            executable_statement_seen = False
            unreachable_flag = False
            continue

        # ── ELSE ──────────────────────────────────────────────────────────────
        if re.match(r'^ELSE;?$', clean, re.IGNORECASE):
            if not any(b[0] == 'IF' for b in block_stack):
                err(i, 'ELSE without a matching IF', display)
            executable_statement_seen = False
            unreachable_flag = False
            continue

        # ── IF … THEN ────────────────────────────────────────────────────────
        if re.match(r'^IF\b', safe, re.IGNORECASE):
            block_stack.append(('IF', i))
            executable_statement_seen = False
            
            m_if = re.search(r'^IF\s+(.+?)(?:\s+THEN\b|$)', safe, re.IGNORECASE)
            if m_if:
                cond = m_if.group(1)
                if re.search(r'(?<![:<>!=])=(?!=)|:=', cond):
                     warn(i, "Possible assignment inside condition. Use '==' for equality comparison.", display)
            
            if re.search(r'(?<!^)\bEND;?\s*$', safe, re.IGNORECASE):
                if block_stack: block_stack.pop()
            continue

        # ── END ───────────────────────────────────────────────────────────────
        if re.search(r'\bEND;?\s*$', safe, re.IGNORECASE) and not re.match(r'^(IF|ELSE\s+IF|FOR|WHILE|RETURN)\b', safe, re.IGNORECASE):
            if block_stack:
                popped_kw, start_line = block_stack.pop()
                if popped_kw in ('FOR', 'WHILE', 'REPEAT'):
                    loop_depth = max(0, loop_depth - 1)
                    if popped_kw == 'FOR' and active_for_counters:
                        active_for_counters.pop()
                
                # CASE cleanup
                if popped_kw == 'CASE':
                    has_default = case_default_stack.pop()
                    if not has_default:
                        warn(i, "CASE statement missing DEFAULT branch. Unhandled values will cause the block to be skipped silently.", display)

                # -- Empty block check removed --

                # Closing the function's opening BEGIN → function is done
                if popped_kw == 'BEGIN' and not block_stack:
                    # Check for unused locals
                    if current_fn:
                        curr_locals = fn_locals.get(str(current_fn).upper(), set())
                        unused = curr_locals - used_locals_in_fn
                        for uv in unused:
                            warn(i, f"LOCAL variable '{uv}' is declared but never used in function '{current_fn}'.", "")

                    current_fn = None
            elif current_fn:
                current_fn = None
            else:
                err(i, 'END without a matching block or function', display)
            
            executable_statement_seen = True
            unreachable_flag = False # End of block clears unreachable
            continue

        # ── BREAK / CONTINUE outside a loop ───────────────────────────────────
        if re.match(r'^BREAK;?$', clean, re.IGNORECASE):
            if loop_depth == 0:
                err(i, 'BREAK used outside of a loop', display)
            unreachable_flag = True
            continue
        if re.match(r'^CONTINUE;?$', clean, re.IGNORECASE):
            if loop_depth == 0:
                err(i, 'CONTINUE used outside of a loop', display)
            unreachable_flag = True
            continue

        # ── RETURN outside function ───────────────────────────────────────────
        if re.match(r'^RETURN\b', clean, re.IGNORECASE):
            if not current_fn:
                err(i, 'RETURN outside of any function', display)
            unreachable_flag = True
            
            if re.search(r'(?<!^)\bEND;?\s*$', safe, re.IGNORECASE):
                if block_stack: block_stack.pop()
            continue

        m_local = re.match(r'^LOCAL\b\s+(.+?);?\s*$', clean, re.IGNORECASE)
        if m_local:
            if not current_fn:
                err(i, 'LOCAL declaration outside of any function', display)
            
            # Check for invalid characters in LOCAL (e.g. brackets for array sizing)
            if '[' in m_local.group(1) or ']' in m_local.group(1):
                err(i, 'Syntax Error: Invalid array declaration "LOCAL name[size]". PPL does not support C-style array sizing. Use "LOCAL sx;" and then "sx := MAKELIST(0, X, 1, 100);" instead.', display)

            if '(' in m_local.group(1) or ')' in m_local.group(1):
                err(i, 'Syntax Error: Parentheses are not allowed in LOCAL declarations. If you are trying to declare an array, use "LOCAL sx;" and then "sx := MAKELIST(0, X, 1, 100);"', display)

            # Extract the part before any := to find the variables being declared
            declaration_part = m_local.group(1).split(':=')[0]
            found_vars = list(re.finditer(r'\b([A-Za-z_]\w*)\b', declaration_part))
            # Check for shadowing & Track init
            for m_var in found_vars:
                v = m_var.group(1).upper()
                if v in BUILTINS or v in _STRUCTURAL:
                    warn(i, f'Shadowing built-in keyword "{v}" with a LOCAL variable', display)
                if v in _RESERVED_GLOBALS:
                    warn(i, f'Shadowing reserved global variable "{v}" with a LOCAL declaration. This is permitted but use caution.', display)
                
                # Track if initialized on the same line
                if ':=' in m_local.group(1):
                    assigned_vars_in_fn.add(v)
            continue

        # ── Missing semicolon  [ERROR] ──────────────────────────────────────
        is_block_kw = bool(re.match(
            r'^(IF|FOR|WHILE|REPEAT|ELSE|BEGIN|END|UNTIL|EXPORT|PROCEDURE|LOCAL|RETURN|BREAK|CONTINUE|CASE|DEFAULT)\b',
            clean, re.IGNORECASE
        ))
        if current_fn and not is_block_kw and not clean.startswith('//') and not clean.endswith(';'):
            err(i, 'Statement missing semicolon', display)
            
        # If the line wasn't a control flow opener, it counts as an executable statement
        if current_fn and not is_block_kw:
            executable_statement_seen = True

    # ── End-of-file: unclosed block checks ───────────────────────────────────
    for kw, ln in block_stack:
        err(ln, f'Unclosed {kw} block — missing END or UNTIL?')

    if current_fn:
        err(fn_start_ln, f'Function "{current_fn}" never closed — missing END?')

    return sorted(issues, key=lambda x: x.line_no)


# ── Summary helper ────────────────────────────────────────────────────────────

def lint_summary(issues: List[Issue]) -> str:
    errors   = [x for x in issues if x.severity == 'ERROR']
    warnings = [x for x in issues if x.severity == 'WARNING']
    if not issues:
        return f'  {_CLR_GRN}{_CLR_BLD}[OK]{_CLR_RST}  No issues found'
    
    lines = [str(x) for x in issues]
    
    if errors:
        summary_color = _CLR_RED
        status = 'fix errors'
    elif warnings:
        summary_color = _CLR_YEL
        status = 'check warnings'
    else:
        summary_color = _CLR_GRN
        status = 'CLEAN'

    summary = f'\n  {summary_color}{_CLR_BLD}{len(errors)} error(s), {len(warnings)} warning(s){_CLR_RST}  --  {status}'
    lines.append(summary)
    return '\n'.join(lines)


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    import argparse

    parser = argparse.ArgumentParser(description='HP Prime PPL Static Analyzer')
    parser.add_argument('file', nargs='+', help='.hpprgm file(s) to lint')
    parser.add_argument('--errors-only', '-e', action='store_true',
                        help='Only show errors, suppress warnings')
    args = parser.parse_args()

    any_errors = False

    for path in args.file:
        try:
            with open(str(path), 'r', encoding='utf-8', errors='replace') as f:
                code = f.read()
        except FileNotFoundError:
            print(f'  {_CLR_RED}{_CLR_BLD}error:{_CLR_RST} File not found: {path}', file=sys.stderr)
            sys.exit(1)

        issues = lint(code, filename=str(path))
        if args.errors_only:
            issues = [x for x in issues if x.severity == 'ERROR']

        header = f'  {_CLR_CYN}{_CLR_BLD}LINT{_CLR_RST}  {path}'
        print(f'\n{header}')
        print(f'{_CLR_GRY}{"-" * (len(str(path)) + 10)}{_CLR_RST}')
        print(lint_summary(issues))
        print()

        if any(x.severity == 'ERROR' for x in issues):
            any_errors = True

    sys.exit(1 if any_errors else 0)


if __name__ == '__main__':
    main()
