"""Project ingestion pipeline — ingest a codebase as a memory graph."""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db, log_memory_event
from backend.lib.content_address import compute_content_hash
from backend.lib.vector_clock import increment_clock
from backend.models import Agent, Memory
from backend.redis_client import get_redis, ns_key

router = APIRouter()

# ── skip dirs / default extensions ────────────────────────────────────────────

_SKIP_DIRS: frozenset[str] = frozenset(
    {
        "node_modules",
        ".git",
        "__pycache__",
        "dist",
        ".venv",
        "build",
        ".next",
        "coverage",
        ".mypy_cache",
        ".pytest_cache",
    }
)

_DEFAULT_EXTENSIONS: frozenset[str] = frozenset(
    {".py", ".ts", ".tsx", ".js", ".jsx", ".md", ".json", ".yaml", ".yml"}
)

# ── regex patterns ─────────────────────────────────────────────────────────────

_PY_IMPORT = re.compile(
    r"^\s*(?:from\s+([\w.]+)\s+import|import\s+([\w.,\s]+))",
    re.MULTILINE,
)
_TS_IMPORT = re.compile(
    r"""import\s+(?:[^'";\n]*?\s+from\s+)?['\"]((?:\.|[^'\"\\s])[^'\"]*)['\"]""",
    re.MULTILINE,
)
_PY_EXPORT = re.compile(r"^(?:async\s+def|def|class)\s+(\w+)", re.MULTILINE)
_TS_EXPORT = re.compile(
    r"^export\s+(?:default\s+)?(?:function|class|const|let|var|interface|type|enum)\s+(\w+)",
    re.MULTILINE,
)

# ── request / response schemas ─────────────────────────────────────────────────


class IngestRequest(BaseModel):
    project_path: str
    agent_id: uuid.UUID
    project_name: str
    file_extensions: list[str] = []


class IngestResponse(BaseModel):
    project_name: str
    root_memory_id: uuid.UUID
    files_ingested: int
    edges_created: int
    agent_id: uuid.UUID
    ingested_at: datetime


class UpdateRequest(BaseModel):
    project_path: str
    agent_id: uuid.UUID
    project_name: str
    file_extensions: list[str] = []


class UpdateResponse(BaseModel):
    project_name: str
    added: int
    updated: int
    deleted: int
    unchanged: int
    last_updated: datetime


class ProjectStatusResponse(BaseModel):
    project_name: str
    root_memory_id: str | None = None
    agent_id: str | None = None
    file_count: int = 0
    ingested_at: str | None = None
    last_updated: str | None = None
    memory_count: int = 0


class LearnRequest(BaseModel):
    agent_id: uuid.UUID


class LearnResponse(BaseModel):
    agent_id: uuid.UUID
    synthesis_memory_id: uuid.UUID
    files_learned: int
    core_files: list[str]
    entry_points: list[str]
    causal_depth_of_understanding: int


# ── internal file-metadata container ──────────────────────────────────────────


class _FileMeta:
    __slots__ = (
        "file_path",
        "file_type",
        "line_count",
        "imports",
        "exports",
        "last_modified",
        "content",
    )

    def __init__(
        self,
        file_path: str,
        file_type: str,
        line_count: int,
        imports: list[str],
        exports: list[str],
        last_modified: str,
        content: str,
    ) -> None:
        self.file_path = file_path
        self.file_type = file_type
        self.line_count = line_count
        self.imports = imports
        self.exports = exports
        self.last_modified = last_modified
        self.content = content


# ── parsing helpers ────────────────────────────────────────────────────────────


def _parse_imports(content: str, file_type: str) -> list[str]:
    if file_type == ".py":
        result: list[str] = []
        for m in _PY_IMPORT.finditer(content):
            if m.group(1):
                result.append(m.group(1))
            elif m.group(2):
                for part in m.group(2).split(","):
                    name = part.strip().split()[0] if part.strip() else ""
                    if name:
                        result.append(name)
        return result
    if file_type in (".ts", ".tsx", ".js", ".jsx"):
        return _TS_IMPORT.findall(content)
    return []


