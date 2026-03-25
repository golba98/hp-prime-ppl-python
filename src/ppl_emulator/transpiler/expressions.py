# ─────────────────────────────────────────────────────────────────
#  String & Text Utilities and Expression Transpilation
# ─────────────────────────────────────────────────────────────────

import re
from .constants import _OPS, _PYTHON_RESERVED, BUILTINS, _STRUCTURAL  # pyre-ignore

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

def _xform(expr):
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
            res.append(f'"{_escape_content(content)}"')  # type: ignore
        else:
            e = val
            # { } -> PPLList([ ])
            e = e.replace('{', 'PPLList([').replace('}', '])')
            
            # Color literals
            e = re.sub(r'#([0-9A-Fa-f]+)h\b', lambda m: str(int(m.group(1), 16)), e)
            e = re.sub(r'#(\d+)(?![0-9A-Fa-fh])', r'\1', e)
            
            # Comma indexing name[i, j] -> name[i][j]
            def repl_comma_idx(m):
                name = m.group(1)
                indices = [idx.strip() for idx in m.group(2).split(',')]
                return _safe_name(name) + "".join(f"[{idx}]" for idx in indices)
            e = re.sub(r'\b([A-Za-z_]\w*)\s*\[([^\[\]]+?,[^\[\]]+?)\]', repl_comma_idx, e)
            
            # Paren indexing name(i) -> name(i) (callable PPLList)
            def repl_paren_idx(m):
                name = m.group(1)
                if name.upper() in BUILTINS or name.upper() in _STRUCTURAL: return m.group(0)
                return _safe_name(name) + "(" + m.group(2) + ")"
            e = re.sub(r'\b([A-Za-z_]\w*)\s*\(([^()]+)\)', repl_paren_idx, e)
            
            # HP Prime Unicode-arrow function names: B→R, R→B, etc.
            e = re.sub(r'([A-Za-z_]\w*)→([A-Za-z_]\w*)', r'\1_to_\2', e)
            # HP Prime native math symbols
            e = e.replace('\u2212', '-')          # − (U+2212) Unicode minus → ASCII minus
            e = e.replace('\u03c0', 'pi')          # π (U+03C0) pi constant
            e = e.replace('\u03A0', 'pi')          # Π uppercase variant
            e = re.sub(r'\u221a([\w.]+)', r'SQRT(\1)', e)   # √x  → SQRT(x)
            e = re.sub(r'\u221a(\([^()]*\))', r'SQRT\1', e) # √(x) → SQRT(x)
            # Ops
            for pat, rep in _OPS: e = re.sub(pat, rep, e, flags=re.IGNORECASE)
            e = re.sub(r'(?<!\*)\^(?!\*)', '**', e)
            e = e.replace('₂', ' ').replace('₁₀', ' ').replace('₁₆', ' ')
            
            # Rename reserved Python names
            e = re.sub(r'\b(set|list|map|filter|input|type|dir|id|hex|oct|bin|str|yield|lambda|class|del|raise|with|assert|async|await)\b', 
                       lambda m: f"_ppl_{m.group(1).lower()}", e, flags=re.IGNORECASE)
            res.append(e)
    
    return ''.join(res).strip()
