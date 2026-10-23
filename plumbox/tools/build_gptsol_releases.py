"""Wspólne pliki runtime i ich kopiowanie do wariantu pakietowego."""
from pathlib import Path
import shutil
ROOT = Path(__file__).resolve().parents[1]
SHARED_FILES = tuple(sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / "app").rglob("*") if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"))
def copy_runtime_to(destination):
    destination = Path(destination)
    for relative in SHARED_FILES:
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target)
