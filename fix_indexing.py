import re
import os

def fix_file(path, variables):
    if not os.path.exists(path):
        print(f"File not found: {path}")
        return

    print(f"Fixing {path}...")
    with open(path, 'r', encoding='utf-8', errors='replace') as f:
        content = f.read()

    new_content = content
    # Sort variables by length descending to avoid partial matches
    sorted_vars = sorted(variables, key=len, reverse=True)
    
    for var in sorted_vars:
        pos = 0
        while True:
            # Find var( (case insensitive)
            match = re.search(r'\b' + re.escape(var) + r'\s*\(', new_content[pos:], re.IGNORECASE)
            if not match:
                break
            
            match_start = pos + match.start()
            start_bracket = pos + match.end() - 1
            
            # Find matching parenthesis
            depth = 0
            end_bracket = -1
            for i in range(start_bracket, len(new_content)):
                if new_content[i] == '(':
                    depth += 1
                elif new_content[i] == ')':
                    depth -= 1
                    if depth == 0:
                        end_bracket = i
                        break
            
            if end_bracket != -1:
                # Replace ( and ) with [ and ]
                inner = new_content[start_bracket+1:end_bracket]
                new_content = new_content[:start_bracket] + '[' + inner + ']' + new_content[end_bracket+1:]
                
                # Check for consecutive indexing: var[idx](idx2)
                current_pos = end_bracket + 1
                while current_pos < len(new_content) and new_content[current_pos] == '(':
                    depth = 0
                    inner_end = -1
                    for j in range(current_pos, len(new_content)):
                        if new_content[j] == '(': depth += 1
                        elif new_content[j] == ')':
                            depth -= 1
                            if depth == 0:
                                inner_end = j
                                break
                    if inner_end != -1:
                        inner_text = new_content[current_pos+1:inner_end]
                        new_content = new_content[:current_pos] + '[' + inner_text + ']' + new_content[inner_end+1:]
                        current_pos = inner_end + 1
                    else:
                        break
                
                pos = start_bracket + 1 # Continue after the [
            else:
                pos = start_bracket + 1
    
    with open(path, 'w', encoding='utf-8', errors='replace') as f:
        f.write(new_content)

files_to_fix = {
    r'..\4-Fireworks\Fireworks.hpprgm': ['fw_list', 'p_list', 'm_info'],
    r'..\1-Binary Search Tree Visualizer\BSTVisualizer.hpprgm': ['bst_val', 'bst_left', 'bst_right', 'bst_used'],
    r'..\3-Starfield Warp\STARFIELD.hpprgm': ['sx', 'sy', 'sz', 'fx', 'fy', 'fdx', 'fdy', 'flife', 'fcr', 'fcg', 'fcb'],
    r'..\6-Advanced Payments 2,0\Leasing20.hpprgm': ['m1', 'mTXT', 'm', 'L1']
}

for path, vars in files_to_fix.items():
    fix_file(path, vars)

print("Done.")
