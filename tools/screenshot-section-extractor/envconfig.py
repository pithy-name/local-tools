"""Minimal .env loader — stdlib only, zero dependencies.

Reads flat KEY=VALUE lines. Skips blank lines and #-comments. Strips surrounding
quotes from values, and drops trailing inline comments (whitespace + #) from
*unquoted* values (so a quoted value may itself contain '#'). Deliberately NOT
python-dotenv: keeps the toolkit a "just run it", dependency-free script.
"""

import re


def load_env(path):
    """Return {KEY: VALUE} parsed from `path`. Missing file -> empty dict."""
    cfg = {}
    try:
        with open(path) as f:
            lines = f.readlines()
    except FileNotFoundError:
        return cfg
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip()
        if val[:1] in ("'", '"'):                       # quoted: take to matching quote
            q = val[0]
            end = val.find(q, 1)
            val = val[1:end] if end != -1 else val[1:]
        else:                                           # unquoted: strip inline comment
            val = re.split(r"\s+#", val, maxsplit=1)[0].strip()
        cfg[key] = val
    return cfg
