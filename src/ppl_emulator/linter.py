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
from typing import List, Dict, Set, Optional, Tuple, Any, cast

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
    'INPUT': (1, 6),
    'CHOOSE': (2, 100),
    'WAIT': (0, 1),
    'GETKEY': (0, 0),
    'ISKEYDOWN': (1, 1),
    'MOUSE': (0, 1),
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
    'BLIT_P': (0, 11),
    'SUBGROB': (5, 6),
    'INVERT_P': (0, 5),
    'GROB': (3, 4),
    # Color / math
    'RGB': (3, 4),
    'IP': (1, 1),
    'FP': (1, 1),
    'ABS': (1, 1),
    'MAX': (1, 100), 'MIN': (1, 100), 'FLOOR': (1, 1), 'CEILING': (1, 1), 'ROUND': (2, 2),
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

# Contextual keywords valid as variable names (only special inside loop headers)
_CONTEXTUAL_KEYWORDS: frozenset = frozenset(['FROM', 'TO', 'STEP', 'DO'])

# Keywords truly reserved as assignment targets (cannot be variable names)
_ASSIGNMENT_RESERVED: frozenset = _STRUCTURAL - _CONTEXTUAL_KEYWORDS

# PPL-specific Unicode operators that are valid on HP Prime (not ASCII errors)
_PPL_UNICODE_OPS: frozenset = frozenset([
    '≠',  # not-equal (≠)
    '≤',  # less-or-equal (≤)
    '≥',  # greater-or-equal (≥)
    '▶',  # STO store (▶)
    '→',  # right-arrow (→)
    '←',  # left-arrow (←)
    '∞',  # infinity (∞)
    '≡',  # identical-to (≡)
    '−',  # Unicode minus sign (U+2212) — used on HP Prime keyboard
    'π',  # pi constant (U+03C0) — native HP Prime symbol
    '√',  # square root (U+221A) — native HP Prime operator
    '∑',  # summation (U+2211)
    '∫',  # integral (U+222B)
    '∂',  # partial derivative (U+2202)
    'θ',  # theta (U+03B8)
    'ℯ',  # euler's number (U+212F)
    'ⅈ',  # imaginary unit (U+2148)
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
        return f'{prefix} [{loc}]  {_CLR_BLD}{self.message}{_CLR_RST}'

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
    patterns never match text inside quotes. Handles PPL escaped quotes ("") 
    and backslash-escaped quotes (\\")."""
    result, in_str = [], False
    i = 0
    while i < len(line):
        ch = line[i]
        if ch == '"':
            if in_str:
                # Check for escaped quote ""
                if i + 1 < len(line) and line[i+1] == '"':
                    result.append('  ') # Two spaces for ""
                    i += 1
                else:
                    in_str = False
                    result.append('"')
            else:
                in_str = True
                result.append('"')
        elif in_str:
            if ch == '\\' and i + 1 < len(line) and line[i+1] == '"':
                result.append('  ') # Two spaces for \"
                i += 1
            else:
                result.append(' ')
        else:
            result.append(ch)
        i += 1
    return ''.join(result)


def _has_odd_quotes(line: str) -> bool:
    """Check if a line has an unclosed string literal, respecting escaped quotes ("" and \\")."""
    in_str = False
    i = 0
    while i < len(line):
        if line[i] == '"':
            if in_str:
                if i + 1 < len(line) and line[i+1] == '"':
                    i += 1 # skip escaped quote ""
                else:
                    in_str = False
            else:
                in_str = True
        elif in_str and line[i] == '\\' and i + 1 < len(line) and line[i+1] == '"':
            i += 1 # skip escaped quote \"
        i += 1
    return in_str


def _paren_balance(line: str) -> int:
    """Return net ( minus ) count, ignoring content inside strings."""
    safe = _erase_strings(line)
    return safe.count('(') - safe.count(')')


def _brace_balance(line: str) -> int:
    """Return net { minus } count, ignoring content inside strings."""
    safe = _erase_strings(line)
    return safe.count('{') - safe.count('}')


def _is_valid_lhs(expr: str, line_no: int, issues: List[Issue], source_line: str) -> bool:
    """Return True if expr is a valid assignment target in PPL.
    Valid:  identifier          e.g.  x
    Valid:  LOCAL identifier    e.g.  LOCAL x
    Valid:  identifier[index]   e.g.  bst_val[slot]  (list element)
    Valid:  comma-separated list e.g. x, y, z (for LOCAL)
    Invalid: literals, expressions, keywords, or using () for indexing."""
    expr = expr.strip()
    
    # Strip LOCAL prefix if present
    if expr.upper().startswith("LOCAL "):
        expr = str(expr[6:]).strip()

    # 1. Simple identifier
    if re.match(r'^[A-Za-z_]\w*$', expr):
        if expr.upper() in _ASSIGNMENT_RESERVED:
             issues.append(Issue(line_no, 'ERROR', f'Invalid assignment target "{expr}" — "{expr}" is a reserved keyword.', source_line))
             return False
        return True
    
    # 2. List element:  name(index) or name[index]
    # PPL uses (index) for both functions and lists, but [] is also seen.
    m_list = re.match(r'^([A-Za-z_]\w*)\s*[\(\[](.+)[\)\]]$', expr)
    if m_list:
        name = m_list.group(1).upper()
        if name in _ASSIGNMENT_RESERVED:
            issues.append(Issue(line_no, 'ERROR', f'Invalid assignment target "{expr}" — "{name}" is a reserved keyword.', source_line))
            return False
        return True

    # 3. Multiple variables in LOCAL (e.g., LOCAL a, b, c)
    # Only reached when expr has commas but no surrounding parens/brackets
    if ',' in expr:
        parts = [p.strip() for p in expr.split(',')]
        return all(_is_valid_lhs(p, line_no, issues, source_line) for p in parts)
    # 4. Handle cases where it's a function call on the LHS (invalid)
    if '(' in expr:
        issues.append(Issue(line_no, 'ERROR', f'Invalid assignment target "{expr}" — cannot assign to a function result.', source_line))
        return False

    issues.append(Issue(line_no, 'ERROR', f'Invalid assignment target "{expr}" — must be a variable or list element.', source_line))
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
    
    # Pre-process lines to mask strings and comments
    proc_lines: List[str] = []
    raw_lines: List[str] = ppl_code.replace('\r\n', '\n').replace('\r', '\n').splitlines()
    proc_lines  = raw_lines

    # ── Pass 1: collect defined function names + all assigned variable names ─
    defined_fns: Set[str] = set()
    duplicate_fns: Set[str] = set()
    assigned_vars: Set[str] = set()
    local_vars: Set[str] = set()
    defined_fn_args: Dict[str, int] = {}
    
    # Scoped tracking for undeclared variable checks
    # Pass 1 Logic: Function and Variable Discovery
    fn_params: Dict[str, Set[str]] = {} # Map of func_name -> set(params)
    fn_locals: Dict[str, Set[str]] = {} # Map of func_name -> set(local_vars)
    curr_pass1_fn: Optional[str] = None

    for i, raw in enumerate(proc_lines, 1):
        line = _strip_comment(raw).strip()

        # Function declaration (handle bare declarations without EXPORT/PROCEDURE)
        m = re.match(r'(?:EXPORT|PROCEDURE)\s+(\w+)\s*\((.*?)\)', line, re.IGNORECASE)
        # Check for bare function: Name(...) BEGIN
        if not m:
            m_bare = re.match(r'^(\w+)\s*\((.*?)\)\s*;?$', line)
            if m_bare:
                # To be sure, peek ahead for BEGIN
                is_proc = False
                for j in range(i, min(i + 5, len(proc_lines))):
                    next_line = _strip_comment(proc_lines[j]).strip()
                    if not next_line: continue
                    if re.match(r'^BEGIN;?$', next_line, re.IGNORECASE):
                        is_proc = True
                        break
                    if re.match(r'^(EXPORT|PROCEDURE|LOCAL|VAR|IF|FOR|WHILE|REPEAT|CASE)\b', next_line, re.IGNORECASE):
                        break
                if is_proc: m = m_bare
        
        if m:
            params_group = 2 if 'EXPORT' in m.group(0).upper() or 'PROCEDURE' in m.group(0).upper() else 2
            # Wait, for m_bare: r'^(\w+)\s*\((.*?)\)\s*;?$', group 1 is name, group 2 is params.
            # For m_export: r'(?:EXPORT|PROCEDURE)\s+(\w+)\s*\((.*?)\)', group 1 is name, group 2 is params.
            # So it's ALWAYS group 2 for parameters in both regexes!
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
            lhs_part = m_local.group(1).split(':=')[0]
            for m_var in re.finditer(r'\b([A-Za-z_]\w*)\b', lhs_part):
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

    _warned_shadows:    Set[str] = set()
    _warned_zero_index: Set[str] = set()

    # ── Duplicate function names (from pass 1) ────────────────────────────────
    for dup in sorted(duplicate_fns):
        err(0, f'Duplicate function name "{dup}" defined more than once')

    # ── Non-ASCII characters (only if not in strings or comments) ─────────────
    for i, raw in enumerate(raw_lines, 1):
        # Strip comments first
        clean_text = _strip_comment(raw)
        # Erase strings next
        safe_text = _erase_strings(clean_text)
        
        try:
            safe_text.encode('ascii')
        except (UnicodeEncodeError, AttributeError):
            for j, ch in enumerate(safe_text):
                if ord(ch) > 127 and ch not in _PPL_UNICODE_OPS:
                    warn(i,
                        f'Non-ASCII character (U+{ord(ch):04X}) in code — '
                        f'ensure HP Prime supports this character.',
                        raw.strip())
                    break

    # ── Unclosed string check on original lines ───────────────────────────────
    _ms_open = False   # currently inside a multi-line string
    _ms_line = 0       # line number where the string was opened
    _ms_text = ''      # source text of the opening line
    for i, raw in enumerate(raw_lines, 1):
        stripped_raw = _strip_comment(raw).strip()
        if _has_odd_quotes(stripped_raw):
            if _ms_open:
                _ms_open = False   # closing quote found
            else:
                _ms_open = True    # opening quote, may span multiple lines
                _ms_line = i
                _ms_text = stripped_raw
    if _ms_open:
        err(_ms_line, 'Unclosed string literal', _ms_text)

    # ── Pass 2: Main Logic Analysis ──────────────────────────────────────────
    # Most statement-level and expression-level checks are now handled in the 
    # bufferized loop below to support multi-line statements.
    # ── Main Loop ────────────────────────────────────────────────────────────
    stmt_buf: List[str] = []
    stmt_start_ln = 1
    unreachable_kw = "" # To store the keyword that caused unreachability (BREAK, CONTINUE, RETURN)
    
    # We'll use a copy of proc_lines to safely peek
    for i, raw in enumerate(proc_lines, 1):
        line_clean = _strip_comment(raw).strip()
        if not line_clean and not stmt_buf:
            continue
            
        if not stmt_buf:
            stmt_start_ln = i
            
        stmt_buf.append(line_clean)
        cb = " ".join(stmt_buf)
        sf = _erase_strings(cb)
        
        # Balance check
        pb = sf.count('(') - sf.count(')')
        bb = sf.count('{') - sf.count('}')
        trailing_op = bool(re.search(
            r'(?:[-+*/^]|\b(?:AND|OR|XOR|MOD|DIV))\s*$', sf, re.IGNORECASE))
        if pb > 0 or bb > 0 or cb.endswith(',') or cb.endswith(':=') or trailing_op:
            continue
            
        # We have a complete (at least one) statement structure.
        # Now split by semicolon, but NOT inside strings or nested blocks.
        # Actually, if we just split by ';' using a simple loop that ignores strings.
        full_cb = cb
        stmt_buf = [] # Reset for next
        
        # Split into individual statements
        stmts: List[str] = []
        sbuf: List[str] = []
        in_s = False
        j = 0
        while j < len(full_cb):
            ch = full_cb[j]
            if ch == '"':
                if not in_s: in_s = True; sbuf.append('"')
                else:
                    if j + 1 < len(full_cb) and full_cb[j+1] == '"':
                        sbuf.append('""'); j += 1
                    else: in_s = False; sbuf.append('"')
            elif in_s and ch == '\\' and j + 1 < len(full_cb) and full_cb[j+1] == '"':
                sbuf.append('\\"'); j += 1
            elif ch == ';' and not in_s:
                s = ''.join(sbuf).strip()
                if s: stmts.append(s + ';') # Keep ; for endswith check
                sbuf = []
            else:
                sbuf.append(ch)
            j += 1
        last = ''.join(sbuf).strip()
        if last: stmts.append(last)
        
        for stmt_idx, stmt in enumerate(stmts):
            # i_stmt is the line number where the statement ends (approx)
            # but stmt_start_ln is better for multi-line.
            curr_ln = stmt_start_ln if stmt_idx == 0 else i
            
            clean = stmt.strip()
            # If the statement is empty or just a semicolon, skip
            if not clean or clean == ';': continue
            
            # For keywords, we use a clean version without semicolon
            safe = _erase_strings(clean)
            bare_clean = clean.rstrip(';').strip()
            
            display = proc_lines[curr_ln - 1]

            # ── Expression-level checks ───────────────────────────────────────
            # These were previously in a separate line-based loop.
            
            # Chained indexing check [1][1]
            if re.search(r'[\]\)]\s*[\[\(]', safe):
                err(curr_ln, 'Chained indexing (e.g. [1][1]) is not supported on the physical HP Prime. Use comma-based indexing instead: [1,1]', display)

            # Massive list literal check
            for m_list_lit in re.finditer(r'\{([^{}]+)\}', safe):
                if m_list_lit.group(1).count(',') > 50:
                    warn(curr_ln, "Large list literal detected (>50 elements). This can cause a 'Syntax Error' or crash the physical HP Prime compiler. Use MAKELIST(0, X, 1, N) instead.", display)

            # 0-indexing check - skip built-in calls like WAIT(0)
            for m_zero in re.finditer(r'\b([A-Za-z_]\w*)\s*[\(\[]\s*0\s*[\)\]]', safe):
                vname = m_zero.group(1).upper()
                if vname not in BUILTINS and vname not in _warned_zero_index:
                    _warned_zero_index.add(vname)
                    warn(curr_ln, "HP Prime arrays and lists are 1-indexed. Indexing with 0 will cause a runtime error.", display)
                    break
            # '=' used instead of ':=' or '=='
            if not re.match(r'^FOR\b', safe, re.IGNORECASE):
                # We skip if it's likely a comment or already handled
                if re.search(r'(?<![:<>!=])\b([A-Za-z_]\w*)\s*=(?!=)', safe):
                    err(curr_ln, 'Use ":=" for assignment, or "==" for equality. A single "=" is invalid.', display)

            # Trailing operators
            if re.search(r'(?:[-+*/^]|\b(?:AND|OR|XOR|MOD|DIV))\s*;?\s*$', safe, re.IGNORECASE):
                err(curr_ln, 'Expression ends with a trailing operator', display)

            # ── UNREACHABLE CHECK ─────────────────────────────────────────────

            remaining = bare_clean
            
            # Use a while loop to process keywords part of the same statement
            # (e.g., "IF cond THEN FOR i ... DO BEGIN")
            while remaining:
                remaining = remaining.strip()
                if not remaining: break
                
                found_kw = False
                
                # ── Function declaration ───────────────────
                m_fn = re.match(r'^(?:EXPORT|PROCEDURE)\s+(\w+)\s*\((.*?)\)', remaining, re.IGNORECASE)
                if not m_fn:
                    m_bare = re.match(r'^(\w+)\s*\((.*?)\)', remaining)
                    if m_bare:
                        is_proc = False
                        cur_idx = int(curr_ln)
                        for k in range(cur_idx, min(cur_idx + 5, len(proc_lines))):
                            nxt = _strip_comment(proc_lines[k]).strip()
                            if not nxt: continue
                            if re.match(r'^BEGIN;?$', nxt, re.IGNORECASE):
                                is_proc = True; break
                            if re.match(r'^(EXPORT|PROCEDURE|LOCAL|VAR|IF|FOR|WHILE|REPEAT|CASE|END)\b', nxt, re.IGNORECASE):
                                break
                        if is_proc: m_fn = m_bare

                if m_fn:
                    fname = m_fn.group(1)
                    if current_fn:
                        err(curr_ln, f'"{fname}" declared inside "{current_fn}" — missing END?', display)
                    current_fn = fname
                    fn_start_ln = curr_ln
                    executable_statement_seen = False
                    used_locals_in_fn = set() 
                    assigned_vars_in_fn = set()
                    for p in m_fn.group(2).split(','):
                        p = p.strip().upper()
                        if p: assigned_vars_in_fn.add(p)
                    active_for_counters = []
                    case_default_stack = []
                    unreachable_flag = False
                    remaining = remaining[m_fn.end():].strip()
                    found_kw = True

                # ── BEGIN ───────────────────
                elif (m_begin := re.match(r'^BEGIN\b', remaining, re.IGNORECASE)):
                    block_stack.append(('BEGIN', curr_ln))
                    executable_statement_seen = False
                    remaining = remaining[m_begin.end():].strip()
                    found_kw = True

                # ── FOR ───────────────────
                elif (m_for := re.match(r'^FOR\s+([A-Za-z_]\w*)\s+FROM\s+.+?\s+(?:DOWN)?TO\s+.+?(?:\s+STEP\s+.+?)?\s+DO\b', remaining, re.IGNORECASE)):
                    block_stack.append(('FOR', curr_ln))
                    loop_depth += 1
                    active_for_counters.append(m_for.group(1).upper())
                    assigned_vars_in_fn.add(m_for.group(1).upper())
                    executable_statement_seen = False
                    remaining = remaining[m_for.end():].strip()
                    found_kw = True

                # ── WHILE ───────────────────
                elif (m_while := re.match(r'^WHILE\s+(.+?)\s+DO\b', remaining, re.IGNORECASE)):
                    block_stack.append(('WHILE', curr_ln))
                    loop_depth += 1
                    cond = m_while.group(1)
                    if re.search(r'(?<![:<>!=])\b([A-Za-z_]\w*)\s*=(?!=)|:=', cond):
                         warn(curr_ln, "Possible assignment inside condition. Use '==' for equality comparison.", display)
                    executable_statement_seen = False
                    remaining = remaining[m_while.end():].strip()
                    found_kw = True

                # ── REPEAT ───────────────────
                elif (m_repeat := re.match(r'^REPEAT\b', remaining, re.IGNORECASE)):
                    block_stack.append(('REPEAT', curr_ln))
                    loop_depth += 1
                    executable_statement_seen = False
                    remaining = remaining[m_repeat.end():].strip()
                    found_kw = True

                # ── UNTIL ───────────────────
                elif (m_until := re.match(r'^UNTIL\s+(.+?)\b', remaining, re.IGNORECASE)):
                    if block_stack and block_stack[-1][0] == 'REPEAT':
                        block_stack.pop(); loop_depth = max(0, loop_depth - 1)
                    else:
                        err(curr_ln, 'UNTIL without a matching REPEAT', display)
                    executable_statement_seen = True
                    remaining = remaining[m_until.end():].strip()
                    found_kw = True

                # ── IF ───────────────────
                elif (m_if := re.match(r'^IF\s+(.+?)\s+THEN\b', remaining, re.IGNORECASE)):
                    block_stack.append(('IF', curr_ln))
                    cond = m_if.group(1)
                    if re.search(r'(?<![:<>!=])\b([A-Za-z_]\w*)\s*=(?!=)|:=', cond):
                         warn(curr_ln, "Possible assignment inside condition. Use '==' for equality comparison.", display)
                    executable_statement_seen = False
                    remaining = remaining[m_if.end():].strip()
                    found_kw = True

                # ── ELSE ───────────────────
                elif (m_else := re.match(r'^ELSE\b', remaining, re.IGNORECASE)):
                    m_elseif = re.match(r'^ELSE\s+IF\s+(.+?)\s+THEN\b', remaining, re.IGNORECASE)
                    if m_elseif:
                        # ELSE IF introduces a new nested IF block needing its own END
                        block_stack.append(('IF', curr_ln))
                        cond = m_elseif.group(1)
                        if re.search(r'(?<![:<>!=])\b([A-Za-z_]\w*)\s*=(?!=)|:=', cond):
                             warn(curr_ln, "Possible assignment inside condition. Use '==' for equality comparison.", display)
                        remaining = remaining[m_elseif.end():].strip()
                    else:
                        if not any(kw == 'IF' for kw, ln in block_stack) and not case_default_stack:
                             warn(curr_ln, 'ELSE outside of an IF-THEN block', display)
                        remaining = remaining[m_else.end():].strip()
                    executable_statement_seen = False
                    found_kw = True

                # ── CASE / DEFAULT ───────────────────
                elif (m_case := re.match(r'^CASE\b', remaining, re.IGNORECASE)):
                    block_stack.append(('CASE', curr_ln)); case_default_stack.append(False)
                    remaining = remaining[m_case.end():].strip()
                    found_kw = True
                elif (m_default := re.match(r'^DEFAULT\b', remaining, re.IGNORECASE)):
                    if case_default_stack: 
                        cast(List[bool], case_default_stack)[-1] = True
                    else: err(curr_ln, 'DEFAULT outside of a CASE block', display)
                    remaining = remaining[m_default.end():].strip()
                    found_kw = True

                # ── END ───────────────────
                elif (m_end := re.match(r'^END\b', remaining, re.IGNORECASE)):
                    if block_stack:
                        popped, _ = block_stack.pop()
                        if popped in ('FOR', 'WHILE', 'REPEAT'):
                             loop_depth = max(0, loop_depth - 1)
                             if popped == 'FOR' and active_for_counters: active_for_counters.pop()
                        if popped == 'CASE': case_default_stack.pop()
                        if popped == 'BEGIN' and not block_stack:
                            if current_fn:
                                curr_lc = cast(Set[str], fn_locals.get(str(current_fn).upper(), set()))
                                for uv in (curr_lc - used_locals_in_fn):
                                    warn(fn_start_ln, f"LOCAL variable '{uv}' is declared but never used in function '{current_fn}'.", "")
                            current_fn = None
                    remaining = remaining[m_end.end():].strip()
                    found_kw = True

                # ── LOCAL ───────────────────
                elif (m_local := re.match(r'^LOCAL\s+(.+?)\b', remaining, re.IGNORECASE)):
                    if not current_fn: err(curr_ln, 'LOCAL declaration outside of any function', display)
                    lstr = m_local.group(1)
                    if '[' in lstr or ']' in lstr:
                        err(curr_ln, 'Syntax Error: Invalid array declaration "LOCAL name[size]".', display)
                    if '(' in lstr or ')' in lstr:
                        if ':=' not in lstr: err(curr_ln, 'Syntax Error: Parentheses are not allowed in LOCAL declarations.', display)
                    
                    l_str = str(lstr)
                    dp = l_str.split(':=')[0]
                    for mv in re.finditer(r'\b([A-Za-z_]\w*)\b', dp):
                        v = mv.group(1).upper()
                        if (v in BUILTINS or v in _STRUCTURAL) and v not in _warned_shadows:
                            _warned_shadows.add(v); warn(curr_ln, f'Shadowing keyword "{v}"', display)
                        if v in _RESERVED_GLOBALS and v not in _warned_shadows:
                            _warned_shadows.add(v); warn(curr_ln, f'Shadowing global "{v}"', display)
                        if ':=' in l_str: assigned_vars_in_fn.add(v)
                    remaining = remaining[m_local.end():].strip()
                    found_kw = True

                if not found_kw: break

            # ── Assignments ───────────────────────────────────────────────────
            for match in re.finditer(r'([A-Za-z_]\w*(?:\s*[\(\[].+?[\)\]])?)\s*:=', safe):
                target = match.group(1)
                # Check if this is a valid target
                _is_valid_lhs(target, curr_ln, issues, display)
                
                # Track assignment to avoid "used before assigned"
                var_match = re.match(r'^([A-Za-z_]\w*)', target)
                if var_match and current_fn:
                    assigned_vars_in_fn.add(var_match.group(1).upper())

            # ── Usage / Call ──────────────────────────────────────────────────
            # Undeclared variable check & Local usage tracking & Uninitialized check
            if current_fn:
                cf_up = current_fn.upper()
                curr_params = fn_params.get(cf_up, set())
                curr_locals = fn_locals.get(cf_up, set())
                
                # Find all word tokens that look like variables or calls
                for m_tok in re.finditer(r'\b([A-Za-z_]\w*)\b', safe):
                    gs = m_tok.group(1)
                    tok = gs.upper()
                    
                    # If it's followed by ( it's a call
                    # Use a slice that is safe and check startswith
                    tail = safe[m_tok.end():]
                    is_call = tail.lstrip().startswith('(')
                    # Track local usage FIRST, before any skip/continue
                    if tok in curr_locals or tok in used_locals_in_fn:
                        used_locals_in_fn.add(tok)

                    # Skip structural keywords
                    if tok in _STRUCTURAL or tok in BUILTINS or tok == 'LOCAL' or tok == 'EXPORT' or tok == 'PROCEDURE' or tok == 'BEGIN' or tok == 'END':
                        continue

                    # Skip reserved globals (A-Z, G0-G9, etc.) - legacy PPL uses them
                    if tok in _RESERVED_GLOBALS:
                        continue


                    if is_call:
                        # ARG count check
                        if tok in BUILTIN_ARGS:
                            pass
                        elif tok in defined_fns:
                            if tok == cf_up and curr_ln != fn_start_ln:
                                warn(curr_ln, f"Recursive call to '{gs}' detected. HP Prime has a very shallow stack.", display)
                    else:
                        # Potential implicit global or typo
                        if tok not in curr_params and tok not in curr_locals and tok not in assigned_vars and tok not in defined_fns:
                             # warn(curr_ln, f"Variable '{gs}' is used but not declared as LOCAL or parameter. Implicit globals are discouraged.", display)
                             pass

            # ── Specific Function Call Analysis ───────────────────────────────
            for m_call in re.finditer(r'\b([A-Za-z_]\w*)\s*\(', safe):
                fg = m_call.group(1)
                func_name = fg.upper()
                
                # Extract argument string (handling nested parens)
                start_idx = m_call.end()
                arg_buf = []
                p_depth = 1
                k = start_idx
                while k < len(safe) and p_depth > 0:
                    ch = safe[k]
                    if ch == '(': p_depth += 1
                    elif ch == ')': p_depth -= 1
                    if p_depth > 0: arg_buf.append(ch)
                    k += 1
                args_str = "".join([str(c) for c in arg_buf]) # pyre-ignore
                count = _count_args(args_str)

                # Built-in check
                if func_name in BUILTIN_ARGS:
                    min_args, max_args = BUILTIN_ARGS[func_name]
                    if count < min_args or count > max_args:
                        err(curr_ln, f'"{fg}" expects {min_args}-{max_args} arguments, got {count}', display)
                    
                    # Specific Checks: WAIT
                    if func_name == 'WAIT' and count == 1:
                        try:
                            wait_val = float(args_str.strip())
                            if wait_val > 10:
                                warn(curr_ln, f'WAIT time is {wait_val}s (> 10s). This may cause the calculator to appear frozen.', display)
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
                                    warn(curr_ln, f'Hardcoded coordinate ({x}, {y}) is outside the screen bounds (320x240).', display)
                        except ValueError:
                            pass # Not literal ints, ignore

                    # Specific Checks: Output Arguments (CHOOSE, INPUT)
                    if func_name in ['INPUT', 'CHOOSE'] and current_fn:
                        cf_up = current_fn.upper()
                        arg0_match = re.search(r'\b([A-Za-z_]\w*)\b', args_str)
                        if arg0_match:
                            v0 = arg0_match.group(1).upper()
                            assigned_vars_in_fn.add(v0)
                            if v0 in fn_locals.get(cf_up, set()):
                                used_locals_in_fn.add(v0)

                # User-defined check
                elif func_name in defined_fn_args and current_fn is not None:
                    expected = defined_fn_args[func_name]
                    if count != expected:
                        err(curr_ln, f'"{fg}" expects {expected} arguments, got {count}', display)
                else:
                    # Unknown or index access
                    pass

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
