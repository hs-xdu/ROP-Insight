"""Source identity without placing repository paths in exported results."""

from pathlib import Path
import subprocess


def code_identity():
    root = Path(__file__).resolve().parents[3]
    args = ['git', f'--git-dir={root / ".git"}', f'--work-tree={root}']
    options = dict(capture_output=True, text=True, timeout=3,
                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    try:
        revision = subprocess.run(args + ['rev-parse', 'HEAD'], **options)
        status = subprocess.run(args + ['status', '--porcelain'], **options)
        if revision.returncode or status.returncode:
            return None, None
        return revision.stdout.strip(), bool(status.stdout.strip())
    except (OSError, subprocess.TimeoutExpired):
        return None, None
