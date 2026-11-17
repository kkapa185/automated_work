"""Local file, git diff, generic URL, stack-trace and raw text ingestion."""

from __future__ import annotations

import asyncio
import os
import shlex
from pathlib import Path

from connectors.base import BaseConnector, ConnectorError
from connectors.html import html_to_markdown
from schemas import ContextArtifact, ContextSource, SourceKind

TEXT_SUFFIX_LANG = {
    ".py": "python", ".js": "javascript", ".ts": "typescript", ".tsx": "tsx", ".jsx": "jsx",
    ".go": "go", ".rs": "rust", ".java": "java", ".kt": "kotlin", ".rb": "ruby", ".sh": "bash",
    ".json": "json", ".yaml": "yaml", ".yml": "yaml", ".toml": "toml", ".md": "markdown",
    ".sql": "sql", ".html": "html", ".css": "css", ".c": "c", ".h": "c", ".cpp": "cpp",
}
MAX_DIR_FILES = 50


def resolve_path(ref: str, workspace: str | None) -> Path:
    p = Path(os.path.expanduser(ref))
    if not p.is_absolute() and workspace:
        candidate = Path(workspace) / p
        if candidate.exists():
            return candidate
    return p


def _is_binary(data: bytes) -> bool:
    return b"\x00" in data[:8192]


class LocalFileConnector(BaseConnector):
    kind = SourceKind.FILE

    async def fetch(self, source: ContextSource, workspace: str | None = None) -> ContextArtifact:
        path = resolve_path(source.ref, workspace)
        return await asyncio.to_thread(self._read, path, source.ref)

    def _read(self, path: Path, ref: str) -> ContextArtifact:
        limit = self.settings.max_artifact_chars
        if not path.exists():
            raise ConnectorError(f"path does not exist: {path}")
        if path.is_dir():
            files = sorted(
                f for f in path.rglob("*")
                if f.is_file() and not any(part.startswith(".") or part in {"node_modules", "__pycache__"} for part in f.relative_to(path).parts)
            )
            chunks, total = [], 0
            for f in files[:MAX_DIR_FILES]:
                raw = f.read_bytes()
                if _is_binary(raw):
                    continue
                text = raw.decode("utf-8", errors="replace")
                block = f"### {f.relative_to(path)}\n```{TEXT_SUFFIX_LANG.get(f.suffix, '')}\n{text}\n```"
                if total + len(block) > limit:
                    chunks.append(f"_...{len(files) - len(chunks)} more files omitted_")
                    break
                chunks.append(block)
                total += len(block)
            return ContextArtifact(
                kind=SourceKind.FILE, ref=ref, title=f"Directory {path}",
                content="\n\n".join(chunks), metadata={"path": str(path), "files": len(files)},
            )
        raw = path.read_bytes()
        if _is_binary(raw):
            raise ConnectorError(f"refusing to ingest binary file: {path}")
        text = raw.decode("utf-8", errors="replace")
        lang = TEXT_SUFFIX_LANG.get(path.suffix, "")
        return ContextArtifact(
            kind=SourceKind.FILE, ref=ref, title=f"File {path.name}",
            content=f"```{lang}\n{text}\n```", metadata={"path": str(path), "bytes": len(raw)},
        )


class GitDiffConnector(BaseConnector):
    """``ref`` is a git revision range (``main...HEAD``), ``staged``, or ``working`` (default)."""

    kind = SourceKind.GIT_DIFF

    async def fetch(self, source: ContextSource, workspace: str | None = None) -> ContextArtifact:
        cwd = workspace or os.getcwd()
        ref = source.ref.strip()
        if ref in ("", "working", "HEAD"):
            args = ["git", "diff", "HEAD"]
        elif ref in ("staged", "cached"):
            args = ["git", "diff", "--cached"]
        else:
            parts = shlex.split(ref)
            if any(p.startswith("-") and p not in ("--stat",) for p in parts):
                raise ConnectorError(f"unsupported git diff argument in {ref!r}")
            args = ["git", "diff", *parts]
        proc = await asyncio.create_subprocess_exec(
            *args, cwd=cwd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.DEVNULL,
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=60)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise ConnectorError("git diff timed out")
        if proc.returncode != 0:
            raise ConnectorError(f"git diff failed ({proc.returncode}): {err.decode(errors='replace')[:500]}")
        diff = out.decode("utf-8", errors="replace")
        return ContextArtifact(
            kind=SourceKind.GIT_DIFF, ref=ref or "working", title=f"git diff {ref or 'working'}",
            content=f"```diff\n{diff or '(no changes)'}\n```", metadata={"cwd": cwd, "bytes": len(out)},
        )


class UrlConnector(BaseConnector):
    kind = SourceKind.URL

    async def fetch(self, source: ContextSource, workspace: str | None = None) -> ContextArtifact:
        url = source.ref.strip()
        if not url.startswith(("http://", "https://")):
            raise ConnectorError(f"unsupported URL scheme: {url!r}")
        resp = await self.request("GET", url, headers={"Accept": "text/html,text/plain,application/json,*/*"})
        ctype = resp.headers.get("content-type", "").lower()
        body = resp.text
        if "html" in ctype:
            content = html_to_markdown(body)
        elif "json" in ctype:
            content = f"```json\n{body}\n```"
        elif ctype.startswith("text/") or not ctype:
            content = body
        else:
            raise ConnectorError(f"unsupported content type {ctype!r} for {url}")
        return ContextArtifact(
            kind=SourceKind.URL, ref=url, title=f"Document {url}", content=content,
            metadata={"content_type": ctype, "status": resp.status_code},
        )


class InlineTextConnector(BaseConnector):
    """Stack traces and raw text snippets are already content; wrap them verbatim."""

    kind = SourceKind.TEXT

    async def fetch(self, source: ContextSource, workspace: str | None = None) -> ContextArtifact:
        title = "Stack trace" if source.kind == SourceKind.STACK_TRACE else "Provided text"
        return ContextArtifact(kind=source.kind, ref=source.ref[:80], title=title, content=f"```\n{source.ref}\n```")
