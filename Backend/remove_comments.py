import sys
import tokenize
import io
import os

def remove_comments_and_docstrings(source_code):
    out = ""
    prev_toktype = tokenize.INDENT
    last_lineno = -1
    last_col = 0
    io_obj = io.StringIO(source_code)
    
    try:
        for tok in tokenize.generate_tokens(io_obj.readline):
            token_type = tok[0]
            token_string = tok[1]
            start_line, start_col = tok[2]
            end_line, end_col = tok[3]
            
            if start_line > last_lineno:
                last_col = 0
            if start_col > last_col:
                out += (" " * (start_col - last_col))
                
            if token_type == tokenize.COMMENT:
                pass # ignore comment
            elif token_type == tokenize.STRING:
                if prev_toktype != tokenize.INDENT and prev_toktype != tokenize.NEWLINE and start_col > 0:
                    out += token_string
                else:
                    # Docstring: on l'ignore
                    pass
            else:
                out += token_string
                
            prev_toktype = token_type
            last_col = end_col
            last_lineno = end_line
    except tokenize.TokenError:
        return source_code # fall back if syntax error
        
    # Nettoyage des lignes vides multiples
    lines = out.split('\n')
    cleaned_lines = []
    for line in lines:
        if line.strip():
            cleaned_lines.append(line)
            
    return "\n".join(cleaned_lines) + "\n"

def process_file(filepath):
    print(f"Processing {filepath}...")
    with open(filepath, 'r', encoding='utf-8') as file:
        source = file.read()
    
    cleaned = remove_comments_and_docstrings(source)
    
    with open(filepath, 'w', encoding='utf-8') as file:
        file.write(cleaned)

def process_dir(directory):
    for root, dirs, files in os.walk(directory):
        for f in files:
            if f.endswith('.py'):
                process_file(os.path.join(root, f))

if __name__ == "__main__":
    process_dir('src')
    process_dir('scripts')
    if os.path.exists('dashboard_ui.py'):
        process_file('dashboard_ui.py')
    if os.path.exists('main.py'):
        process_file('main.py')
