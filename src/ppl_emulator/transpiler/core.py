import re
from contextlib import contextmanager
from .constants import BUILTINS, _PPL_KEYWORDS, _SYSTEM_GLOBALS
from .expressions import _safe_name, _strip_comment, _erase_strings, _split_locals, _xform

class Transpiler:
    def __init__(self):
        self._out: list[str] = []
        self._block_stack: list[tuple[str, int]] = []  # track (block_type, line_number)
        self.indent_level: int = 0
        self._cur_line_raw: int = 0
        self._cur_fn: str | None = None
        self._fn_order: list[tuple[str, str]] = []
        self._export: str | None = None
        self._export_params: list[str] = []
        self._locals: dict[str, set[str]] = {}
        self._globals: dict[str, set[str]] = {}
        self._iferr_stack: list[int] = []
        self._case_stack: list[dict[str, bool | int]] = []
        self._fn_params: dict[str, list[str]] = {}  # raw param names per function

    @contextmanager
    def _indent_block(self):
        """Context manager to push/pop indentation levels."""
        self.indent_level += 1
        yield
        self.indent_level -= 1

    def _pad(self):
        return '    ' * self.indent_level

    def _xf(self, expr):
        """Transform a PPL expression using the current function's symbol table.

        Passes known local+global variable names to _xform so that
        paren-indexed variable access (e.g. my_list(2)) is correctly
        rewritten to _rt.GET_VAR('MY_LIST')(2) rather than left as a
        bare Python identifier that would raise NameError at runtime.
        """
        known = None
        if self._cur_fn:
            raw = (self._locals.get(self._cur_fn, set()) |
                   self._globals.get(self._cur_fn, set()))
            # _first_pass stores names via _safe_name (lowercase); normalise to
            # uppercase so repl_var's name_up comparisons work correctly.
            known = {v.upper() for v in raw}
        return _xform(expr, self._cur_line_raw, known)

    def _emit(self, line=''):
        """Emitter helper that handles indentation automatically."""
        self._out.append(self._pad() + line if line else '')

    def _emit0(self, line):
        self._out.append(line)

    def _validate_lvalue(self, lhs):
        lhs = lhs.strip()
        # Variable or bracket-indexed element (e.g., A or A[1] or A[1,2])
        if re.match(r'^[A-Za-z_]\w*(?:\s*\[.+\])?$', lhs):
            return True
        # Paren-indexed element (e.g., A(1) or A(1,2)) — PPL list/matrix access
        if re.match(r'^[A-Za-z_]\w*\s*\(.+\)$', lhs):
            return True
        raise SyntaxError(f"Line {self._cur_line_raw}: L-value must be a variable or array element: '{lhs}'")

    def _preprocess(self, code):
        lines = code.replace('\r\n', '\n').splitlines()
        result = []
        for i, line in enumerate(lines):
            nc = _strip_comment(line).strip()
            # Handle procedure calls followed by BEGIN
            m = re.match(r'^([A-Za-z_]\w*)\s*\(([^)]*)\)\s*;?$', nc)
            if m and m.group(1).upper() not in _PPL_KEYWORDS:
                is_proc = False
                end_idx = i + 10
                if end_idx > len(lines): end_idx = len(lines)
                for j in range(i + 1, end_idx):  # type: ignore
                    ns = _strip_comment(lines[j]).strip()
                    if not ns: continue
                    if re.match(r'^BEGIN;?$', ns, re.IGNORECASE): is_proc = True
                    break  # stop at first non-blank line (BEGIN or not)
                if is_proc: line = line.replace(nc, 'PROCEDURE ' + nc.rstrip(';'))
            # Handle LOCAL function definitions: LOCAL func(params) [+ BEGIN] → PROCEDURE
            elif re.match(r'^LOCAL\s+[A-Za-z_]\w*\s*\(', nc, re.IGNORECASE):
                m_lfn = re.match(r'^LOCAL\s+([A-Za-z_]\w*)\s*\(([^)]*)\)\s*;?$', nc, re.IGNORECASE)
                if m_lfn:
                    is_lfn = False
                    end_idx2 = min(i + 10, len(lines))
                    for j in range(i + 1, end_idx2):
                        ns = _strip_comment(lines[j]).strip()
                        if not ns: continue
                        if re.match(r'^BEGIN;?$', ns, re.IGNORECASE): is_lfn = True
                        break
                    if is_lfn:
                        line = line.replace(nc, f'PROCEDURE {m_lfn.group(1)}({m_lfn.group(2)})')
            result.append(line)
        
        expanded: list[str] = []
        for line in result:
            nc = _strip_comment(line).strip(); indent = str(line)[: len(line) - len(line.lstrip())]  # type: ignore
            # Expansion for one-liners
            m = re.match(r'^(IF\s+.+?(?:\s+THEN|(?<![A-Za-z_])\s*THEN))\s+(.+?)\s*(?:ELSE\s+(.+?)\s*)?END;?\s*$', nc, re.IGNORECASE)
            if m:
                expanded.append(indent + m.group(1))
                for s in m.group(2).split(';'):
                    if s.strip(): expanded.append(indent + '  ' + s.strip() + ';')
                if m.group(3):
                    expanded.append(indent + 'ELSE')
                    for s in m.group(3).split(';'):
                        if s.strip(): expanded.append(indent + '  ' + s.strip() + ';')
                expanded.append(indent + 'END;'); continue
            m = re.match(r'^(WHILE\s+.+?\s+DO)\s+(.+?)\s*END;?\s*$', nc, re.IGNORECASE)
            if m:
                expanded.append(indent + m.group(1))
                for s in m.group(2).split(';'):
                    if s.strip(): expanded.append(indent + '  ' + s.strip() + ';')
                expanded.append(indent + 'END;'); continue
            m = re.match(r'^(FOR\s+.+?\s+DO)\s+(.+?)\s*END;?\s*$', nc, re.IGNORECASE)
            if m:
                expanded.append(indent + m.group(1))
                for s in m.group(2).split(';'):
                    if s.strip(): expanded.append(indent + '  ' + s.strip() + ';')
                expanded.append(indent + 'END;'); continue
            m = re.match(r'^REPEAT\s*(.*?)\s*UNTIL\s+(.+?);?\s*$', nc, re.IGNORECASE)
            if m:
                expanded.append(indent + 'REPEAT')
                for s in m.group(1).split(';'):
                    if s.strip(): expanded.append(indent + '  ' + s.strip() + ';')
                expanded.append(indent + 'UNTIL ' + m.group(2) + ';'); continue
            expanded.append(line)  # type: ignore
        return '\n'.join(expanded)

    def _first_pass(self, code):
        cur: str | None = None
        loc: set[str] = set()
        asgn: set[str] = set()
        for raw in code.splitlines():
            line = _strip_comment(raw).strip()
            if not line: continue
            m = re.match(r'(EXPORT|PROCEDURE)\s+(\w+)\s*\((.*?)\)', line, re.IGNORECASE)
            if m:
                if cur:
                    self._locals[cur] = loc  # type: ignore
                    self._globals[cur] = asgn - loc  # type: ignore
                cur = m.group(2)
                loc = set()
                asgn = set()
                params = [_safe_name(p.strip()) for p in m.group(3).split(',') if p.strip()]
                loc.update(params); self._fn_order.append((cur, ", ".join(params)))
                if m.group(1).upper() == 'EXPORT': self._export, self._export_params = cur, params
                continue
            m = re.match(r'LOCAL\s+(.+?);?\s*$', line, re.IGNORECASE)
            if m and cur:
                for d in _split_locals(m.group(1)):
                    match = re.match(r'(\w+)', d)
                    if match: loc.add(_safe_name(match.group(1)))
                continue
            for ma in re.finditer(r'(\w+)(?:\[.+?\])?\s*:=', line):
                if cur: asgn.add(_safe_name(ma.group(1)))
        if cur:
            self._locals[cur] = loc  # type: ignore
            self._globals[cur] = asgn - loc  # type: ignore

    def _emit_header(self):
        self._emit0("# Auto-generated by HP PPL Emulator"); self._emit0("import sys, math, sympy")
        self._emit0("from src.ppl_emulator.runtime.engine import HPPrimeRuntime")
        self._emit0("from src.ppl_emulator.runtime.types import PPLList, PPLString, PPLMatrix")
        self._emit0("_rt = HPPrimeRuntime()")
        for fn in BUILTINS:
            self._emit0(f"{fn} = _rt.{fn}")
            safe = _safe_name(fn)
            if safe != fn: self._emit0(f"{safe} = _rt.{fn}")
        self._emit0("CAS = _rt.CAS")
        self._emit0("Finance = _rt.Finance")
        self._emit0("pi = math.pi")  # HP Prime π constant
        self._emit0("e = math.e")  # HP Prime e constant
        # CAS symbolic variables — x,y,z,t,a,b,c as sympy symbols for CAS calls
        self._emit0("x, y, z, t, a, b, c = sympy.symbols('x y z t a b c')")
        self._emit0("n = k = s = r = m = 0")  # numeric loop/scratch vars
        self._emit0("Ans = 0")  # HP Prime last-result register
        # PPL 2-D matrix slice helper: emitted into every transpiled program
        self._emit0("def _ppl_slice_2d(mat, r0, r1, c0, c1):")
        self._emit0("    return PPLList([row[c0:c1] for row in mat[r0:r1]])")
        self._emit0("")

    def _emit_footer(self, out_path):
        if self._export:
            args = ", ".join(["0"] * len(self._export_params))
            self._emit0(f"{self._export}({args})")
        self._emit0(f"_rt.save({repr(out_path)})")

    def _transpile_line(self, line):
        line = line.strip(); 
        if not line: return
        # Skip forward declarations: bare user-function calls at module level
        if self.indent_level == 0 and self._cur_fn is None:
            m_fwd = re.match(r'^([A-Za-z_]\w*)\s*\(([^()]*)\)\s*;?$', line)
            if m_fwd:
                fn_names = {name for name, _ in self._fn_order}
                if m_fwd.group(1) in fn_names or m_fwd.group(1).upper() in {n.upper() for n, _ in self._fn_order}:
                    return  # forward declaration — skip
        m = re.match(r'^(EXPORT|PROCEDURE)\s+(\w+)\s*\((.*?)\);?$', line, re.IGNORECASE)
        if m:
            fn_name = m.group(2)
            raw_params = [p.strip() for p in m.group(3).split(',') if p.strip()]
            self._cur_fn, self.indent_level = fn_name, 0
            params = [_safe_name(p) for p in raw_params]
            self._fn_params[fn_name.upper()] = raw_params  # store for BEGIN injection
            self._emit(f"def {fn_name}({', '.join(params)}):")
            self.indent_level = 1; self._block_stack = [('PROCEDURE', self._cur_line_raw)]; gvars = self._globals.get(fn_name, set())
            if gvars: self._emit(f"global {', '.join(sorted(gvars))}")
            # Register arity so CHECK_ARITY can validate call sites at runtime
            self._emit(f"_rt.REGISTER_FN('{fn_name}', {len(raw_params)})")
            return
        # EXPORT variable := value  (exported global, not a function)
        m_expvar = re.match(r'^EXPORT\s+(.+)$', line, re.IGNORECASE)
        if m_expvar: line = m_expvar.group(1).strip()

        if re.match(r'^BEGIN;?$', line, re.IGNORECASE):
            self._emit("_rt.PUSH_BLOCK()")
            # If this BEGIN opens a function body, inject parameters into the scope
            if self._cur_fn and len(self._block_stack) == 1 and self._block_stack[0][0] == 'PROCEDURE':
                fn_key = self._cur_fn.upper()
                for p in self._fn_params.get(fn_key, []):
                    safe = _safe_name(p)
                    self._emit(f"_rt.SET_VAR('{p.upper()}', {safe}, is_local=True)")
            self._block_stack.append(('BEGIN', self._cur_line_raw))
            return
        if re.match(r'^END;?$', line, re.IGNORECASE):
            if any(True for _ in [next((l for l in reversed(self._out) if l.strip()), '')]) and next((l for l in reversed(self._out) if l.strip()), '').strip().endswith(':'): self._emit("pass")
            self._emit("_rt.POP_BLOCK()")
            _bts_popped = self._block_stack.pop() if self._block_stack else ('UNKNOWN', 0)
            if _bts_popped[0] != 'CASE':
                self.indent_level = max(0, self.indent_level - 1)
            if self._iferr_stack and self._iferr_stack[-1] == self.indent_level: self._iferr_stack.pop()
            
            if _bts_popped[0] == 'DEFAULT' and self._block_stack and self._block_stack[-1][0] == 'CASE':
                # PPL CASE's END; closes BOTH the DEFAULT branch AND the CASE itself
                self._block_stack.pop()
                if self._case_stack: self._case_stack.pop()
            elif _bts_popped[0] == 'CASE':
                if self._case_stack: self._case_stack.pop()

            if self.indent_level == 0:
                if self._block_stack and self._block_stack[-1][0] == 'PROCEDURE':
                    self._block_stack.pop()
                elif self._block_stack:
                    btype, bline = self._block_stack[-1]
                    raise SyntaxError(f"Line {self._cur_line_raw}: Unexpected END; unclosed {btype} block at line {bline}")
                self._cur_fn = None; self._emit(); self._block_stack = []
            return
        
        # CASE statement
        if re.match(r'^CASE;?$', line, re.IGNORECASE):
            self._case_stack.append({'first': True, 'has_default': False, 'indent': self.indent_level})
            self._block_stack.append(('CASE', self._cur_line_raw))
            return
        
        # DEFAULT (inside CASE)
        m = re.match(r'^DEFAULT\b\s*(.*)$', line, re.IGNORECASE)
        if m and self._case_stack:
            verb = "if True:" if self._case_stack[-1]['first'] else "else:"
            self._emit(verb)
            self.indent_level += 1
            self._emit("_rt.PUSH_BLOCK()")
            self._block_stack.append(('DEFAULT', self._cur_line_raw))
            self._case_stack[-1]['has_default'] = True
            self._case_stack[-1]['first'] = False
            if m.group(1): self._transpile_line(m.group(1))
            return

        m = re.match(r'^LOCAL\b\s+(.+?);?$', line, re.IGNORECASE)
        if m:
            for d in _split_locals(m.group(1)):
                name_match = re.match(r'^(\w+)', d)
                if name_match:
                    name = name_match.group(1)
                    if name.upper() in _SYSTEM_GLOBALS:
                        raise SyntaxError(f"Line {self._cur_line_raw}: Cannot shadow system global '{name}' in LOCAL declaration")
                am = re.match(r'(\w+)\[(\d+)\]\s*(?::=\s*(.+))?', d)
                if am: 
                    self._emit(f"_rt.SET_VAR('{am.group(1).upper()}', PPLList([0] * {am.group(2)}), is_local=True)")
                else:
                    im = re.match(r'(\w+)\s*:=\s*(.+)', d); 
                    if im: self._emit(f"_rt.SET_VAR('{im.group(1).upper()}', {self._xf(im.group(2))}, is_local=True)")
                    else: self._emit(f"_rt.SET_VAR('{d.strip().upper()}', 0, is_local=True)")
            return
        # FOR ... DOWNTO (descending loop)
        m = re.match(r'^FOR\s+(\w+)\s+FROM\s+(.+?)\s+DOWNTO\s+(.+?)(?:\s+STEP\s+(.+?))?\s+DO\s*(.*)$', line, re.IGNORECASE)
        if m:
            start, stop, step = self._xf(m.group(2)), self._xf(m.group(3)), (self._xf(m.group(4)) if m.group(4) else '1')
            self._emit(f"for {_safe_name(m.group(1))} in range(int({start}), int({stop}) + (1 if -int({step}) > 0 else -1), -int({step})):")
            self.indent_level += 1
            self._emit("_rt.PUSH_BLOCK()")
            self._block_stack.append(('FOR', self._cur_line_raw))
            # Also sync the loop counter into the scope stack? 
            # PPL loop counters are usually variables.
            self._emit(f"_rt.SET_VAR('{m.group(1).upper()}', {_safe_name(m.group(1))})")
            if m.group(5): self._transpile_line(m.group(5))
            return
        # Strict FOR loop: check for missing DO
        if re.match(r'^FOR\b', line, re.IGNORECASE):
            m = re.match(r'^FOR\s+(\w+)\s+FROM\s+(.+?)\s+TO\s+(.+?)(?:\s+STEP\s+(.+?))?\s+DO\b\s*(.*)$', line, re.IGNORECASE)
            if not m:
                raise SyntaxError(f"Line {self._cur_line_raw}: Expected 'DO' in FOR loop")
            start, stop, step = self._xf(m.group(2)), self._xf(m.group(3)), (self._xf(m.group(4)) if m.group(4) else '1')
            self._emit(f"for {_safe_name(m.group(1))} in range(int({start}), int({stop}) + (1 if int({step}) > 0 else -1), int({step})):")
            self.indent_level += 1
            self._emit("_rt.PUSH_BLOCK()")
            self._block_stack.append(('FOR', self._cur_line_raw))
            self._emit(f"_rt.SET_VAR('{m.group(1).upper()}', {_safe_name(m.group(1))})")
            if m.group(5): self._transpile_line(m.group(5))
            return
        
        m = re.match(r'^WHILE\s+(.+?)\s+DO\b\s*(.*)$', line, re.IGNORECASE)
        if m:
            self._emit(f"while {self._xf(m.group(1))}:")
            self.indent_level += 1
            self._emit("_rt.PUSH_BLOCK()")
            self._block_stack.append(('WHILE', self._cur_line_raw))
            if m.group(2): self._transpile_line(m.group(2))
            return
        m_rep = re.match(r'^REPEAT\s*(.*?)\s*UNTIL\s+(.+?);?\s*$', line, re.IGNORECASE)
        if m_rep:
            self._emit('while True:')
            self.indent_level += 1
            self._emit("_rt.PUSH_BLOCK()")
            self._block_stack.append(('REPEAT', self._cur_line_raw))
            body = m_rep.group(1).strip()
            if body:
                for s in body.split(';'):
                    if s.strip(): self._transpile_line(s.strip())
            self._emit(f'if {self._xf(m_rep.group(2))}: break')
            self._emit("_rt.POP_BLOCK()")
            self.indent_level -= 1
            if self._block_stack: self._block_stack.pop()
            return
        if re.match(r'^REPEAT;?$', line, re.IGNORECASE):
            self._emit("while True:"); self.indent_level += 1;
            self._emit("_rt.PUSH_BLOCK()")
            self._block_stack.append(('REPEAT', self._cur_line_raw));
            return
        m = re.match(r'^UNTIL\s+(.+?);?$', line, re.IGNORECASE)
        if m:
            if any(True for _ in [next((l for l in reversed(self._out) if l.strip()), '')]) and next((l for l in reversed(self._out) if l.strip()), '').strip().endswith(':'): self._emit("pass")
            self._emit(f"if {self._xf(m.group(1))}: break")
            self._emit("_rt.POP_BLOCK()")
            self.indent_level = max(0, self.indent_level - 1)
            if self._block_stack: self._block_stack.pop()
            return
        
        m = re.match(r'^IF\s+(.+?)(?:\s+THEN\b|(?<![A-Za-z_])\s*THEN\b)\s*(.*)$', line, re.IGNORECASE)
        if m:
            # Only treat as a CASE branch if this IF is at the CASE's own indent level
            if self._case_stack and self.indent_level == self._case_stack[-1]['indent']:
                verb = "if" if self._case_stack[-1]['first'] else "elif"
                self._case_stack[-1]['first'] = False
                self._emit(f"{verb} {self._xf(m.group(1))}:")
            else:
                self._emit(f"if {self._xf(m.group(1))}:")
            self.indent_level += 1
            self._emit("_rt.PUSH_BLOCK()")
            self._block_stack.append(('IF', self._cur_line_raw))
            if m.group(2): self._transpile_line(m.group(2))
            return
        m = re.match(r'^IFERR\b\s*(.*)$', line, re.IGNORECASE)
        if m:
            self._emit("try:")
            self._iferr_stack.append(self.indent_level)
            self.indent_level += 1
            self._emit("_rt.PUSH_BLOCK()")
            self._block_stack.append(('IFERR', self._cur_line_raw))
            if m.group(1): self._transpile_line(m.group(1))
            return
        m = re.match(r'^THEN\b\s*(.*)$', line, re.IGNORECASE)
        if m:
            if self._iferr_stack and self._iferr_stack[-1] == self.indent_level - 1:
                self._emit("_rt.POP_BLOCK()")
                self.indent_level -= 1
                if self._block_stack: self._block_stack.pop()
                self._emit("except:")
                self.indent_level += 1
                self._emit("_rt.PUSH_BLOCK()")
                self._block_stack.append(('IF', self._cur_line_raw)) # treating except block as an IF block for END tracking
                if m.group(1): self._transpile_line(m.group(1))
                return
        m = re.match(r'^ELSE\s+IF\s+(.+?)\s+THEN\b\s*(.*)$', line, re.IGNORECASE)
        if m:
            if any(True for _ in [next((l for l in reversed(self._out) if l.strip()), '')]) and next((l for l in reversed(self._out) if l.strip()), '').strip().endswith(':'): self._emit("pass")
            self._emit("_rt.POP_BLOCK()")
            prev = self.indent_level
            self.indent_level = max(1, self.indent_level - 1)
            if self.indent_level < prev and self._block_stack: self._block_stack.pop()
            self._emit(f"elif {self._xf(m.group(1))}:")
            self.indent_level += 1
            self._emit("_rt.PUSH_BLOCK()")
            self._block_stack.append(('IF', self._cur_line_raw))
            if m.group(2): self._transpile_line(m.group(2))
            return
        m = re.match(r'^ELSE\b\s*(.*)$', line, re.IGNORECASE)
        if m:
            if any(True for _ in [next((l for l in reversed(self._out) if l.strip()), '')]) and next((l for l in reversed(self._out) if l.strip()), '').strip().endswith(':'): self._emit("pass")
            self._emit("_rt.POP_BLOCK()")
            prev = self.indent_level
            self.indent_level = max(1, self.indent_level - 1)
            if self.indent_level < prev and self._block_stack: self._block_stack.pop()
            self._emit("else:")
            self.indent_level += 1
            self._emit("_rt.PUSH_BLOCK()")
            self._block_stack.append(('IF', self._cur_line_raw))
            if m.group(1): self._transpile_line(m.group(1))
            return
        m = re.match(r'^RETURN\s*(.*?);?$', line, re.IGNORECASE)
        if m: self._emit(f"return {self._xf(m.group(1)) if m.group(1) else 'None'}"); return
        if re.match(r'^BREAK;?$', line, re.IGNORECASE):
            has_loop = any(b[0] in ('FOR', 'WHILE', 'REPEAT') for b in self._block_stack)
            self._emit("break" if has_loop else "pass"); return
        if re.match(r'^CONTINUE;?$', line, re.IGNORECASE):
            has_loop = any(b[0] in ('FOR', 'WHILE', 'REPEAT') for b in self._block_stack)
            self._emit("continue" if has_loop else "pass"); return
        # Handle ▶ (STO) operator: expr▶var → var = expr
        if '▶' in line:
            m_sto = re.match(r'^(.+?)▶\s*(\w+)\s*;?\s*$', line.strip())
            if m_sto and m_sto.group(2).upper() not in _PPL_KEYWORDS:
                self._validate_lvalue(m_sto.group(2))
                self._emit(f"_rt.SET_VAR('{m_sto.group(2).upper()}', {self._xf(m_sto.group(1).strip())})")
                return
        # Import _slice_bound at the top level or use it here
        from .expressions import _slice_bound
        m = re.match(r'^(.+?)\s*:=\s*(.+?);?$', line)
        if m:
            lhs, rhs = m.group(1).strip(), self._xf(m.group(2).strip())
            self._validate_lvalue(lhs)
            lm_p = re.match(r'^(\w+)\s*\((.+)\)$', lhs)   # paren-indexed: name(i) or name(i,j)
            lm_b = re.match(r'^(\w+)\s*\[(.+)\]$', lhs)   # bracket-indexed: name[i]
            if lm_p:
                var = lm_p.group(1).upper()
                # Split comma-separated indices and chain as [i][j].
                # Discrepancy 2 fix: PPLList/PPLMatrix.__setitem__ handles 1-based conversion
                # internally, so we pass the raw PPL index without subtracting 1.
                indices = [idx.strip() for idx in lm_p.group(2).split(',')]
                chain = ''.join(f'[{self._xf(idx)}]' for idx in indices)
                self._emit(f"_rt.GET_VAR('{var}', {self._cur_line_raw}).value{chain} = {rhs}")
            elif lm_b:
                var = lm_b.group(1).upper()
                raw_idx = lm_b.group(2)
                # Discrepancy 2 fix: PPLList/PPLMatrix.__setitem__ handles 1-based internally.
                if ',' in raw_idx:
                    indices = [idx.strip() for idx in raw_idx.split(',')]
                    chain = ''.join(f'[{self._xf(idx)}]' for idx in indices)
                    self._emit(f"_rt.GET_VAR('{var}', {self._cur_line_raw}).value{chain} = {rhs}")
                else:
                    self._emit(f"_rt.GET_VAR('{var}', {self._cur_line_raw}).value[{self._xf(raw_idx)}] = {rhs}")
            else:
                self._emit(f"_rt.GET_VAR('{lhs.upper()}', {self._cur_line_raw}).value = {rhs}")
            return
        m = re.match(r'^CHOOSE\s*\(\s*(\w+)\s*,\s*(.+?)\);?$', line, re.IGNORECASE)
        if m: self._emit(f"_rt.SET_VAR('{m.group(1).upper()}', _rt.CHOOSE({self._xf(m.group(2))}))"); return
        
        # INPUT(var, ...)
        m_input = re.match(r'^INPUT\s*\(\s*(\w+)\s*(?:,\s*(.+?))?\s*\);?$', line, re.IGNORECASE)
        if m_input:
            var = m_input.group(1).upper()
            args = f", {self._xf(m_input.group(2))}" if m_input.group(2) else ""
            self._emit(f"_rt.INPUT('{var}'{args})")
            return

        # DIMGROB_P(Gk, w, h [, color])
        m_dimgrob = re.match(r'^DIMGROB_P\s*\(\s*(\w+)\s*,\s*(.*?)\);?$', line, re.IGNORECASE)
        if m_dimgrob:
            target = m_dimgrob.group(1).upper()
            args = m_dimgrob.group(2)
            self._emit(f"_rt.SET_VAR('{target}', _rt.DIMGROB_P({self._xf(args)}))")
            return
        
        self._emit(self._xf(line.rstrip(';')))

    def transpile(self, ppl_code, out_path='screen.png'):
        code = self._preprocess(ppl_code); self._first_pass(code); self._emit_header()
        buf = []
        for line_num, raw in enumerate(code.splitlines(), 1):
            self._cur_line_raw = line_num
            cl = _strip_comment(raw).strip() 
            if not cl:
                if not buf: self._emit()
                continue
            buf.append(cl); cb = " ".join(buf); sf = _erase_strings(cb); pb, bb = sf.count('(') - sf.count(')') , sf.count('{') - sf.count('}')
            trailing_op = bool(re.search(r'(?:[-+*/^]|\b(?:AND|OR|XOR|MOD|DIV))\s*$', sf, re.IGNORECASE))
            if pb > 0 or bb > 0 or cb.endswith(',') or cb.endswith(':=') or trailing_op: continue
            
            stmts, sbuf, in_s, pdepth, i = [], [], False, 0, 0
            while i < len(cb):
                ch = cb[i]
                if ch == '"':
                    if not in_s: in_s = True; sbuf.append('"')
                    else:
                        if i + 1 < len(cb) and cb[i+1] == '"': sbuf.append('""'); i += 1
                        else: in_s = False; sbuf.append('"')
                elif in_s and ch == '\\' and i + 1 < len(cb) and cb[i+1] == '"':
                    sbuf.append('\\"'); i += 1
                elif not in_s and ch in '([{': pdepth += 1; sbuf.append(ch)
                elif not in_s and ch in ')]}': pdepth = max(0, pdepth - 1); sbuf.append(ch)
                elif ch == ';' and not in_s and pdepth == 0:
                    s = ''.join(sbuf).strip()
                    if s: stmts.append(s)
                    sbuf = []
                else: sbuf.append(ch)
                i += 1
            last = ''.join(sbuf).strip()
            if last: stmts.append(last)
            for s in stmts: self._transpile_line(s)
            buf = []
        
        if self._block_stack:
            btype, bline = self._block_stack[-1]
            raise SyntaxError(f"End of file: {btype} block at line {bline} was never closed")

        self._emit0("")
        self._emit_footer(out_path)
        return '\n'.join(self._out)

def transpile(ppl_code, out_path='screen.png'): return Transpiler().transpile(ppl_code, out_path)
