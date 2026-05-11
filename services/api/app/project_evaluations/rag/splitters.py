from __future__ import annotations

import ast
import hashlib
import json
import re
from collections.abc import Iterable
from pathlib import PurePosixPath

from services.api.app.project_evaluations.domain.models import ArtifactRole
from services.api.app.project_evaluations.rag.chunk_models import ChunkRecord, ChunkType

MAX_CHUNK_CHARS = 1_600
CHUNK_OVERLAP = 180
CODE_SYMBOL_PATTERN = re.compile(
    r"^\s*(?:export\s+)?(?:async\s+)?(?:function|class|interface|type|const|let|var)\s+([A-Za-z_$][\w$]*)",
    re.MULTILINE,
)
MARKER_PATTERN = re.compile(r"^\[(page|slide)\s+(\d+)\]\s*$", re.MULTILINE | re.IGNORECASE)
HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)


def split_artifact(evaluation_id: str, artifact: object) -> list[ChunkRecord]:
    raw_text = str(getattr(artifact, "raw_text", ""))
    if not raw_text.strip():
        return []

    metadata = _metadata(artifact)
    role = _artifact_role(metadata, str(getattr(artifact, "source_type", "")))
    language = _optional_str(metadata.get("language"))
    base = _base_fields(evaluation_id, artifact, role, language)

    if role in {ArtifactRole.CODEBASE_SOURCE.value, ArtifactRole.CODEBASE_TEST.value}:
        return _split_code(raw_text, base, language)
    if role in {ArtifactRole.CODEBASE_CONFIG.value, ArtifactRole.CODEBASE_API_SPEC.value}:
        return _split_structured(raw_text, base, language)
    if role == ArtifactRole.CODEBASE_OVERVIEW.value:
        return _split_markdown(raw_text, base, ChunkType.CODEBASE_OVERVIEW)
    if role in {
        ArtifactRole.PROJECT_REPORT.value,
        ArtifactRole.PROJECT_PRESENTATION.value,
        ArtifactRole.PROJECT_DESIGN_DOC.value,
        ArtifactRole.PROJECT_DESCRIPTION.value,
    }:
        return _split_project_document(raw_text, base)
    return []


def _split_code(
    text: str, base: dict[str, object], language: str | None
) -> list[ChunkRecord]:
    chunks = [
        _make_chunk(
            text=_file_manifest(text, base, language),
            base=base,
            chunk_type=ChunkType.FILE_MANIFEST,
            chunk_index=0,
        )
    ]
    symbol_chunks = _python_symbol_chunks(text, base) if language == "python" else _generic_symbol_chunks(text, base)
    chunks.extend(_with_indexes(symbol_chunks, start_index=len(chunks)))
    if len(chunks) == 1:
        chunks.extend(_raw_chunks(text, base, ChunkType.CODE_RAW, len(chunks)))
    return chunks


def _split_structured(
    text: str, base: dict[str, object], language: str | None
) -> list[ChunkRecord]:
    if language == "json":
        json_chunks = _json_section_chunks(text, base)
        if json_chunks:
            return _with_indexes(json_chunks, start_index=0)
    return _split_markdown(text, base, ChunkType.STRUCTURED_CONFIG)


def _split_project_document(text: str, base: dict[str, object]) -> list[ChunkRecord]:
    marked_sections = _marker_sections(text)
    if marked_sections:
        chunks: list[ChunkRecord] = []
        for section_text, start, _end, marker_type, marker_number in marked_sections:
            for part, part_start, part_end in _recursive_chunks(section_text):
                marker_kwargs = (
                    {"page_number": marker_number}
                    if marker_type == "page"
                    else {"slide_number": marker_number}
                )
                chunks.append(
                    _make_chunk(
                        text=part,
                        base=base,
                        chunk_type=ChunkType.PROJECT_DOCUMENT,
                        chunk_index=0,
                        char_start=start + part_start,
                        char_end=start + part_end,
                        **marker_kwargs,
                    )
                )
        return _with_indexes(chunks, start_index=0)
    return _split_markdown(text, base, ChunkType.PROJECT_DOCUMENT)


def _split_markdown(
    text: str, base: dict[str, object], chunk_type: ChunkType
) -> list[ChunkRecord]:
    sections = _heading_sections(text)
    chunks: list[ChunkRecord] = []
    if sections:
        for title, section_text, start, _end in sections:
            for part, part_start, part_end in _recursive_chunks(section_text):
                chunks.append(
                    _make_chunk(
                        text=part,
                        base=base,
                        chunk_type=chunk_type,
                        chunk_index=0,
                        char_start=start + part_start,
                        char_end=start + part_end,
                        section_title=title,
                    )
                )
    else:
        chunks.extend(_raw_chunks(text, base, chunk_type, 0))
    return _with_indexes(chunks, start_index=0)