def _parse_exports(content: str, file_type: str) -> list[str]:
    if file_type == ".py":
        return _PY_EXPORT.findall(content)
    if file_type in (".ts", ".tsx", ".js", ".jsx"):
        return _TS_EXPORT.findall(content)
    return []


def _resolve_import(
    importer: str,
    import_str: str,
    file_type: str,
    all_paths: set[str],
) -> str | None:
    """Map an import string to a relative file path present in the project."""
    if file_type == ".py":
        candidate = import_str.replace(".", "/") + ".py"
        if candidate in all_paths:
            return candidate
        init_candidate = import_str.replace(".", "/") + "/__init__.py"
        if init_candidate in all_paths:
            return init_candidate
        return None
    if file_type in (".ts", ".tsx", ".js", ".jsx"):
        if not import_str.startswith("."):
            return None
        base_dir = os.path.dirname(importer)
        resolved = os.path.normpath(os.path.join(base_dir, import_str)).replace("\\", "/")
        for ext in (".ts", ".tsx", ".js", ".jsx"):
            if resolved + ext in all_paths:
                return resolved + ext
        for idx in ("/index.ts", "/index.tsx", "/index.js", "/index.jsx"):
            if resolved + idx in all_paths:
                return resolved + idx
        if resolved in all_paths:
            return resolved
        return None
    return None


# ── directory tree ─────────────────────────────────────────────────────────────


def _build_tree(relative_paths: list[str]) -> str:
    tree: dict[str, Any] = {}
    for p in sorted(relative_paths):
        parts = p.replace("\\", "/").split("/")
        node = tree
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = None

    def _render(node: dict[str, Any], indent: int = 0) -> list[str]:
        lines: list[str] = []
        for name, child in sorted(node.items()):
            prefix = "  " * indent
            if child is None:
                lines.append(f"{prefix}{name}")
            else:
                lines.append(f"{prefix}{name}/")
                lines.extend(_render(child, indent + 1))
        return lines

    return "\n".join(_render(tree))


# ── misc helpers ───────────────────────────────────────────────────────────────


def _ctx_hash(project_name: str, file_path: str) -> str:
    return hashlib.sha256(f"{project_name}{file_path}".encode()).hexdigest()


def _walk_project(project_path: str, extensions: frozenset[str]) -> list[_FileMeta]:
    files: list[_FileMeta] = []
    for root, dirs, filenames in os.walk(project_path):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS and not d.startswith(".")]
        for fname in filenames:
            _, ext = os.path.splitext(fname)
            if ext not in extensions:
                continue
            abs_path = os.path.join(root, fname)
            rel_path = os.path.relpath(abs_path, project_path).replace("\\", "/")
            try:
                with open(abs_path, encoding="utf-8", errors="replace") as fh:
                    content = fh.read()
                mtime = datetime.fromtimestamp(
                    os.path.getmtime(abs_path), tz=timezone.utc
                ).isoformat()
                files.append(
                    _FileMeta(
                        file_path=rel_path,
                        file_type=ext,
                        line_count=content.count("\n") + 1,
                        imports=_parse_imports(content, ext),
                        exports=_parse_exports(content, ext),
                        last_modified=mtime,
                        content=content,
                    )
                )
            except OSError:
                continue
    return files


