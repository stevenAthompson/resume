#!/usr/bin/env python3
"""
Render a resume HTML file from a Markdown content file + a Mustache template.

Usage:
  python resume_render.py --content resume.md --template templates/resume_base.mustache.html --output out.html

The content markdown is expected to follow the structure used by the provided resume.md:
- H1 name
- Sections:
  - Personal Info (list of "- **Label**: value" where value can be a Markdown link)
  - Summary (one paragraph)
  - Skills (list of "- Skill — 80%")
  - Certs & Education (list items, optional links)
  - Acknowledgments (list items, optional links)
  - Recent Experience (repeating job blocks)
  - Keywords (one line)
"""
from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import html as html_mod

from mustache import Renderer

# -----------------------------
# Markdown parsing (specific to resume.md structure)
# -----------------------------
def _strip_md(s: str) -> str:
    return s.strip()

def _unescape_entities(s: str) -> str:
    # Allows users to keep &amp; / &nbsp; etc in markdown and still get correct HTML output.
    return html_mod.unescape(s)

def _parse_md_link(s: str) -> Tuple[str, Optional[str]]:
    s = s.strip()
    m = re.fullmatch(r"\[(.+?)\]\((.+?)\)", s)
    if m:
        return _unescape_entities(m.group(1).strip()), m.group(2).strip()
    return _unescape_entities(s), None

def parse_resume_markdown(md_text: str) -> Dict[str, Any]:
    lines = md_text.splitlines()
    i = 0

    # Find H1
    while i < len(lines) and not lines[i].startswith("# "):
        i += 1
    if i >= len(lines):
        raise ValueError("Could not find H1 '# Name' in content markdown.")
    full_name = lines[i][2:].strip()
    name_parts = full_name.split()
    first_name = name_parts[0]
    last_name = name_parts[-1] if len(name_parts) > 1 else ""
    i += 1

    # Collect sections keyed by H2
    sections: Dict[str, List[str]] = {}
    current = None
    buf: List[str] = []
    def flush():
        nonlocal buf, current
        if current is not None:
            sections[current] = buf[:]
        buf = []

    while i < len(lines):
        line = lines[i]
        if line.startswith("## "):
            flush()
            current = line[3:].strip()
        else:
            if current is not None:
                buf.append(line)
        i += 1
    flush()

    # Personal Info
    pi_lines = sections.get("Personal Info", [])
    personal_info: List[Dict[str, Any]] = []
    for line in pi_lines:
        line = line.strip()
        if not line.startswith("- "):
            continue
        # - **Label**: value
        m = re.match(r"-\s+\*\*(.+?)\*\*:\s*(.+)$", line)
        if not m:
            continue
        label = _unescape_entities(m.group(1).strip())
        value_raw = m.group(2).strip()
        value, href = _parse_md_link(value_raw)
        personal_info.append({"label": label, "value": value, "href": href})

    # Summary
    summary_lines = [l.strip() for l in sections.get("Summary", []) if l.strip()]
    summary = _unescape_entities(" ".join(summary_lines))

    # Skills
    skills: List[Dict[str, Any]] = []
    for line in sections.get("Skills", []):
        line = line.strip()
        if not line.startswith("- "):
            continue
        item = line[2:].strip()
        # Skill — 80% (em dash)
        m = re.match(r"(.+?)\s+—\s+(\d+)\s*%$", item)
        if not m:
            # Allow hyphen dash fallback
            m = re.match(r"(.+?)\s+-\s+(\d+)\s*%$", item)
        if not m:
            continue
        name = _unescape_entities(m.group(1).strip())
        percent = int(m.group(2))
        skills.append({"name": name, "percent": percent})

    def parse_simple_list(section_name: str) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for line in sections.get(section_name, []):
            line = line.strip()
            if not line.startswith("- "):
                continue
            text, href = _parse_md_link(line[2:].strip())
            item: Dict[str, Any] = {"text": text}
            if href:
                item["href"] = href
            out.append(item)
        return out

    certs_education = parse_simple_list("Certs & Education")
    acknowledgments = parse_simple_list("Acknowledgments")

    # Recent Experience
    exp_lines = sections.get("Recent Experience", [])
    experience: List[Dict[str, Any]] = []
    j = 0
    while j < len(exp_lines):
        line = exp_lines[j].strip()
        if line.startswith("### "):
            header = line[4:].strip()
            # Title — Company
            if " — " in header:
                title, company = [h.strip() for h in header.split(" — ", 1)]
            else:
                title, company = header, ""
            # Dates line
            j += 1
            while j < len(exp_lines) and not exp_lines[j].strip():
                j += 1
            dates = ""
            if j < len(exp_lines):
                m = re.match(r"\*\*Dates:\*\*\s*(.+)$", exp_lines[j].strip())
                if m:
                    dates = _unescape_entities(m.group(1).strip())
                    j += 1

            # Description paragraph (until bullets or next job)
            desc_parts: List[str] = []
            while j < len(exp_lines):
                t = exp_lines[j].strip()
                if t.startswith("### "):
                    break
                if t.startswith("- "):
                    break
                if t:
                    desc_parts.append(t)
                j += 1
            description = _unescape_entities(" ".join(desc_parts)).strip()

            # Bullets
            bullets: List[Dict[str, Any]] = []
            while j < len(exp_lines):
                t = exp_lines[j].strip()
                if t.startswith("### "):
                    break
                if t.startswith("- "):
                    b = t[2:].strip()
                    # **Lead:** text
                    m = re.match(r"\*\*(.+?)\*\*\s*(.+)$", b)
                    if m:
                        lead = _unescape_entities(m.group(1).strip())
                        text = _unescape_entities(m.group(2).strip())
                        bullets.append({"lead": lead, "text": text})
                    else:
                        bullets.append({"lead": "", "text": _unescape_entities(b)})
                j += 1

            experience.append({
                "dates": dates,
                "title": _unescape_entities(title),
                "company": _unescape_entities(company),
                "description": description,
                "bullets": bullets,
            })
        else:
            j += 1

    # Keywords
    kw_lines = [l.strip() for l in sections.get("Keywords", []) if l.strip()]
    keywords = _unescape_entities(" ".join(kw_lines))

    return {
        "person": {"full_name": full_name, "first_name": first_name, "last_name": last_name},
        "personal_info": personal_info,
        "summary": summary,
        "skills": skills,
        "certs_education": certs_education,
        "acknowledgments": acknowledgments,
        "experience": experience,
        "keywords": keywords,
    }

# -----------------------------
# CLI
# -----------------------------
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--content", default="resume.md", help="Path to Markdown content file")
    ap.add_argument("--template", default="templates/resume_base.mustache.html", help="Path to Mustache HTML template")
    ap.add_argument("--output", default="resume_generated.html", help="Path to write rendered HTML")
    ap.add_argument("--data-out", default=None, help="Optional path to write parsed JSON data")
    args = ap.parse_args()

    content_path = Path(args.content)
    template_path = Path(args.template)
    out_path = Path(args.output)

    md_text = content_path.read_text(encoding="utf-8")
    data = parse_resume_markdown(md_text)

    if args.data_out:
        Path(args.data_out).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    renderer = Renderer(template_dir=template_path.parent)
    html_out = renderer.render(template_path.read_text(encoding="utf-8"), data)
    out_path.write_text(html_out, encoding="utf-8")
    print(f"Wrote: {out_path}")

if __name__ == "__main__":
    main()
