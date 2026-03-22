# ─────────────────────────────────────────────────────────────────
#  HP Prime PPL → Python Transpiler
#  Handles: functions, LOCAL arrays, FOR/WHILE/IF/ELSE/REPEAT,
#           := assignment, graphics calls, PRINT, math ops.
# ─────────────────────────────────────────────────────────────────

import re

# ── Expression-level substitutions ──────────────────────────────

_OPS = [
    (r'\bAND\b',  'and'),
    (r'\bOR\b',   'or'),
    (r'\bNOT\b',  'not '),
    (r'\bMOD\b',  '%'),
    (r'\bDIV\b',  '//'),
    (r'\bXOR\b',  '^'),
    (r'≠',        '!='),
    (r'≤',        '<='),
    (r'≥',        '>='),
    (r'<>',       '!='),
]

def _xform(expr):
    """Transform a PPL expression to valid Python."""
    expr = str(expr).strip()

    # #NNNNh hex color literals → integer  (must come before decimal #N rule)
    expr = re.sub(r'#([0-9A-Fa-f]+)h\b',
                  lambda m: str(int(m.group(1), 16)), expr)
    # #N decimal color literals → N  (not followed by hex digit or 'h')
    expr = re.sub(r'#(\d+)(?![0-9A-Fa-fh])', r'\1', expr)

    # {a, b, ...} PPL list literals → PPLList([a, b, ...])
    expr = re.sub(r'\{([^{}]*)\}',
                  lambda m: f'PPLList([{m.group(1)}])', expr)

    # PPL list access: ident[i, j, ...] -> ident[i][j]...
    def repl_comma_idx(m):
        name = m.group(1)
        indices = [idx.strip() for idx in m.group(2).split(',')]
        return name + "".join(f"[{idx}]" for idx in indices)
    expr = re.sub(r'\b([A-Za-z_]\w*)\s*\[([^\[\]]+?,[^\[\]]+?)\]', repl_comma_idx, expr)

    for pat, rep in _OPS:
        expr = re.sub(pat, rep, expr, flags=re.IGNORECASE)
    # ^ → ** (power), but not ^^
    expr = re.sub(r'(?<!\*)\^(?!\*)', '**', expr)
    return expr


def _split_locals(text):
    """Split LOCAL declarations on commas, but not commas inside { } braces."""
    parts, cur, depth = [], [], 0
    for ch in text:
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
        elif ch == ',' and depth == 0:
            parts.append(''.join(cur))
            cur = []
            continue
        cur.append(ch)
    parts.append(''.join(cur))
    return parts


# ── Transpiler class ─────────────────────────────────────────────

# ── Built-in keywords and functions for PPL ──────────────────────

BUILTINS = frozenset([
    'PRINT','MSGBOX','INPUT','CHOOSE','WAIT','GETKEY','MOUSE','SIZE',
    'RECT','RECT_P','LINE','LINE_P','PIXON','PIXON_P','CIRCLE_P',
    'FILLCIRCLE_P','ARC_P','TEXTOUT_P','BLIT_P','DRAWMENU','DISP_FREEZE',
    'FREEZE',
    'RGB','IP','FP','ABS','MAX','MIN','FLOOR','CEILING','ROUND','SQ',
    'SQRT','LOG','LN','EXP','SIN','COS','TAN','IFTE','RANDOM','RANDINT',
    'MAKELIST','SUBGROB','GROB','INVERT_P',
])

_STRUCTURAL = frozenset([
    'IF','THEN','ELSE','END','FOR','FROM','TO','STEP','DO','WHILE',
    'REPEAT','UNTIL','RETURN','BREAK','CONTINUE','LOCAL','BEGIN',
    'EXPORT','PROCEDURE',
])

_PPL_KEYWORDS = BUILTINS | _STRUCTURAL