async def _write_memory_direct(
    db: AsyncSession,
    redis: Redis,
    agent_id: uuid.UUID,
    content: str,
    source_identifier: str,
    safety_context: dict[str, Any],
    causal_parents: list[str],
    causal_depth: int,
) -> Memory:
    """Insert a Memory row directly, bypassing agent behavioural checks."""
    mem = Memory(
        content=content,
        agent_id=agent_id,
        source_type="tool_call",
        source_identifier=source_identifier,
        safety_context=safety_context,
        memory_state="active",
        reality_score=float(safety_context.get("reality_score", 1.0)),
    )
    db.add(mem)
    await db.flush()

    mem.content_hash = compute_content_hash(
        {
            "content": mem.content,
            "agent_id": mem.agent_id,
            "session_id": None,
            "source_type": mem.source_type,
            "source_identifier": mem.source_identifier,
            "created_at": mem.created_at,
        }
    )
    mem.content_hash_valid = True

    clock = await increment_clock(str(agent_id), redis)
    mem.causal_parents = causal_parents
    mem.vector_clock = clock
    mem.causal_depth = causal_depth

    await log_memory_event(
        db,
        memory_id=mem.id,
        event_type="write",
        performed_by_agent_id=agent_id,
        event_metadata={
            "source_type": "tool_call",
            "source_identifier": source_identifier,
        },
    )
    return mem


# ── endpoints ──────────────────────────────────────────────────────────────────


@router.post("/ingest", response_model=IngestResponse, status_code=status.HTTP_201_CREATED)
async def ingest_project(
    body: IngestRequest,
    db: AsyncSession = Depends(get_db),
) -> IngestResponse:
    agent_r = await db.execute(select(Agent).where(Agent.id == body.agent_id))
    if agent_r.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")

    if not os.path.isdir(body.project_path):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="project_path is not a valid directory",
        )

    extensions: frozenset[str] = (
        frozenset(body.file_extensions) if body.file_extensions else _DEFAULT_EXTENSIONS
    )
    ingested_at = datetime.now(timezone.utc)
    redis = await get_redis()

    # Step 1: Walk directory tree
    file_metas = _walk_project(body.project_path, extensions)
    file_count = len(file_metas)
    all_paths = {m.file_path for m in file_metas}
    directory_tree = _build_tree([m.file_path for m in file_metas])

    # Step 4 (first because file_count is known): PROJECT ROOT memory
    root_content = (
        f"Project: {body.project_name}\n"
        f"Files: {file_count}\n"
        f"Structure:\n{directory_tree}"
    )
    root_safety: dict[str, Any] = {
        "reality_score": 1.0,
        "channel": "direct_observation",
        "cognitive_operations": ["project_scan"],
        "context_hash": _ctx_hash(body.project_name, ""),
        "project_name": body.project_name,
        "node_type": "project_root",
        "file_count": file_count,
    }
    root_mem = await _write_memory_direct(
        db,
        redis,
        agent_id=body.agent_id,
        content=root_content,
        source_identifier=f"project_ingest:{body.project_name}",
        safety_context=root_safety,
        causal_parents=[],
        causal_depth=0,
    )
    await db.commit()
    await db.refresh(root_mem)
    root_id = str(root_mem.id)

    # Step 2: Write each file as a memory
    path_to_mid: dict[str, str] = {}
    file_memory_objs: list[Memory] = []

    for meta in file_metas:
        mem_content = f"File: {meta.file_path}\n\n{meta.content[:2000]}"
        file_safety: dict[str, Any] = {
            "reality_score": 1.0,
            "channel": "direct_observation",
            "cognitive_operations": ["file_read", "import_parse"],
            "context_hash": _ctx_hash(body.project_name, meta.file_path),
            "project_name": body.project_name,
            "file_path": meta.file_path,
            "file_type": meta.file_type,
            "line_count": meta.line_count,
            "imports": meta.imports,
            "exports": meta.exports,
            "node_type": "project_file",
            "last_modified": meta.last_modified,
        }
        mem = await _write_memory_direct(
            db,
            redis,
            agent_id=body.agent_id,
            content=mem_content,
            source_identifier=f"project_ingest:{body.project_name}",
            safety_context=file_safety,
            causal_parents=[root_id],
            causal_depth=1,
        )
        path_to_mid[meta.file_path] = str(mem.id)
        file_memory_objs.append(mem)

    await db.commit()

    # Step 3: Add import-dependency causal edges
    edges_created = 0
    for i, meta in enumerate(file_metas):
        import_parent_ids: list[str] = []
        for imp in meta.imports:
            resolved = _resolve_import(meta.file_path, imp, meta.file_type, all_paths)
            if resolved and resolved in path_to_mid and resolved != meta.file_path:
                import_parent_ids.append(path_to_mid[resolved])
                edges_created += 1

        if import_parent_ids:
            mem = file_memory_objs[i]
            existing = list(mem.causal_parents or [])
            seen: set[str] = set(existing)
            for pid in import_parent_ids:
                if pid not in seen:
                    seen.add(pid)
                    existing.append(pid)
            mem.causal_parents = existing

    await db.commit()

    # Step 5: Store project registry in Redis (no TTL — persistent)
    registry: dict[str, Any] = {
        "root_memory_id": root_id,
        "agent_id": str(body.agent_id),
        "file_count": file_count,
        "ingested_at": ingested_at.isoformat(),
        "last_updated": ingested_at.isoformat(),
    }
    await redis.set(ns_key(f"project:{body.project_name}"), json.dumps(registry))

    return IngestResponse(
        project_name=body.project_name,
        root_memory_id=root_mem.id,
        files_ingested=file_count,
        edges_created=edges_created,
        agent_id=body.agent_id,
        ingested_at=ingested_at,
    )


