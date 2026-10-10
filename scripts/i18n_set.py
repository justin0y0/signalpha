"""Set or add i18n keys in frontend/src/i18n/{en,zh}.ts.

    from i18n_set import apply
    apply({"some.key": ("English text", "中文文案")})

Existing keys are replaced in place (single- or double-quoted values); new keys are
appended before the closing brace. Run from anywhere: paths are resolved from this file.
"""
import re
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent / "frontend" / "src" / "i18n"


def _esc(v: str) -> str:
    return v.replace("\\", "\\\\").replace("'", "\\'")


def _set(path: Path, values: dict[str, str]) -> list[str]:
    s = path.read_text()
    added = []
    for key, val in values.items():
        if val is None:
            continue
        pat = re.compile(r"(\n\s*)'" + re.escape(key) + r"':\s*\n?\s*(?:'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"),")
        if pat.search(s):
            s = pat.sub(lambda m: f"{m.group(1)}'{key}': '{_esc(val)}',", s, count=1)
        else:
            idx = s.rstrip().rfind("}")
            s = s[:idx].rstrip() + f"\n  '{key}': '{_esc(val)}',\n" + s[idx:]
            added.append(key)
    path.write_text(s)
    return added


def apply(pairs: dict[str, tuple[str, str]]) -> None:
    a = _set(BASE / "en.ts", {k: v[0] for k, v in pairs.items()})
    b = _set(BASE / "zh.ts", {k: v[1] for k, v in pairs.items()})
    print(f"set {len(pairs)} keys; new en={len(a)} zh={len(b)}")
