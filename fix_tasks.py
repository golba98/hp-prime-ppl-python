import re
import os

def fix_indexing(content, variables):
    new_content = content
    sorted_vars = sorted(variables, key=len, reverse=True)
    for var in sorted_vars:
        pos = 0
        while True:
            match = re.search(r'\b' + re.escape(var) + r'\s*\(', new_content[pos:], re.IGNORECASE)
            if not match: break
            match_start = pos + match.start()
            start_bracket = pos + match.end() - 1
            depth, end_bracket = 0, -1
            for i in range(start_bracket, len(new_content)):
                if new_content[i] == '(': depth += 1
                elif new_content[i] == ')':
                    depth -= 1
                    if depth == 0:
                        end_bracket = i
                        break
            if end_bracket != -1:
                inner = new_content[start_bracket+1:end_bracket]
                new_content = new_content[:start_bracket] + '[' + inner + ']' + new_content[end_bracket+1:]
                # Check for consecutive indexing
                current_pos = end_bracket + 1
                # ... skip complex consecutive check for now, just do simple ...
                pos = start_bracket + 1
            else: pos = start_bracket + 1
    return new_content

def clean_file(path, variables=None, extract_ppl=False):
    if not os.path.exists(path): return
    with open(path, 'rb') as f: raw_data = f.read()
    try: content = raw_data.decode('utf-8')
    except: content = raw_data.decode('latin-1')

    if "ADVPMT" in path:
        content = """EXPORT ADVPMT(N,I,P,S,A)
BEGIN
// advance monthly payments
// 2018-03-15 EWS
// HP 17BII+
LOCAL X;
X:=(P-S*Finance.TvmPV(N,I,0,1,12))/(Finance.TvmPV(N-A,I,1,0,12)+A);
RETURN ROUND(X,2);
END;"""
    else:
        if extract_ppl:
            match = re.search(r'(EXPORT\s+.*END;)', content, re.DOTALL | re.IGNORECASE)
            if match: content = match.group(1)
        
        # General non-ascii cleanup
        content = content.replace('\ufffd', ' ')
        content = re.sub(r'[^\x00-\x7f]', ' ', content) # Remove all non-ascii

        if "Leasing20" in path:
            # surgical fix for MOUSE line
            content = re.sub(r'WHILE\s+MOUSE\(1\).*?0\s+DO\s+END;', 'WHILE SIZE(MOUSE) != 0 DO END;', content, flags=re.IGNORECASE)
            # fix B->R
            content = re.sub(r'B\s*->\s*R', 'B->R', content) # Ensure it's clean
            # Join multi-line INPUT
            content = re.sub(r'INPUT\s*\([^;]+?\);', lambda m: m.group(0).replace('\n', ' ').replace('\r', ' '), content, flags=re.DOTALL | re.IGNORECASE)

    if variables:
        content = fix_indexing(content, variables)

    with open(path, 'w', encoding='ascii', errors='replace') as f:
        f.write(content)

tasks = [
    {'path': r'..\4-Fireworks\test_fireworks.hpprgm', 'vars': ['fw_list', 'p_list', 'm_info'], 'extract': False},
    {'path': r'..\1-Binary Search Tree Visualizer\BSTVisualizer.hpprgm', 'vars': ['bst_val', 'bst_left', 'bst_right', 'bst_used'], 'extract': False},
    {'path': r'..\5-Advanced Lease Payments\ADVPMT.hpprgm', 'vars': [], 'extract': True},
    {'path': r'..\6-Advanced Payments 2,0\Leasing20.hpprgm', 'vars': ['m1', 'mTXT', 'm', 'L1'], 'extract': True}
]

for task in tasks:
    clean_file(task['path'], task['vars'], task['extract'])
print("Done.")
