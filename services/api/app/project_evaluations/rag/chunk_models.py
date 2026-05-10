from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class ChunkType(StrEnum):
    FILE_MANIFEST = "file_manifest"
    CODE_SYMBOL = "code_symbol"
    CODE_RAW = "code_raw"
    CODEBASE_OVERVIEW = "codebase_overview"
    STRUCTURED_CONFIG = "structured_config"
    PROJECT_DOCUMENT = "project_document_semantic"
    PROJECT_DOCUMENT_RAW = "project_document_raw"


@dataclass(frozen=True)
class ChunkRecord:
    text: str
    evaluation_id: str
    artifact_id: str
    source_path: str
    source_type: str
    artifact_role: str
    chunk_type: ChunkType
    chunk_index: int
    content_hash: str
    language: str | None = None
    top_dir: str | None = None
    project_area: str | None = None
    symbol_name: str | None = None
    symbol_type: str | None = None
    line_start: int | None = None
    line_end: int | None = None
    char_start: int | None = None
    char_end: int | None = None
    page_number: int | None = None
    slide_number: int | None = None
    section_title: str | None = None

    def payload(self) -> dict[str, object]:
        return {
            "text": self.text,
            "evaluation_id": self.evaluation_id,
            "artifact_id": self.artifact_id,
            "source_path": self.source_path,
            "source_type": self.source_type,
            "artifact_role": self.artifact_role,
            "chunk_type": self.chunk_type.value,
            "chunk_index": self.chunk_index,
            "content_hash": self.content_hash,
            "language": self.language,
            "top_dir": self.top_dir,
            "project_area": self.project_area,
            "symbol_name": self.symbol_name,
            "symbol_type": self.symbol_type,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "char_start": self.char_start,
            "char_end": self.char_end,
            "page_number": self.page_number,
            "slide_number": self.slide_number,
            "section_title": self.section_title,
        }


@dataclass(frozen=True)
class RetrievedChunk:
    text: str
    source_path: str
    artifact_id: str | None
    source_type: str | None
    artifact_role: str | None
    chunk_type: str | None
    score: float | None = None
    line_start: int | None = None
    line_end: int | None = None
    page_number: int | None = None
    slide_number: int | None = None
    section_title: str | None = None
    symbol_name: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)

    @classmethod
    def from_payload(
        cls, payload: dict[str, object], score: float | None = None
    ) -> RetrievedChunk:
        return cls(
            text=str(payload.get("text", "")),
            source_path=str(payload.get("source_path", "")),
            artifact_id=_optional_str(payload.get("artifact_id")),
            source_type=_optional_str(payload.get("source_type")),
            artifact_role=_optional_str(payload.get("artifact_role")),
            chunk_type=_optional_str(payload.get("chunk_type")),
            score=score,
            line_start=_optional_int(payload.get("line_start")),
            line_end=_optional_int(payload.get("line_end")),
            page_number=_optional_int(payload.get("page_number")),
            slide_number=_optional_int(payload.get("slide_number")),
            section_title=_optional_str(payload.get("section_title")),
            symbol_name=_optional_str(payload.get("symbol_name")),
            metadata=payload,
        )

    def source_label(self) -> str:
        suffix = ""
        if self.line_start and self.line_end:
            suffix = f":L{self.line_start}-L{self.line_end}"
        elif self.page_number:
            suffix = f":page {self.page_number}"
        elif self.slide_number:
            suffix = f":slide {self.slide_number}"
        return f"{self.source_path}{suffix}"


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
