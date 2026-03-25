import re
from .constants import BUILTINS, _PPL_KEYWORDS
from .expressions import _safe_name, _strip_comment, _erase_strings, _split_locals, _xform

class Transpiler:
    def __init__(self):
        self._out: list[str] = []
        self._indent: int = 0
        self._cur_fn: str | None = None
        self._fn_order: list[tuple[str, str]] = []
        self._export: str | None = None
        self._export_params: list[str] = []
        self._locals: dict[str, set[str]] = {}
        self._globals: dict[str, set[str]] = {}
        self._iferr_stack: list[int] = []
        self._case_stack: list[dict[str, bool | int]] = []
        self._block_type_stack: list[str] = []  # track block types per indent level

    def _pad(self): return '    ' * self._indent
    def _emit(self, line=''): self._out.append(self._pad() + line if line else '')
    def _emit0(self, line): self._out.append(line)

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
            result.append(line)
        
        expanded: list[str] = []
        for line in result:
            nc = _strip_comment(line).strip(); indent = str(line)[: len(line) - len(line.lstrip())]  # type: ignore
            # Expansion for one-liners
            m = re.match(r'^(IF\s+.+?\s+THEN)\s+(.+?)\s*(?:ELSE\s+(.+?)\s*)?END;?\s*$', nc, re.IGNORECASE)
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
        self._emit0("# Auto-generated by HP PPL Emulator"); self._emit0("import sys, math")
        self._emit0("from src.ppl_emulator.runtime.engine import HPPrimeRuntime")
        self._emit0("from src.ppl_emulator.runtime.types import PPLList")
        self._emit0("_rt = HPPrimeRuntime()")
        for fn in BUILTINS:
            self._emit0(f"{fn} = _rt.{fn}")
            safe = _safe_name(fn)
            if safe != fn: self._emit0(f"{safe} = _rt.{fn}")
        self._emit0("CAS = _rt.CAS")
        self._emit0("Finance = _rt.Finance")
        self._emit0("pi = math.pi")  # HP Prime π constant
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
        if self._indent == 0 and self._cur_fn is None:
            m_fwd = re.match(r'^([A-Za-z_]\w*)\s*\(([^()]*)\)\s*;?$', line)
            if m_fwd:
                fn_names = {name for name, _ in self._fn_order}
                if m_fwd.group(1) in fn_names or m_fwd.group(1).upper() in {n.upper() for n, _ in self._fn_order}:
                    return  # forward declaration — skip
        m = re.match(r'^(EXPORT|PROCEDURE)\s+(\w+)\s*\((.*?)\);?$', line, re.IGNORECASE)
        if m:
            self._cur_fn, self._indent = m.group(2), 0
            params = [_safe_name(p.strip()) for p in m.group(3).split(',') if p.strip()]
            self._emit(f"def {m.group(2)}({', '.join(params)}):")
            self._indent = 1; self._block_type_stack = ['fn']; gvars = self._globals.get(m.group(2), set())
            if gvars: self._emit(f"global {', '.join(sorted(gvars))}")
            return
        # EXPORT variable := value  (exported global, not a function)
        m_expvar = re.match(r'^EXPORT\s+(.+)$', line, re.IGNORECASE)
        if m_expvar: line = m_expvar.group(1).strip()

        if re.match(r'^BEGIN;?$', line, re.IGNORECASE): return
        if re.match(r'^END;?$', line, re.IGNORECASE):
            if any(True for _ in [next((l for l in reversed(self._out) if l.strip()), '')]) and next((l for l in reversed(self._out) if l.strip()), '').strip().endswith(':'): self._emit("pass")
            self._indent = max(0, self._indent - 1)
            _bts_popped = self._block_type_stack.pop() if self._block_type_stack else 'if'
            if self._iferr_stack and self._iferr_stack[-1] == self._indent: self._iferr_stack.pop()
            # Pop CASE when indent drops below the level where CASE was opened.
            # Since CASE doesn't own an indent level, also restore the indent so
            # the enclosing block's END is not consumed.
            if self._case_stack and self._indent < self._case_stack[-1]['indent']:
                self._case_stack.pop()
                self._indent += 1  # restore: CASE didn't allocate this indent level
                self._block_type_stack.append(_bts_popped)
            if self._indent == 0: self._cur_fn = None; self._emit(); self._block_type_stack = []
            return
        
        # CASE statement
        if re.match(r'^CASE;?$', line, re.IGNORECASE):
            self._case_stack.append({'first': True, 'has_default': False, 'indent': self._indent})
            return
        
        # DEFAULT (inside CASE)
        m = re.match(r'^DEFAULT\b\s*(.*)$', line, re.IGNORECASE)
        if m and self._case_stack:
            self._emit("else:")
            self._indent += 1
            self._block_type_stack.append('if')
            self._case_stack[-1]['has_default'] = True
            if m.group(1): self._transpile_line(m.group(1))
            return

        m = re.match(r'^LOCAL\b\s+(.+?);?$', line, re.IGNORECASE)
        if m:
            for d in _split_locals(m.group(1)):
                am = re.match(r'(\w+)\[(\d+)\]\s*(?::=\s*(.+))?', d)
                if am: self._emit(f"{_safe_name(am.group(1))} = PPLList([0] * {am.group(2)})")
                else:
                    im = re.match(r'(\w+)\s*:=\s*(.+)', d); 
                    if im: self._emit(f"{_safe_name(im.group(1))} = {_xform(im.group(2))}")
                    else: self._emit(f"{_safe_name(d)} = 0")
            return
        # FOR ... DOWNTO (descending loop)
        m = re.match(r'^FOR\s+(\w+)\s+FROM\s+(.+?)\s+DOWNTO\s+(.+?)(?:\s+STEP\s+(.+?))?\s+DO\s*(.*)$', line, re.IGNORECASE)
        if m:
            start, stop, step = _xform(m.group(2)), _xform(m.group(3)), (_xform(m.group(4)) if m.group(4) else '1')
            self._emit(f"for {_safe_name(m.group(1))} in range(int({start}), int({stop}) - 1, -int({step})):")
            self._indent += 1
            self._block_type_stack.append('loop')
            if m.group(5): self._transpile_line(m.group(5))
            return
        m = re.match(r'^FOR\s+(\w+)\s+FROM\s+(.+?)\s+TO\s+(.+?)(?:\s+STEP\s+(.+?))?\s+DO\b\s*(.*)$', line, re.IGNORECASE)
        if m:
            start, stop, step = _xform(m.group(2)), _xform(m.group(3)), (_xform(m.group(4)) if m.group(4) else '1')
            self._emit(f"for {_safe_name(m.group(1))} in range(int({start}), int({stop}) + 1, int({step})):")
            self._indent += 1
            self._block_type_stack.append('loop')
            if m.group(5): self._transpile_line(m.group(5))
            return
        m = re.match(r'^WHILE\s+(.+?)\s+DO\b\s*(.*)$', line, re.IGNORECASE)
        if m:
            self._emit(f"while {_xform(m.group(1))}:")
            self._indent += 1
            self._block_type_stack.append('loop')
            if m.group(2): self._transpile_line(m.group(2))
            return
        if re.match(r'^REPEAT;?$', line, re.IGNORECASE): self._emit("while True:"); self._indent += 1; self._block_type_stack.append('loop'); return
        m = re.match(r'^UNTIL\s+(.+?);?$', line, re.IGNORECASE)
        if m:
            if any(True for _ in [next((l for l in reversed(self._out) if l.strip()), '')]) and next((l for l in reversed(self._out) if l.strip()), '').strip().endswith(':'): self._emit("pass")
            self._emit(f"if {_xform(m.group(1))}: break")
            self._indent = max(0, self._indent - 1)
            if self._block_type_stack: self._block_type_stack.pop()
            return
        
        m = re.match(r'^IF\s+(.+?)\s+THEN\b\s*(.*)$', line, re.IGNORECASE)
        if m:
            # Only treat as a CASE branch if this IF is at the CASE's own indent level
            if self._case_stack and self._indent == self._case_stack[-1]['indent']:
                verb = "if" if self._case_stack[-1]['first'] else "elif"
                self._case_stack[-1]['first'] = False
                self._emit(f"{verb} {_xform(m.group(1))}:")
            else:
                self._emit(f"if {_xform(m.group(1))}:")
            self._indent += 1
            self._block_type_stack.append('if')
            if m.group(2): self._transpile_line(m.group(2))
            return
        m = re.match(r'^IFERR\b\s*(.*)$', line, re.IGNORECASE)
        if m:
            self._emit("try:")
            self._iferr_stack.append(self._indent)
            self._indent += 1
            self._block_type_stack.append('try')
            if m.group(1): self._transpile_line(m.group(1))
            return
        m = re.match(r'^THEN\b\s*(.*)$', line, re.IGNORECASE)
        if m:
            if self._iferr_stack and self._iferr_stack[-1] == self._indent - 1:
                self._indent -= 1
                if self._block_type_stack: self._block_type_stack.pop()
                self._emit("except:")
                self._indent += 1
                self._block_type_stack.append('if')
                if m.group(1): self._transpile_line(m.group(1))
                return
        m = re.match(r'^ELSE\s+IF\s+(.+?)\s+THEN\b\s*(.*)$', line, re.IGNORECASE)
        if m:
            if any(True for _ in [next((l for l in reversed(self._out) if l.strip()), '')]) and next((l for l in reversed(self._out) if l.strip()), '').strip().endswith(':'): self._emit("pass")
            prev = self._indent
            self._indent = max(1, self._indent - 1)
            if self._indent < prev and self._block_type_stack: self._block_type_stack.pop()
            self._emit(f"elif {_xform(m.group(1))}:")
            self._indent += 1
            self._block_type_stack.append('if')
            if m.group(2): self._transpile_line(m.group(2))
            return
        m = re.match(r'^ELSE\b\s*(.*)$', line, re.IGNORECASE)
        if m:
            if any(True for _ in [next((l for l in reversed(self._out) if l.strip()), '')]) and next((l for l in reversed(self._out) if l.strip()), '').strip().endswith(':'): self._emit("pass")
            prev = self._indent
            self._indent = max(1, self._indent - 1)
            if self._indent < prev and self._block_type_stack: self._block_type_stack.pop()
            self._emit("else:")
            self._indent += 1
            self._block_type_stack.append('if')
            if m.group(1): self._transpile_line(m.group(1))
            return
        m = re.match(r'^RETURN\s*(.*?);?$', line, re.IGNORECASE)
        if m: self._emit(f"return {_xform(m.group(1)) if m.group(1) else 'None'}"); return
        if re.match(r'^BREAK;?$', line, re.IGNORECASE): self._emit("break" if 'loop' in self._block_type_stack else "pass"); return
        if re.match(r'^CONTINUE;?$', line, re.IGNORECASE): self._emit("continue" if 'loop' in self._block_type_stack else "pass"); return
        # Handle ▶ (STO) operator: expr▶var → var = expr
        if '▶' in line:
            m_sto = re.match(r'^(.+?)▶(\w+)\s*;?\s*$', line.strip())
            if m_sto and m_sto.group(2).upper() not in _PPL_KEYWORDS:
                self._emit(f"{_safe_name(m_sto.group(2))} = {_xform(m_sto.group(1).strip())}")
                return
        m = re.match(r'^(.+?)\s*:=\s*(.+?);?$', line)
        if m:
            lhs, rhs = m.group(1).strip(), _xform(m.group(2).strip())
            lm = re.match(r'^(\w+)\s*[\(\[](.+)[\)\]]$', lhs)
            if lm: self._emit(f"{_safe_name(lm.group(1))}[{_xform(lm.group(2))}] = {rhs}")
            else: self._emit(f"{_safe_name(lhs)} = {rhs}")
            return
        m = re.match(r'^CHOOSE\s*\(\s*(\w+)\s*,\s*(.+?)\);?$', line, re.IGNORECASE)
        if m: self._emit(f"{_safe_name(m.group(1))} = CHOOSE({_xform(m.group(2))})"); return
        self._emit(_xform(line.rstrip(';')))

    def transpile(self, ppl_code, out_path='screen.png'):
        code = self._preprocess(ppl_code); self._first_pass(code); self._emit_header()
        buf = []
        for raw in code.splitlines():
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
        self._emit0("")
        self._emit_footer(out_path)
        return '\n'.join(self._out)

def transpile(ppl_code, out_path='screen.png'): return Transpiler().transpile(ppl_code, out_path)
