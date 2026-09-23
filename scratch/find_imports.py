import os
import ast
import sys

root = os.path.dirname(os.path.abspath(__file__))
skip_dirs = {'.venv', 'venv', '__pycache__', '.git', '.pytest_cache'}

all_imports = set()

for dirpath, dirnames, filenames in os.walk(root):
    dirnames[:] = [d for d in dirnames if d not in skip_dirs]
    for f in filenames:
        if f.endswith('.py'):
            filepath = os.path.join(dirpath, f)
            try:
                with open(filepath, 'r', encoding='utf-8', errors='ignore') as fp:
                    tree = ast.parse(fp.read(), filename=filepath)
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            all_imports.add(alias.name.split('.')[0])
                    elif isinstance(node, ast.ImportFrom):
                        if node.module and node.level == 0:
                            all_imports.add(node.module.split('.')[0])
            except Exception as e:
                print(f"Error parsing {filepath}: {e}")

stdlib = sys.stdlib_module_names if hasattr(sys, 'stdlib_module_names') else set()
local_modules = {f[:-3] for f in os.listdir(root) if f.endswith('.py')}
local_dirs = {d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d))}

external = all_imports - stdlib - local_modules - local_dirs
print("External packages imported:")
for pkg in sorted(external):
    print(f"  {pkg}")
