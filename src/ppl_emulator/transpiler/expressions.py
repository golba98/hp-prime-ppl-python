# ─────────────────────────────────────────────────────────────────
#  String & Text Utilities and Expression Transpilation
# ─────────────────────────────────────────────────────────────────

import re
from .constants import _OPS, _PYTHON_RESERVED, BUILTINS, _STRUCTURAL, BUILTINS_ZERO_ARGS  # pyre-ignore

# Python class names emitted by _xform itself (e.g. {..} -> PPLList([..])).
# These must not be treated as PPL variable references in repl_var.
_XFORM_TYPES = frozenset(['PPLLIST', 'PPLSTRING'])

def _safe_name(name):
    if name.lower() in _PYTHON_RESERVED:
        return f"_ppl_{name.lower()}"
    return name

def _escape_content(s):
    """Escape backslashes and quotes for Python string literals."""
    return s.replace('\\', '\\\\').replace('"', '\\"')

def _strip_comment(line: str) -> str:
    buf: list[str] = []
    in_str: bool = False
    i: int = 0
    while i < len(line):
        if line[i] == '"':
            if not in_str: in_str = True; buf.append('"')
            elif i + 1 < len(line) and line[i+1] == '"': buf.append('""'); i += 1
            else: in_str = False; buf.append('"')
        elif in_str and str(line)[i] == '\\' and i + 1 < len(line) and line[i+1] == '"':
            buf.append('\\"'); i += 1
        elif str(line)[i:i+2] == '//' and not in_str: break  # type: ignore
        else: buf.append(line[i])
        i += 1
    return ''.join(buf).rstrip()

def _erase_strings(line):
    res, in_str, i = [], False, 0
    while i < len(line):
        if line[i] == '"':
            if not in_str: in_str = True; res.append('"')
            elif i + 1 < len(line) and line[i+1] == '"': res.append('  '); i += 1
            else: in_str = False; res.append('"')
        elif in_str and line[i] == '\\' and i + 1 < len(line) and line[i+1] == '"':
            res.append('  '); i += 1
        elif in_str: res.append(' ')
        else: res.append(line[i])
        i += 1
    return ''.join(res)

def _split_locals(text):
    """Split LOCAL declarations on commas, respecting strings, braces and parentheses."""
    parts, cur, depth, in_s, i = [], [], 0, False, 0
    while i < len(text):
        ch = text[i]
        if ch == '"':
            if not in_s: in_s = True; cur.append('"')
            else:
                if i + 1 < len(text) and text[i+1] == '"':
                    cur.append('""'); i += 1
                else:
                    in_s = False; cur.append('"')
        elif not in_s and ch in '{[(':
            depth += 1
            cur.append(ch)
        elif not in_s and ch in '}])':
            depth -= 1
            cur.append(ch)
        elif not in_s and ch == ',' and depth == 0:
            parts.append(''.join(cur).strip()); cur = []
        else:
            cur.append(ch)
        i += 1
    parts.append(''.join(cur).strip())
    return [p for p in parts if p]


def _slice_bound(val, is_start):
    """Convert a PPL 1-based slice bound to a Python 0-based bound."""
    s = val.strip()
    if not s:
        return ''
    if is_start:
        try:
            return str(int(s) - 1)
        except ValueError:
            return f'({s})-1'
    return s

def _ppl_to_py_slice(range_str):
    """Convert a PPL 'start:end' range string to a Python slice string."""
    parts = range_str.split(':', 1)
    start_py = _slice_bound(parts[0], True)
    end_py   = _slice_bound(parts[1] if len(parts) > 1 else '', False)
    return f'{start_py}:{end_py}'

