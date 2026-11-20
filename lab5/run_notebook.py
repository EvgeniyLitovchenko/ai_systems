"""Execute with the current Python; retain partial outputs on errors."""
import os
import sys
from pathlib import Path
import nbformat
from nbclient import NotebookClient
from jupyter_client.kernelspec import KernelSpecManager

root = Path(__file__).resolve().parent
os.chdir(root)
# A private kernelspec avoids changing the user's Jupyter configuration.
kernel_dir = root / '.cache' / 'kernels' / 'lab5'
kernel_dir.mkdir(parents=True, exist_ok=True)
import json
(kernel_dir / 'kernel.json').write_text(json.dumps({
    'argv': [sys.executable, '-m', 'ipykernel_launcher', '-f', '{connection_file}'],
    'display_name': 'Lab 5 Python', 'language': 'python'
}), encoding='utf-8')
manager = KernelSpecManager(kernel_dirs=[str(kernel_dir.parent)])
path = root / 'ft_project.ipynb'
notebook = nbformat.read(path, as_version=4)
client = NotebookClient(notebook, timeout=3600, kernel_name='lab5',
                        kernel_manager_class='jupyter_client.KernelManager',
                        resources={'metadata': {'path': str(root)}})
# Pass an explicit manager so the interpreter is precisely this virtualenv.
from jupyter_client import KernelManager
client.km = KernelManager(kernel_name='lab5', kernel_spec_manager=manager)
client.owns_km = True

def progress(cell, cell_index, **kwargs):
    if cell.cell_type == 'code':
        print(f'Cell {cell_index + 1}/{len(notebook.cells)} completed', flush=True)
        nbformat.write(notebook, path)
client.on_cell_executed = progress
try:
    client.execute()
finally:
    nbformat.write(notebook, path)
print('Notebook saved:', path, flush=True)
