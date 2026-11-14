"""Load a `.env` file into `os.environ` (stdlib only, no new dependency).

Sought from the working directory upwards so both `sherlock-rec` (any cwd) and the eval scripts
(python/sherlock) find the repository root's `.env`. Existing environment variables win — the file
only fills what the shell did not export, so `SHERLOCK_G1_API_KEY=... sherlock-rec ...` still works.

`.env` format: `KEY=VALUE` lines, `#` comments, blank lines, optional `export ` prefix, optional
quoting. Secrets stay in `.env` (git-ignored); `.env-example` documents every key.
"""

import os
from pathlib import Path


def parse(text: str) -> dict:
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        line = line.removeprefix("export ").strip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if not value.startswith(("'", '"')) and " #" in value:
            value = value.split(" #")[0].rstrip()  # an inline comment, but not inside quotes
        value = value.strip('"').strip("'")
        if value and not out.get(key):
            out[key.strip()] = value
    return out


def find(start: Path | None = None) -> Path | None:
    here = Path(start or Path.cwd()).resolve()
    for path in (here, *here.parents):
        if (path / ".env").is_file():
            return path / ".env"
    return None


def load(start: Path | None = None, override: bool = False) -> Path | None:
    """Apply every unset key from the nearest .env; returns the path (None when there is no file)."""
    path = find(start)
    if path is None:
        return None
    for key, value in parse(path.read_text(encoding="utf-8")).items():
        if override or not os.environ.get(key):
            os.environ[key] = value
    return path