@router.post("/update", response_model=UpdateResponse)
async def update_project(
    body: UpdateRequest,
    db: AsyncSession = Depends(get_db),
) -> UpdateResponse:
    redis = await get_redis()

    raw = await redis.get(ns_key(f"project:{body.project_name}"))
    if raw is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found — run POST /project/ingest first",
        )
    registry: dict[str, Any] = json.loads(raw)
    last_updated = datetime.fromisoformat(registry["last_updated"])

    if not os.path.isdir(body.project_path):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="project_path is not a valid directory",
        )

    extensions: frozenset[str] = (
        frozenset(body.file_extensions) if body.file_extensions else _DEFAULT_EXTENSIONS
    )
    file_metas = _walk_project(body.project_path, extensions)
    current_paths = {m.file_path for m in file_metas}

    existing_r = await db.execute(
        select(Memory).where(
            Memory.agent_id == body.agent_id,
            Memory.is_deleted.is_(False),
            Memory.safety_context["project_name"].astext == body.project_name,
            Memory.safety_context["node_type"].astext == "project_file",
        )
    )
    existing_memories = list(existing_r.scalars().all())
    existing_by_path: dict[str, Memory] = {
        (m.safety_context or {}).get("file_path", ""): m for m in existing_memories
    }

    added = updated = deleted = unchanged = 0
    now = datetime.now(timezone.utc)
    root_mid: str = registry.get("root_memory_id", "")

    for meta in file_metas:
        mem_content = f"File: {meta.file_path}\n\n{meta.content[:2000]}"
        file_mtime = datetime.fromisoformat(meta.last_modified)

        if meta.file_path in existing_by_path:
            existing_mem = existing_by_path[meta.file_path]
            if file_mtime > last_updated:
                new_safety = dict(existing_mem.safety_context or {})
                new_safety.update(
                    {
                        "line_count": meta.line_count,
                        "imports": meta.imports,
                        "exports": meta.exports,
                        "last_modified": meta.last_modified,
                    }
                )
                existing_mem.content = mem_content
                existing_mem.safety_context = new_safety
                await log_memory_event(
                    db,
                    memory_id=existing_mem.id,
                    event_type="write",
                    performed_by_agent_id=body.agent_id,
                    event_metadata={
                        "reason": "project_update",
                        "file_path": meta.file_path,
                    },
                )
                updated += 1
            else:
                unchanged += 1
        else:
            file_safety: dict[str, Any] = {
                "reality_score": 1.0,
                "channel": "direct_observation",
                "cognitive_operations": ["file_read", "import_parse"],
                "context_hash": _ctx_hash(body.project_name, meta.file_path),
                "project_name": body.project_name,
                "file_path": meta.file_path,
                "file_type": meta.file_type,
                "line_count": meta.line_count,
                "imports": meta.imports,
                "exports": meta.exports,
                "node_type": "project_file",
                "last_modified": meta.last_modified,
            }
            await _write_memory_direct(
                db,
                redis,
                agent_id=body.agent_id,
                content=mem_content,
                source_identifier=f"project_update:{body.project_name}",
                safety_context=file_safety,
                causal_parents=[root_mid] if root_mid else [],
                causal_depth=1,
            )
            added += 1

    for path, mem in existing_by_path.items():
        if path not in current_paths:
            mem.is_deleted = True
            await log_memory_event(
                db,
                memory_id=mem.id,
                event_type="deleted",
                performed_by_agent_id=body.agent_id,
                event_metadata={"reason": "file_removed_from_project"},
            )
            deleted += 1

    await db.commit()

    registry["last_updated"] = now.isoformat()
    registry["file_count"] = len(current_paths)
    await redis.set(ns_key(f"project:{body.project_name}"), json.dumps(registry))

    return UpdateResponse(
        project_name=body.project_name,
        added=added,
        updated=updated,
        deleted=deleted,
        unchanged=unchanged,
        last_updated=now,
    )