class Transpiler:

    def __init__(self):
        self._out      = []       # output lines (no indent prefix)
        self._indent   = 0
        self._cur_fn   = None     # current function name
        self._fn_order = []       # (fname, params) in source order
        self._export   = None     # first EXPORT function = entry point
        self._export_params = []
        self._locals   = {}       # fname → {local var names}
        self._globals  = {}       # fname → {non-local assigned vars}

    # ── Helpers ──────────────────────────────────────────────────

    def _pad(self):
        return '    ' * self._indent

    def _emit(self, line=''):
        self._out.append(self._pad() + line if line else '')

    def _emit0(self, line):
        """Emit at column 0 regardless of indent."""
        self._out.append(line)

    def _strip_comment(self, line):
        """Remove // … comments, respecting string literals."""
        buf, in_str = [], False
        i = 0
        while i < len(line):
            ch = line[i]
            if ch == '"':
                in_str = not in_str
                buf.append(ch)
            elif line[i:i+2] == '//' and not in_str:
                break
            else:
                buf.append(ch)
            i += 1
        return ''.join(buf).rstrip()

    # ── Preprocessing ────────────────────────────────────────────

    def _preprocess(self, code):
        """
        Two passes before transpilation:
        1. Add PROCEDURE keyword to bare (non-EXPORT) function declarations.
        2. Expand single-line  IF cond THEN stmt; END;  to multi-line form.
        """
        lines = code.replace('\r\n', '\n').replace('\r', '\n').splitlines()

        # ── Pass 1: inject PROCEDURE ──────────────────────────────
        result = []
        for i, line in enumerate(lines):
            nc = self._strip_comment(line).strip()   # stripped of comments
            # Matches: identifier(params) alone on a line?
            m = re.match(r'^([A-Za-z_]\w*)\s*\(([^)]*)\)\s*;?$', nc)
            if m and m.group(1).upper() not in _PPL_KEYWORDS:
                # Look ahead for BEGIN (skip blank/comment-only lines)
                is_proc = False
                for j in range(i + 1, min(i + 10, len(lines))):
                    ns = self._strip_comment(lines[j]).strip()
                    if not ns: continue
                    if re.match(r'^BEGIN;?$', ns, re.IGNORECASE):
                        is_proc = True
                        break
                    # If we see another structural keyword, it's not a bare proc
                    if re.match(r'^(EXPORT|PROCEDURE|LOCAL|VAR|IF|FOR|WHILE|REPEAT|CASE)\b', ns, re.IGNORECASE):
                        break
                
                if is_proc:
                    indent_ws = line[: len(line) - len(line.lstrip())]
                    line = indent_ws + 'PROCEDURE ' + nc.rstrip(';')
            result.append(line)

        # ── Pass 2: expand single-line IF/THEN/ELSE/END ──────────
        expanded = []
        for line in result:
            nc = self._strip_comment(line).strip()
            indent_ws = line[: len(line) - len(line.lstrip())]

            # IF cond THEN trueStmt(s); ELSE falseStmt(s); END;
            # We match IF...THEN, everything until ELSE, then everything until END.
            m = re.match(
                r'^(IF\s+.+?\s+THEN)\s+(.+?)\s*ELSE\s+(.+?)\s*END;?\s*$',
                nc, re.IGNORECASE
            )
            if m:
                expanded.append(indent_ws + m.group(1))
                for stmt in m.group(2).split(';'):
                    s = stmt.strip()
                    if s: expanded.append(indent_ws + '  ' + s + ';')
                expanded.append(indent_ws + 'ELSE')
                for stmt in m.group(3).split(';'):
                    s = stmt.strip()
                    if s: expanded.append(indent_ws + '  ' + s + ';')
                expanded.append(indent_ws + 'END;')
                continue

            # IF cond THEN stmt(s); END;
            m = re.match(
                r'^(IF\s+.+?\s+THEN)\s+(.+?)\s*END;?\s*$',
                nc, re.IGNORECASE
            )
            if m:
                expanded.append(indent_ws + m.group(1))
                for stmt in m.group(2).split(';'):
                    s = stmt.strip()
                    if s: expanded.append(indent_ws + '  ' + s + ';')
                expanded.append(indent_ws + 'END;')
                continue

            expanded.append(line)

        return '\n'.join(expanded)

    # ── First pass: collect variable scopes ──────────────────────

    def _first_pass(self, code):
        cur, loc, asgn = None, set(), set()

        for raw in code.splitlines():
            line = self._strip_comment(raw).strip()
            if not line:
                continue

            # Function declaration (EXPORT or PROCEDURE)
            m = re.match(r'(EXPORT|PROCEDURE)\s+(\w+)\s*\((.*?)\)', line, re.IGNORECASE)
            if m:
                if cur:
                    self._locals[cur]  = loc
                    self._globals[cur] = asgn - loc
                cur, loc, asgn = m.group(2), set(), set()
                params = [p.strip() for p in m.group(3).split(',') if p.strip()]
                loc.update(params)
                kind = m.group(1).upper()
                self._fn_order.append((cur, m.group(3)))
                if kind == 'EXPORT':
                    self._export = cur  # last EXPORT in file = entry point
                    self._export_params = params
                continue

            # LOCAL declarations
            m = re.match(r'LOCAL\s+(.+?);?\s*$', line, re.IGNORECASE)
            if m and cur:
                for d in m.group(1).split(','):
                    d = d.strip()
                    am = re.match(r'(\w+)\[', d)
                    loc.add(am.group(1) if am else d.split(':=')[0].strip())
                continue

            # Track simple assigned variables (not list-element assignments)
            m = re.match(r'(\w+)(?:\[.+?\])?\s*:=', line)
            if m and cur:
                asgn.add(m.group(1))

        if cur:
            self._locals[cur]  = loc
            self._globals[cur] = asgn - loc

    # ── Header / footer ──────────────────────────────────────────

    def _emit_header(self):
        self._emit0("# Auto-generated by HP PPL Emulator — do not edit")
        self._emit0("import sys, math")
        self._emit0("from runtime import HPPrimeRuntime, PPLList")
        self._emit0("")
        self._emit0("_rt = HPPrimeRuntime()")
        self._emit0("")
        for fn in [
            'PRINT','MSGBOX',
            'RECT','RECT_P','LINE','LINE_P','PIXON','PIXON_P',
            'CIRCLE_P','FILLCIRCLE_P','ARC_P','TEXTOUT_P','BLIT_P',
            'DRAWMENU','DISP_FREEZE','FREEZE','WAIT','GETKEY','INPUT','CHOOSE',
            'MOUSE','SIZE',
            'RGB','IP','FP','ABS','MAX','MIN','FLOOR','CEILING',
            'ROUND','SQ','SQRT','LOG','LN','EXP','SIN','COS','TAN','IFTE',
            'RANDOM', 'RANDINT', 'MAKELIST',
        ]:
            self._emit0(f"{fn} = _rt.{fn}")
        self._emit0("")

    def _emit_footer(self, out_path):
        self._emit0("")
        self._emit0("# ── Entry point ──────────────────────────────")
        if self._export:
            # Provide default 0 for all required parameters
            args = ", ".join(["0"] * len(self._export_params))
            self._emit0(f"{self._export}({args})")
        self._emit0(f"_rt.save({repr(out_path)})")

    # ── Line transpiler ───────────────────────────────────────────

    def _transpile_line(self, line):
        """Return transpiled Python string, or None if handled internally."""

        # ── Semicolon enforcement ──
        if not line.endswith(';'):
            line_up = line.upper()
            is_exception = False
            
            # Function declarations
            if line_up.startswith('EXPORT ') or line_up.startswith('PROCEDURE '):
                is_exception = True
            # Block starters
            elif line_up == 'BEGIN' or line_up == 'REPEAT' or line_up == 'ELSE':
                is_exception = True
            # Control flow starters
            elif (line_up.startswith('IF ') and line_up.endswith(' THEN')) or \
                 (line_up.startswith('ELSE IF ') and line_up.endswith(' THEN')) or \
                 (line_up.startswith('FOR ') and line_up.endswith(' DO')) or \
                 (line_up.startswith('WHILE ') and line_up.endswith(' DO')):
                is_exception = True
            
            if not is_exception:
                raise SyntaxError(f"Missing semicolon at end of line: '{line}'")

        # ── Function declaration ──
        m = re.match(r'^(EXPORT|PROCEDURE)\s+(\w+)\s*\((.*?)\)\s*;?$', line, re.IGNORECASE)
        if m:
            fname  = m.group(2)
            params = m.group(3).strip()
            self._cur_fn  = fname
            self._indent  = 0
            self._emit(f"def {fname}({params}):")
            self._indent  = 1
            gvars = self._globals.get(fname, set())
            if gvars:
                self._emit(f"global {', '.join(sorted(gvars))}")
            return None

        # ── BEGIN ──
        if re.match(r'^BEGIN;?$', line, re.IGNORECASE):
            return None

        # ── END ──
        if re.match(r'^END;?\s*$', line, re.IGNORECASE):
            # If we're closing a block that has no body, emit 'pass'
            prev = self._out[-1].strip() if self._out else ''
            if prev.endswith(':'):
                self._emit("pass")
            self._indent = max(0, self._indent - 1)
            if self._indent == 0:
                self._cur_fn = None
                self._emit()
            return None

        # ── LOCAL ──
        m = re.match(r'^LOCAL\s+(.+?);?\s*$', line, re.IGNORECASE)
        if m:
            for d in _split_locals(m.group(1)):
                d = d.strip()
                # Array: name[size]
                am = re.match(r'(\w+)\[(\d+)\]\s*(?::=\s*(.+))?', d)
                if am:
                    name, size = am.group(1), int(am.group(2))
                    self._emit(f"{name} = PPLList([0] * {size})  # 1-indexed")
                else:
                    # Scalar with optional init
                    im = re.match(r'(\w+)\s*:=\s*(.+)', d)
                    if im:
                        self._emit(f"{im.group(1)} = {_xform(im.group(2))}")
                    else:
                        self._emit(f"{d} = 0")
            return None

        # ── FOR ──
        m = re.match(r'^FOR\s+(\w+)\s+FROM\s+(.+?)\s+TO\s+(.+?)(?:\s+STEP\s+(.+?))?\s+DO$', line, re.IGNORECASE)
        if m:
            var   = m.group(1)
            start = _xform(m.group(2))
            stop  = _xform(m.group(3))
            step  = _xform(m.group(4)) if m.group(4) else '1'
            if step == '1':
                self._emit(f"for {var} in range(int({start}), int({stop}) + 1):")
            else:
                self._emit(f"for {var} in range(int({start}), int({stop}) + 1, int({step})):")
            self._indent += 1
            return None

        # ── WHILE ──
        m = re.match(r'^WHILE\s+(.+?)\s+DO$', line, re.IGNORECASE)
        if m:
            self._emit(f"while {_xform(m.group(1))}:")
            self._indent += 1
            return None

        # ── REPEAT ──
        if re.match(r'^REPEAT;?$', line, re.IGNORECASE):
            self._emit("while True:")
            self._indent += 1
            return None

        # ── UNTIL ──
        m = re.match(r'^UNTIL\s+(.+?);?\s*$', line, re.IGNORECASE)
        if m:
            # The break check stays inside the while loop, then we close the loop
            self._emit(f"if {_xform(m.group(1))}: break")
            self._indent = max(0, self._indent - 1)
            return None

        # ── ELSE IF ──
        m = re.match(r'^ELSE\s+IF\s+(.+?)\s+THEN$', line, re.IGNORECASE)
        if m:
            self._indent = max(1, self._indent - 1)
            self._emit(f"elif {_xform(m.group(1))}:")
            self._indent += 1
            return None

        # ── IF … THEN ──
        m = re.match(r'^IF\s+(.+?)\s+THEN$', line, re.IGNORECASE)
        if m:
            self._emit(f"if {_xform(m.group(1))}:")
            self._indent += 1
            return None

        # ── ELSE ──
        if re.match(r'^ELSE;?$', line, re.IGNORECASE):
            self._indent = max(1, self._indent - 1)
            self._emit("else:")
            self._indent += 1
            return None

        # ── RETURN ──
        m = re.match(r'^RETURN\s*(.*?);?\s*$', line, re.IGNORECASE)
        if m:
            val = _xform(m.group(1)) if m.group(1).strip() else 'None'
            self._emit(f"return {val}")
            return None

        # ── BREAK / CONTINUE ──
        if re.match(r'^BREAK;?$', line, re.IGNORECASE):
            self._emit("break")
            return None
        if re.match(r'^CONTINUE;?$', line, re.IGNORECASE):
            self._emit("continue")
            return None

        # ── CHOOSE(var, ...) — write result back into variable ──
        m = re.match(r'^CHOOSE\s*\(\s*(\w+)\s*,\s*(.+?)\)\s*;?\s*$', line, re.IGNORECASE)
        if m:
            var  = m.group(1)
            rest = _xform(m.group(2))
            self._emit(f"{var} = CHOOSE({rest})")
            return None

        # ── Assignment  lhs := rhs ──
        m = re.match(r'^(.+?)\s*:=\s*(.+?);?\s*$', line)
        if m:
            lhs = m.group(1).strip()
            rhs = _xform(m.group(2).strip())
            
            # Validation: lhs shouldn't contain ':='
            if ':=' in lhs:
                 raise SyntaxError(f"Multiple assignments or missing semicolon: '{line}'")
            # Validation: rhs shouldn't contain ':=' (unless in a string, but _xform/regex handles that)
            if ':=' in m.group(2):
                 raise SyntaxError(f"Multiple assignments or missing semicolon: '{line}'")

            # List-element assignment:  name(expr) := value  →  name[expr] = value
            # Note: We now keep this simple to avoid masking potential syntax errors 
            # if the user intended list access but used (). 
            # However, standard PPL uses () for arrays, so we support single-level here.
            lm = re.match(r'^(\w+)\s*\((.+)\)$', lhs)
            if lm:
                self._emit(f"{lm.group(1)}[{_xform(lm.group(2))}] = {rhs}")
            else:
                self._emit(f"{_xform(lhs)} = {rhs}")
            return None

        # ── General statement / function call ──
        self._emit(_xform(line.rstrip(';')))
        return None

    # ── Public entry point ────────────────────────────────────────

    def transpile(self, ppl_code, out_path='screen.png'):
        ppl_code = self._preprocess(ppl_code)
        self._first_pass(ppl_code)
        self._emit_header()

        for raw in ppl_code.replace('\r\n', '\n').replace('\r', '\n').splitlines():
            stripped = self._strip_comment(raw).strip()
            if not stripped:
                self._emit()
                continue
            if stripped.startswith('//'):
                self._emit(f"# {stripped[2:].strip()}")
                continue
            
            # Split line into statements by ';' (but not inside strings)
            # and transpile each.
            
            line_up = stripped.upper()
            
            # Helper to check if a single statement is a block starter exception
            def is_stmt_exception(s):
                su = s.upper()
                if su.startswith('EXPORT ') or su.startswith('PROCEDURE '):
                    return True
                if su in ['BEGIN', 'REPEAT', 'ELSE']:
                    return True
                if (su.startswith('IF ') and su.endswith(' THEN')) or \
                   (su.startswith('ELSE IF ') and su.endswith(' THEN')) or \
                   (su.startswith('FOR ') and su.endswith(' DO')) or \
                   (su.startswith('WHILE ') and su.endswith(' DO')):
                    return True
                return False

            # Split statements by semicolon, respecting strings
            statements_to_process = []
            buf, in_str = [], False
            for ch in stripped:
                if ch == '"':
                    in_str = not in_str
                    buf.append(ch)
                elif ch == ';' and not in_str:
                    stmt = ''.join(buf).strip()
                    if stmt:
                        statements_to_process.append(stmt + ';')
                    buf = []
                else:
                    buf.append(ch)
            
            last = ''.join(buf).strip()
            if last:
                # If there's something left without a semicolon, it MUST be a block exception
                if not is_stmt_exception(last):
                     raise SyntaxError(f"Missing semicolon at end of line: '{stripped}'")
                statements_to_process.append(last)
            elif not stripped.endswith(';') and not is_stmt_exception(stripped):
                # Empty line or only whitespace - already handled by 'not stripped' above
                # But if we had " ; " it would end up here with last="" and stripped.endswith(';')=True
                pass

            for stmt in statements_to_process:
                self._transpile_line(stmt)

        self._emit_footer(out_path)
        return '\n'.join(self._out)


def transpile(ppl_code, out_path='screen.png'):
    return Transpiler().transpile(ppl_code, out_path)
