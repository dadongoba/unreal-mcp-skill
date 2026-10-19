"""Read published guidance without depending on a host's skill loader."""
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]


def documents(root=ROOT):
    root = Path(root).resolve()
    paths = [root / "SKILL.md", root / "schemas" / "experience.v1.json"]
    paths += sorted((root / "references").glob("*.md"))
    paths += sorted((root / "references" / "capabilities").glob("*.md"))
    paths += sorted((root / "references" / "templates").glob("*.txt"))
    # Inbox and candidates are deliberately absent: receiving a report is not verification.
    paths += sorted((root / "knowledge" / "published").glob("*.json"))
    return {p.relative_to(root).as_posix(): p for p in paths
            if p.is_file() and p.resolve().is_relative_to(root)}


def read(path="SKILL.md", offset=0, limit=12000, root=ROOT):
    paths = documents(root)
    if path not in paths:
        raise ValueError("Unknown published knowledge path; search available documents first")
    if not 0 <= offset <= 1000000 or not 1 <= limit <= 24000:
        raise ValueError("Invalid knowledge page range")
    content = paths[path].read_text(encoding="utf-8-sig")
    return {"path": path, "text": content[offset:offset + limit],
            "next_offset": offset + limit if offset + limit < len(content) else None,
            "instruction": "Respect each fact's confidence and engine/language applicability."}


def search(query, limit=8, root=ROOT):
    if not query.strip() or len(query) > 200 or not 1 <= limit <= 20:
        raise ValueError("Supply a 1-200 character query and limit 1-20")
    terms = set(re.findall(r"[\w-]+", query.casefold()))
    hits = []
    for name, path in documents(root).items():
        content = path.read_text(encoding="utf-8-sig")
        lower = content.casefold()
        score = sum(min(lower.count(term), 10) + 10 * (term in name.casefold()) for term in terms)
        if score:
            start = max(0, min((lower.find(t) for t in terms if t in lower), default=0) - 160)
            hits.append({"path": name, "score": score, "excerpt": content[start:start + 1000]})
    return {"matches": sorted(hits, key=lambda h: (-h["score"], h["path"]))[:limit],
            "scope": "Published references and promoted knowledge only; check applicability before use."}