@router.get("/{project_name}/status", response_model=ProjectStatusResponse)
async def get_project_status(
    project_name: str,
    db: AsyncSession = Depends(get_db),
) -> ProjectStatusResponse:
    redis = await get_redis()
    raw = await redis.get(ns_key(f"project:{project_name}"))
    if raw is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )
    registry: dict[str, Any] = json.loads(raw)

    count_r = await db.execute(
        select(func.count())
        .select_from(Memory)
        .where(
            Memory.is_deleted.is_(False),
            Memory.safety_context["project_name"].astext == project_name,
        )
    )
    memory_count = int(count_r.scalar_one())

    return ProjectStatusResponse(
        project_name=project_name,
        root_memory_id=registry.get("root_memory_id"),
        agent_id=registry.get("agent_id"),
        file_count=int(registry.get("file_count", 0)),
        ingested_at=registry.get("ingested_at"),
        last_updated=registry.get("last_updated"),
        memory_count=memory_count,
    )


@router.post("/{project_name}/learn", response_model=LearnResponse, status_code=status.HTTP_201_CREATED)
async def learn_project(
    project_name: str,
    body: LearnRequest,
    db: AsyncSession = Depends(get_db),
) -> LearnResponse:
    agent_r = await db.execute(select(Agent).where(Agent.id == body.agent_id))
    if agent_r.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")

    redis = await get_redis()
    raw = await redis.get(ns_key(f"project:{project_name}"))
    if raw is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found — run POST /project/ingest first",
        )
    registry: dict[str, Any] = json.loads(raw)
    root_memory_id: str = registry.get("root_memory_id", "")

    # Step 1: Load all file memories for this project, shallowest first
    mems_r = await db.execute(
        select(Memory)
        .where(
            Memory.is_deleted.is_(False),
            Memory.safety_context["project_name"].astext == project_name,
            Memory.safety_context["node_type"].astext == "project_file",
        )
        .order_by(Memory.causal_depth.asc())
    )
    file_memories = list(mems_r.scalars().all())
    files_learned = len(file_memories)

    # Step 2: Build structured project summary
    dir_groups: dict[str, list[tuple[str, list[str]]]] = {}
    for mem in file_memories:
        sc = mem.safety_context or {}
        file_path = sc.get("file_path", "")
        exports: list[str] = sc.get("exports", [])
        directory = os.path.dirname(file_path) or "."
        dir_groups.setdefault(directory, []).append((file_path, exports))

    all_file_paths: dict[str, str] = {
        (m.safety_context or {}).get("file_path", ""): str(m.id) for m in file_memories
    }
    path_set = set(all_file_paths.keys())

    incoming_count: dict[str, int] = {fp: 0 for fp in path_set}
    import_graph: dict[str, list[str]] = {}

    for mem in file_memories:
        sc = mem.safety_context or {}
        file_path = sc.get("file_path", "")
        file_type = sc.get("file_type", ".py")
        raw_imports: list[str] = sc.get("imports", [])
        resolved: list[str] = []
        for imp in raw_imports:
            target = _resolve_import(file_path, imp, file_type, path_set)
            if target and target in path_set:
                resolved.append(target)
                incoming_count[target] = incoming_count.get(target, 0) + 1
        import_graph[file_path] = resolved

    entry_points = [fp for fp, cnt in incoming_count.items() if cnt == 0 and fp]
    core_files = [
        fp
        for fp, _ in sorted(
            ((fp, cnt) for fp, cnt in incoming_count.items() if cnt > 0),
            key=lambda x: x[1],
            reverse=True,
        )[:10]
    ]

    # Directory structure block
    dir_lines: list[str] = []
    for d in sorted(dir_groups.keys()):
        dir_lines.append(f"  {d}/")
        for fp, exports in sorted(dir_groups[d]):
            fname = os.path.basename(fp)
            export_str = ", ".join(exports[:5]) if exports else "(no exports)"
            dir_lines.append(f"    {fname}: {export_str}")
    dir_structure = "\n".join(dir_lines)

    # Key dependency lines
    dep_lines: list[str] = []
    for fp, imports in sorted(import_graph.items()):
        if imports:
            dep_lines.append(f"  {fp} → {', '.join(imports[:3])}")
    key_deps = "\n".join(dep_lines[:20]) if dep_lines else "  (none detected)"

    num_dirs = len(dir_groups)
    entry_point_str = entry_points[0] if entry_points else "(none)"

    synthesis_content = (
        f"PROJECT UNDERSTANDING: {project_name}\n\n"
        f"ENTRY POINTS: {', '.join(entry_points[:5]) or 'none'}\n"
        f"CORE FILES: {', '.join(core_files[:10]) or 'none'}\n"
        f"DIRECTORY STRUCTURE:\n{dir_structure}\n"
        f"KEY DEPENDENCIES:\n{key_deps}\n"
        f"TOTAL FILES: {files_learned} across {num_dirs} directories\n\n"
        f"TO UNDERSTAND THIS PROJECT START FROM: {entry_point_str}"
    )

    # Step 3: causal_parents = root + top-10 core file memories
    synthesis_parents: list[str] = [root_memory_id] if root_memory_id else []
    for fp in core_files[:10]:
        mid = all_file_paths.get(fp)
        if mid:
            synthesis_parents.append(mid)

    synthesis_depth = 2

    synthesis_safety: dict[str, Any] = {
        "reality_score": 1.0,
        "channel": "direct_observation",
        "cognitive_operations": ["project_analysis", "synthesis"],
        "context_hash": _ctx_hash(project_name, "synthesis"),
        "project_name": project_name,
        "node_type": "project_synthesis",
        "files_analyzed": files_learned,
        "core_files": core_files,
        "entry_points": entry_points,
    }

    synthesis_mem = await _write_memory_direct(
        db,
        redis,
        agent_id=body.agent_id,
        content=synthesis_content,
        source_identifier=f"project_learn:{project_name}",
        safety_context=synthesis_safety,
        causal_parents=synthesis_parents,
        causal_depth=synthesis_depth,
    )
    synthesis_mem.memory_state = "active"

    await db.commit()
    await db.refresh(synthesis_mem)

    # Step 4: Return learning summary
    return LearnResponse(
        agent_id=body.agent_id,
        synthesis_memory_id=synthesis_mem.id,
        files_learned=files_learned,
        core_files=core_files,
        entry_points=entry_points,
        causal_depth_of_understanding=synthesis_depth,
    )
