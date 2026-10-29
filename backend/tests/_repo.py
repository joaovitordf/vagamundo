from pathlib import Path

class RepoPath(type(Path())):
    def __truediv__(self, other):
        res = super().__truediv__(other)
        if not res.exists() and "backend" not in self.parts:
            # Try backend candidate without recursion
            backend_target = Path(self) / "backend" / other
            if backend_target.exists():
                return RepoPath(backend_target)
        return RepoPath(res)

_here = Path(__file__).resolve()
REPO_ROOT = RepoPath(_here.parents[2] if _here.parent.parent.name == "backend" else _here.parent.parent)
REPO = REPO_ROOT