def _xform(expr, line_no=None, known_vars=None):
    """Transform a PPL expression to valid Python, respecting strings."""
    parts, buf, in_str, i = [], [], False, 0
    while i < len(expr):
        ch = expr[i]
        if ch == '"':
            if not in_str:
                if buf: parts.append(('code', ''.join(buf))); buf = []
                in_str = True; buf.append('"')
            else:
                if i + 1 < len(expr) and expr[i+1] == '"':
                    buf.append('""'); i += 1
                else:
                    buf.append('"'); in_str = False
                    parts.append(('str', ''.join(buf))); buf = []
        elif in_str and ch == '\\' and i + 1 < len(expr) and expr[i+1] == '"':
            buf.append('\\"'); i += 1
        else:
            buf.append(ch)
        i += 1
    if buf: parts.append(('code', ''.join(buf)))

    res: list[str] = []
    for kind, val in parts:
        if kind == 'str':
            # PPL "" or \" -> Python \"
            content = str(val)[1:-1].replace('""', '"').replace('\\"', '"')  # type: ignore
            res.append(f'PPLString("{_escape_content(content)}")')  # type: ignore
        else:
            e = val
            # { } -> PPLList([ ])
            e = e.replace('{', 'PPLList([').replace('}', '])')
            
            # Color literals
            # Strip leading zeros from plain decimal literals (e.g., 05 -> 5)
            # but leave # prefixed tokens alone — they are handled below.
            e = re.sub(r'(?<!\.)(?<!#)\b0+(\d+)\b', r'\1', e)
            # #AFh  -> explicit hex
            e = re.sub(r'#([0-9A-Fa-f]+)[hH]\b', lambda m: str(int(m.group(1), 16)), e)
            # #1010b -> explicit binary
            e = re.sub(r'#([01]+)[bB]\b', lambda m: str(int(m.group(1), 2)), e)
            # #RRGGBB -> 6-digit colour constant (no suffix required)
            e = re.sub(r'#([0-9A-Fa-f]{6})\b', lambda m: str(int(m.group(1), 16)), e)
            # #XY (2-4 digit partial hex) -> fallback conversion
            e = re.sub(r'#([0-9A-Fa-f]{1,5})\b', lambda m: str(int(m.group(1), 16)), e)
            
            # PPL complex literal: (3, 4) -> complex(3, 4)
            # Match (number, number) NOT preceded by an identifier (which would be a call)
            e = re.sub(
                r'(?<![A-Za-z0-9_])\(\s*(-?[\d.]+(?:[eE][+-]?\d+)?)\s*,\s*(-?[\d.]+(?:[eE][+-]?\d+)?)\s*\)',
                r'complex(\1, \2)', e)

            # Comma indexing name[i, j] -> name[i][j]
            # Discrepancy 2 fix: PPLList/PPLMatrix.__getitem__ now handles 1-based conversion
            # internally, so we no longer subtract 1 here.
            def repl_comma_idx(m):
                name = m.group(1)
                indices = [idx.strip() for idx in m.group(2).split(',')]
                return _safe_name(name) + "".join(f"[{idx}]" for idx in indices)
            e = re.sub(r'\b([A-Za-z_]\w*)\s*\[([^\[\]]+?,[^\[\]]+?)\]', repl_comma_idx, e)
            
            # Paren indexing: name(i) -> name[i-1]
            # Special case: slice/range notation name(s:e) or name(r1:r2, c1:c2)
            def repl_paren_idx(m):
                name = m.group(1)
                name_up = name.upper()
                if name_up in BUILTINS or name_up in _STRUCTURAL: return m.group(0)
                
                # If it's a known local/global variable, treat it as list/string indexing
                # If not sure, we use parentheses so it remains a call (PPLList/PPLString __call__ will handle it)
                # But Task 2 says "it must emit m[r-1][c-1]", so we prioritize [] for likely vars.
                safe = _safe_name(name)
                args_str = m.group(2)
                
                if ':' in args_str:
                    args = [a.strip() for a in args_str.split(',')]
                    if len(args) == 1:
                        # Single range: m(1:2) -> m[0:2]
                        return f'{safe}[{_ppl_to_py_slice(args[0])}]'
                    if len(args) == 2 and ':' in args[0] and ':' in args[1]:
                        # Two ranges: m(1:2, 2:3) -> _ppl_slice_2d(m, 0, 2, 1, 3)
                        r = args[0].split(':', 1)
                        c_arg = args[1].split(':', 1)
                        r0 = _slice_bound(r[0], True);  r1 = _slice_bound(r[1], False)
                        c0 = _slice_bound(c_arg[0], True);  c1 = _slice_bound(c_arg[1], False)
                        return f'_ppl_slice_2d({safe}, {r0}, {r1}, {c0}, {c1})'
                
                if known_vars is not None and name_up in known_vars:
                    # Discrepancy 2 fix: pass index as-is; PPLList.__getitem__ handles 1-based.
                    args = [a.strip() for a in args_str.split(',')]
                    return safe + "".join(f"[{a}]" for a in args)
                
                return safe + "(" + args_str + ")"
            e = re.sub(r'\b([A-Za-z_]\w*)\s*\(([^()]+)\)', repl_paren_idx, e)
            
            # HP Prime Unicode-arrow function names: B→R, R→B, etc.
            e = re.sub(r'([A-Za-z_]\w*)→([A-Za-z_]\w*)', r'\1_to_\2', e)
            # HP Prime native math symbols
            e = e.replace('\u2212', '-')          # − (U+2212) Unicode minus → ASCII minus
            e = e.replace('\ue003', '1j')          # U+E003 HP Prime imaginary unit → Python 1j
            e = e.replace('\u2148', '1j')          # ⅈ (U+2148) imaginary unit → Python 1j
            e = e.replace('\u03c0', 'pi')          # π (U+03C0) pi constant
            e = e.replace('\u03A0', 'pi')          # Π uppercase variant
            e = re.sub(r'\u221a([\w.]+)', r'SQRT(\1)', e)   # √x  → SQRT(x)
            e = re.sub(r'\u221a(\([^()]*\))', r'SQRT\1', e) # √(x) → SQRT(x)
            e = re.sub(r'(\w+)\u00b2', r'(\1)**2', e)         # X² → (X)**2
            # Ops
            for pat, rep in _OPS: e = re.sub(pat, rep, e, flags=re.IGNORECASE)
            e = re.sub(r'(?<!\*)\^(?!\*)', '**', e)
            e = e.replace('₂', ' ').replace('₁₀', ' ').replace('₁₆', ' ')
            
            # Rename reserved Python names (already done above, but let's be thorough)
            # and wrap all other identifiers in _rt.GET_VAR(...)
            def repl_var(m):
                name = m.group(1)
                name_up = name.upper()
                ln_arg = f", {line_no}" if line_no is not None else ""
                tail = e[m.end():].lstrip()
                in_call = tail.startswith('(')

                # Declared local/global variables always use GET_VAR, even when they
                # shadow a builtin name (e.g. LOCAL roots shadows the ROOTS builtin).
                if known_vars is not None and name_up in known_vars:
                    if name_up in _XFORM_TYPES:
                        return name
                    return f"_rt.GET_VAR('{name_up}'{ln_arg})"

                # Python logical operators are already lowercased by _OPS; do NOT uppercase
                # them back — `AND`/`OR`/`NOT` are not valid Python keywords (only lowercase).
                _PY_LOGICALS = {'AND': 'and', 'OR': 'or', 'NOT': 'not'}
                if name_up in _PY_LOGICALS:
                    return _PY_LOGICALS[name_up]

                # Builtins and structural keywords pass through unchanged (uppercase)
                if name_up in BUILTINS or name_up in _STRUCTURAL:
                    if name_up in BUILTINS_ZERO_ARGS and not in_call:
                        return f"{name_up}()"
                    return name_up  # force uppercase so _rt.BUILTIN bindings work
                if name.lower() in _PYTHON_RESERVED:
                    return f"_ppl_{name.lower()}"

                if in_call:
                    # Transpiler-generated Python types must not go through GET_VAR
                    if name_up in _XFORM_TYPES:
                        return name
                    # Unknown identifier in call position: treat as a direct Python function call.
                    return name

                return f"_rt.GET_VAR('{name_up}'{ln_arg}).value"

            # Important: only match identifiers that are NOT preceded by a dot (attribute access)
            # or part of a larger name.
            e = re.sub(r'\b([A-Za-z_]\w*)\b', repl_var, e)
            
            # Post-process: dereference GET_VAR calls unless they are bare arguments in a call list.
            # We want: FUNC(_rt.GET_VAR('A')) if 'A' is passed alone.
            # Use regex to find GET_VAR().value and strip .value if preceded by ( or , and followed by ) or ,
            e = re.sub(r'([\(,]\s*)_rt\.GET_VAR\((.+?)\)\.value(\s*[,\)])', r'\1_rt.GET_VAR(\2)\3', e)
            
            res.append(e)
    
    return ''.join(res).strip()
