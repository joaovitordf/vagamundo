import sys
from pathlib import Path

_backend_dir = Path(__file__).resolve().parent.parent
_tests_dir = Path(__file__).resolve().parent

for p in (str(_backend_dir), str(_backend_dir / "tools"), str(_tests_dir)):
    if p not in sys.path:
        sys.path.insert(0, p)

# Alias 'tests' in sys.modules so 'import tests.foo' works seamlessly
if "tests" not in sys.modules:
    sys.modules["tests"] = sys.modules[__name__]
