"""Assemble fetched artifacts into one structured prompt payload."""

from __future__ import annotations

from xml.sax.saxutils import quoteattr

from schemas import CompiledContext, ContextArtifact


def _truncate(text: str, limit: int) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    head = int(limit * 0.7)
    tail = limit - head
    return text[:head] + f"\n\n...[{len(text) - limit} characters truncated]...\n\n" + text[-tail:], True


class ContextCompiler:
    def __init__(self, max_total_chars: int = 120_000, max_artifact_chars: int = 40_000):
        self.max_total = max_total_chars
        self.max_artifact = max_artifact_chars

    def compile(self, description: str, artifacts: list[ContextArtifact]) -> CompiledContext:
        ok = [a for a in artifacts if a.ok]
        failed = [a for a in artifacts if not a.ok]
        truncated = False
        parts = ["<task_request>", description.strip(), "</task_request>", "", "<context>"]
        budget = self.max_total - sum(len(p) for p in parts) - 200
        for a in ok:
            body, t = _truncate(a.content, min(self.max_artifact, max(0, budget)))
            truncated |= t
            if budget <= 0:
                truncated = True
                parts.append(f"<artifact kind={quoteattr(a.kind.value)} ref={quoteattr(a.ref)} omitted=\"budget\"/>")
                continue
            block = (
                f"<artifact kind={quoteattr(a.kind.value)} ref={quoteattr(a.ref)} title={quoteattr(a.title)}>\n"
                f"{body}\n</artifact>"
            )
            budget -= len(block)
            parts.append(block)
        if failed:
            parts.append("<unavailable_sources>")
            for a in failed:
                parts.append(f"- {a.kind.value} {a.ref}: {a.error}")
            parts.append("</unavailable_sources>")
        parts.append("</context>")
        return CompiledContext(payload="\n".join(parts), artifacts=artifacts, truncated=truncated)