def _python_symbol_chunks(text: str, base: dict[str, object]) -> list[ChunkRecord]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []

    chunks = []
    for node in tree.body:
        if not isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        line_start = node.lineno
        line_end = getattr(node, "end_lineno", node.lineno)
        char_start = _line_to_offset(text, line_start)
        char_end = _line_to_offset(text, line_end + 1)
        symbol_text = text[char_start:char_end].strip()
        if not symbol_text:
            continue
        symbol_type = "class" if isinstance(node, ast.ClassDef) else "function"
        chunks.append(
            _make_chunk(
                text=symbol_text,
                base=base,
                chunk_type=ChunkType.CODE_SYMBOL,
                chunk_index=0,
                symbol_name=node.name,
                symbol_type=symbol_type,
                line_start=line_start,
                line_end=line_end,
                char_start=char_start,
                char_end=char_end,
            )
        )
    return chunks


def _generic_symbol_chunks(text: str, base: dict[str, object]) -> list[ChunkRecord]:
    matches = list(CODE_SYMBOL_PATTERN.finditer(text))
    chunks = []
    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else min(len(text), start + MAX_CHUNK_CHARS)
        symbol_text = text[start:end].strip()
        if not symbol_text:
            continue
        line_start = text.count("\n", 0, start) + 1
        line_end = text.count("\n", 0, end) + 1
        chunks.append(
            _make_chunk(
                text=symbol_text,
                base=base,
                chunk_type=ChunkType.CODE_SYMBOL,
                chunk_index=0,
                symbol_name=match.group(1),
                symbol_type="symbol",
                line_start=line_start,
                line_end=line_end,
                char_start=start,
                char_end=end,
            )
        )
    return chunks


def _json_section_chunks(text: str, base: dict[str, object]) -> list[ChunkRecord]:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, dict):
        return []
    chunks = []
    for key, value in parsed.items():
        section_text = json.dumps({key: value}, ensure_ascii=False, indent=2)
        chunks.append(
            _make_chunk(
                text=section_text,
                base=base,
                chunk_type=ChunkType.STRUCTURED_CONFIG,
                chunk_index=0,
                section_title=str(key),
            )
        )
    return chunks


def _raw_chunks(
    text: str, base: dict[str, object], chunk_type: ChunkType, start_index: int
) -> list[ChunkRecord]:
    return _with_indexes(
        [
            _make_chunk(
                text=part,
                base=base,
                chunk_type=chunk_type,
                chunk_index=0,
                char_start=start,
                char_end=end,
                line_start=text.count("\n", 0, start) + 1,
                line_end=text.count("\n", 0, end) + 1,
            )
            for part, start, end in _recursive_chunks(text)
        ],
        start_index=start_index,
    )


def _recursive_chunks(text: str) -> list[tuple[str, int, int]]:
    normalized = text.strip()
    if not normalized:
        return []
    if len(normalized) <= MAX_CHUNK_CHARS:
        start = text.find(normalized)
        return [(normalized, max(0, start), max(0, start) + len(normalized))]

    chunks: list[tuple[str, int, int]] = []
    start = 0
    while start < len(text):
        limit = min(len(text), start + MAX_CHUNK_CHARS)
        split_at = _best_split(text, start, limit)
        part = text[start:split_at].strip()
        if part:
            part_start = text.find(part, start, split_at)
            chunks.append((part, part_start, part_start + len(part)))
        if split_at >= len(text):
            break
        start = max(split_at - CHUNK_OVERLAP, start + 1)
    return chunks


def _best_split(text: str, start: int, limit: int) -> int:
    for separator in ("\n\n", "\n", ". ", " "):
        index = text.rfind(separator, start, limit)
        if index > start + MAX_CHUNK_CHARS // 2:
            return index + len(separator)
    return limit


def _heading_sections(text: str) -> list[tuple[str | None, str, int, int]]:
    matches = list(HEADING_PATTERN.finditer(text))
    if not matches:
        return []
    sections = []
    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        sections.append((match.group(2).strip(), text[start:end], start, end))
    return sections


def _marker_sections(text: str) -> list[tuple[str, int, int, str, int]]:
    matches = list(MARKER_PATTERN.finditer(text))
    sections = []
    for index, match in enumerate(matches):
        content_start = match.end()
        content_end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        content = text[content_start:content_end].strip()
        if content:
            sections.append((content, content_start, content_end, match.group(1).lower(), int(match.group(2))))
    return sections


def _file_manifest(text: str, base: dict[str, object], language: str | None) -> str:
    source_path = str(base["source_path"])
    symbols = _symbol_names(text, language)
    symbol_text = ", ".join(symbols[:20]) if symbols else "감지된 top-level symbol 없음"
    return (
        f"File: {source_path}\n"
        f"Role: {base['artifact_role']}\n"
        f"Language: {language or 'unknown'}\n"
        f"Project area: {base['project_area'] or 'project'}\n"
        f"Top-level symbols: {symbol_text}"
    )


