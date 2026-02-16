"""
Tiny Mustache-like renderer (subset).

Supported:
- Variables: {{name}} (HTML-escaped), {{{name}}} (unescaped)
- Dotted names: {{person.full_name}}
- Sections: {{#items}} ... {{/items}} (lists/dicts/truthy)
- Inverted sections: {{^items}} ... {{/items}}
- Comments: {{! comment }}
- Partials: {{> partial}} (optional; resolved relative to template directory)

This is intentionally small and dependency-free.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union
import html
import re

# -----------------------------
# Escaping
# -----------------------------
def html_escape(s: str) -> str:
    # Match browser-like escaping for text nodes / attribute contexts.
    # Note: do NOT escape apostrophes to preserve common HTML source expectations.
    return (
        s.replace("&", "&amp;")
         .replace("<", "&lt;")
         .replace(">", "&gt;")
         .replace('"', "&quot;")
    )

# -----------------------------
# AST nodes
# -----------------------------
@dataclass
class TextNode:
    text: str

@dataclass
class VarNode:
    name: str
    escaped: bool = True

@dataclass
class SectionNode:
    name: str
    inverted: bool
    children: List[Any]

@dataclass
class PartialNode:
    name: str

@dataclass
class CommentNode:
    pass


Token = Union[TextNode, VarNode, SectionNode, PartialNode, CommentNode]

# -----------------------------
# Parsing
# -----------------------------
_TAG_RE = re.compile(r"{{({{)?\s*([^}]+?)\s*}}}?" , re.DOTALL)

def _is_triple(opening: str) -> bool:
    return opening == "{{"

def _split_tag(raw: str) -> Tuple[str, str]:
    raw = raw.strip()
    if not raw:
        return ("", "")
    t = raw[0]
    if t in "#^/!>":
        return (t, raw[1:].strip())
    if t == "&":
        return ("&", raw[1:].strip())
    return ("", raw)

def _find_line_bounds(tmpl: str, start: int, end: int) -> Tuple[int, int]:
    line_start = tmpl.rfind("\n", 0, start) + 1
    line_end = tmpl.find("\n", end)
    if line_end == -1:
        line_end = len(tmpl)
    return line_start, line_end

def _standalone_trim(tmpl: str, start: int, end: int, tag_type: str) -> Optional[Tuple[int, int]]:
    # Implements Mustache "standalone lines" trimming for section/open/close/inverted/comment/partial.
    if tag_type not in {"#", "^", "/", "!", ">"}:
        return None
    line_start, line_end = _find_line_bounds(tmpl, start, end)
    left = tmpl[line_start:start]
    right = tmpl[end:line_end]
    if left.strip() == "" and right.strip() == "":
        # Trim entire line, including trailing newline if present.
        trim_start = line_start
        trim_end = line_end
        if trim_end < len(tmpl) and tmpl[trim_end:trim_end+1] == "\n":
            trim_end += 1
        return (trim_start, trim_end)
    return None

def parse_template(tmpl: str) -> List[Token]:
    tokens: List[Token] = []
    pos = 0
    # We'll collect raw tokens first while applying standalone trimming by manipulating text spans.
    while True:
        m = _TAG_RE.search(tmpl, pos)
        if not m:
            if pos < len(tmpl):
                tokens.append(TextNode(tmpl[pos:]))
            break
        start, end = m.span()
        triple = bool(m.group(1))
        raw_tag = m.group(2)
        tag_type, name = _split_tag(raw_tag)

        # text before tag
        if start > pos:
            tokens.append(TextNode(tmpl[pos:start]))

        # standalone handling: if standalone, remove the whole line from output text tokens
        trim = _standalone_trim(tmpl, start, end, tag_type)
        if trim is not None:
            trim_start, trim_end = trim
            # remove any just-added text that belongs to the standalone line's left padding
            # by rewriting the last TextNode if it exists
            if tokens and isinstance(tokens[-1], TextNode):
                # tokens[-1].text includes content from pos..start; we want to remove back to trim_start
                # Find how much overlap there is with this node:
                current = tokens[-1].text
                # The text node spans from some point; we can approximate by trimming trailing whitespace up to line_start.
                # Easiest: drop any trailing whitespace/newline in this node after the last newline.
                # Since trim_start is line_start, we can remove from last newline+1 to end of node.
                cut = current.rfind("\n")
                if cut != -1:
                    tokens[-1].text = current[:cut+1]
                else:
                    tokens[-1].text = ""
            # still keep the semantic tag token (for sections/partials/comments), but it renders nothing itself
            if tag_type == "!":
                tokens.append(CommentNode())
            elif tag_type == ">":
                tokens.append(PartialNode(name))
            elif tag_type in {"#", "^", "/"}:
                tokens.append(VarNode(tag_type + name, escaped=False))  # sentinel for building tree
            # advance pos to end of trimmed region
            pos = trim_end
            continue

        # normal tag tokens
        if triple:
            tokens.append(VarNode(name, escaped=False))
        else:
            if tag_type == "":
                tokens.append(VarNode(name, escaped=True))
            elif tag_type == "&":
                tokens.append(VarNode(name, escaped=False))
            elif tag_type == "!":
                tokens.append(CommentNode())
            elif tag_type == ">":
                tokens.append(PartialNode(name))
            elif tag_type in {"#", "^", "/"}:
                tokens.append(VarNode(tag_type + name, escaped=False))  # sentinel
            else:
                # unknown; treat as literal
                tokens.append(TextNode(m.group(0)))
        pos = end
    return tokens

def build_tree(tokens: List[Token]) -> List[Token]:
    root: List[Token] = []
    stack: List[SectionNode] = []
    def add(node: Token):
        if stack:
            stack[-1].children.append(node)
        else:
            root.append(node)

    for tok in tokens:
        if isinstance(tok, VarNode) and not tok.escaped and tok.name and tok.name[0] in "#^/":
            t = tok.name[0]
            name = tok.name[1:].strip()
            if t in "#^":
                sec = SectionNode(name=name, inverted=(t=="^"), children=[])
                add(sec)
                stack.append(sec)
            elif t == "/":
                if not stack or stack[-1].name != name:
                    raise ValueError(f"Unmatched section end: {name}")
                stack.pop()
        elif isinstance(tok, CommentNode):
            continue
        else:
            add(tok)

    if stack:
        raise ValueError(f"Unclosed section(s): {[s.name for s in stack]}")
    return root

# -----------------------------
# Rendering
# -----------------------------
def _lookup(ctx_stack: Sequence[Any], name: str) -> Any:
    # dotted lookup; supports numeric segments for list indices.
    name = name.strip()
    if name == ".":
        return ctx_stack[-1] if ctx_stack else None
    parts = [p.strip() for p in name.split(".") if p.strip()]
    for ctx in reversed(ctx_stack):
        cur = ctx
        ok = True
        for p in parts:
            if isinstance(cur, dict) and p in cur:
                cur = cur[p]
            elif isinstance(cur, (list, tuple)) and p.isdigit():
                idx = int(p)
                if 0 <= idx < len(cur):
                    cur = cur[idx]
                else:
                    ok = False
                    break
            else:
                ok = False
                break
        if ok:
            return cur
    return None

def _is_truthy(val: Any) -> bool:
    if val is None:
        return False
    if val is False:
        return False
    if val == "":
        return False
    if isinstance(val, (list, tuple, dict)) and len(val) == 0:
        return False
    return True

class Renderer:
    def __init__(self, template_dir: Optional[Path] = None):
        self.template_dir = template_dir

    def render(self, template: str, data: Dict[str, Any]) -> str:
        tokens = build_tree(parse_template(template))
        return self._render_tokens(tokens, [data])

    def _render_tokens(self, tokens: List[Token], ctx_stack: List[Any]) -> str:
        out: List[str] = []
        for tok in tokens:
            if isinstance(tok, TextNode):
                out.append(tok.text)
            elif isinstance(tok, VarNode):
                val = _lookup(ctx_stack, tok.name)
                if val is None:
                    out.append("")
                else:
                    s = str(val)
                    out.append(html_escape(s) if tok.escaped else s)
            elif isinstance(tok, PartialNode):
                if not self.template_dir:
                    raise ValueError("Partials require template_dir")
                partial_path = (self.template_dir / (tok.name + ".mustache.html"))
                if not partial_path.exists():
                    # allow raw name including extension
                    partial_path = (self.template_dir / tok.name)
                partial = partial_path.read_text(encoding="utf-8")
                out.append(self._render_tokens(build_tree(parse_template(partial)), ctx_stack))
            elif isinstance(tok, SectionNode):
                val = _lookup(ctx_stack, tok.name)
                if tok.inverted:
                    if not _is_truthy(val):
                        out.append(self._render_tokens(tok.children, ctx_stack))
                else:
                    if isinstance(val, list):
                        for item in val:
                            ctx_stack.append(item)
                            out.append(self._render_tokens(tok.children, ctx_stack))
                            ctx_stack.pop()
                    elif isinstance(val, dict):
                        ctx_stack.append(val)
                        out.append(self._render_tokens(tok.children, ctx_stack))
                        ctx_stack.pop()
                    elif _is_truthy(val):
                        # render once with same context
                        out.append(self._render_tokens(tok.children, ctx_stack))
            else:
                # unknown node
                pass
        return "".join(out)