def _symbol_names(text: str, language: str | None) -> list[str]:
    if language == "python":
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return []
        return [
            node.name
            for node in tree.body
            if isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
        ]
    return [match.group(1) for match in CODE_SYMBOL_PATTERN.finditer(text)]


def _base_fields(
    evaluation_id: str, artifact: object, role: str, language: str | None
) -> dict[str, object]:
    source_path = str(getattr(artifact, "source_path"))
    path = PurePosixPath(source_path)
    top_dir = path.parts[0] if path.parts else None
    return {
        "evaluation_id": evaluation_id,
        "artifact_id": str(getattr(artifact, "id")),
        "source_path": source_path,
        "source_type": str(getattr(artifact, "source_type", "")),
        "artifact_role": role,
        "language": language,
        "top_dir": top_dir,
        "project_area": _project_area(path),
    }


def _make_chunk(
    text: str,
    base: dict[str, object],
    chunk_type: ChunkType,
    chunk_index: int,
    **kwargs: object,
) -> ChunkRecord:
    cleaned = text.strip()
    return ChunkRecord(
        text=cleaned,
        evaluation_id=str(base["evaluation_id"]),
        artifact_id=str(base["artifact_id"]),
        source_path=str(base["source_path"]),
        source_type=str(base["source_type"]),
        artifact_role=str(base["artifact_role"]),
        chunk_type=chunk_type,
        chunk_index=chunk_index,
        content_hash=_hash_text(str(base["source_path"]), cleaned),
        language=_optional_str(base.get("language")),
        top_dir=_optional_str(base.get("top_dir")),
        project_area=_optional_str(base.get("project_area")),
        symbol_name=_optional_str(kwargs.get("symbol_name")),
        symbol_type=_optional_str(kwargs.get("symbol_type")),
        line_start=_optional_int(kwargs.get("line_start")),
        line_end=_optional_int(kwargs.get("line_end")),
        char_start=_optional_int(kwargs.get("char_start")),
        char_end=_optional_int(kwargs.get("char_end")),
        page_number=_optional_int(kwargs.get("page_number")),
        slide_number=_optional_int(kwargs.get("slide_number")),
        section_title=_optional_str(kwargs.get("section_title")),
    )


def _with_indexes(chunks: Iterable[ChunkRecord], start_index: int) -> list[ChunkRecord]:
    indexed = []
    for offset, chunk in enumerate(chunks, start=start_index):
        indexed.append(
            ChunkRecord(
                text=chunk.text,
                evaluation_id=chunk.evaluation_id,
                artifact_id=chunk.artifact_id,
                source_path=chunk.source_path,
                source_type=chunk.source_type,
                artifact_role=chunk.artifact_role,
                chunk_type=chunk.chunk_type,
                chunk_index=offset,
                content_hash=chunk.content_hash,
                language=chunk.language,
                top_dir=chunk.top_dir,
                project_area=chunk.project_area,
                symbol_name=chunk.symbol_name,
                symbol_type=chunk.symbol_type,
                line_start=chunk.line_start,
                line_end=chunk.line_end,
                char_start=chunk.char_start,
                char_end=chunk.char_end,
                page_number=chunk.page_number,
                slide_number=chunk.slide_number,
                section_title=chunk.section_title,
            )
        )
    return indexed


def _artifact_role(metadata: dict[str, object], source_type: str) -> str:
    role = metadata.get("artifact_role")
    if role:
        return str(role)
    if source_type == "code":
        return ArtifactRole.CODEBASE_SOURCE.value
    if source_type == "document":
        return ArtifactRole.PROJECT_DESCRIPTION.value
    return ArtifactRole.IGNORED.value


def _metadata(artifact: object) -> dict[str, object]:
    raw = getattr(artifact, "metadata_json", "{}")
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw or "{}")
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _project_area(path: PurePosixPath) -> str | None:
    parts = [part for part in path.parts if part]
    if len(parts) >= 3 and parts[0] in {"apps", "services", "src", "app"}:
        return "/".join(parts[:3])
    if len(parts) >= 2:
        return "/".join(parts[:2])
    return path.stem if path.stem else None


def _line_to_offset(text: str, line_number: int) -> int:
    if line_number <= 1:
        return 0
    current_line = 1
    for index, char in enumerate(text):
        if char == "\n":
            current_line += 1
            if current_line == line_number:
                return index + 1
    return len(text)


def _hash_text(source_path: str, text: str) -> str:
    return hashlib.sha256(f"{source_path}\n{text}".encode("utf-8")).hexdigest()


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _optional_int(value: object) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None
