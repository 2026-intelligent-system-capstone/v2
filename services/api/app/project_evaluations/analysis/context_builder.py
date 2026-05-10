from collections import Counter
from pathlib import PurePosixPath

from services.api.app.project_evaluations.analysis.llm_client import LlmClient
from services.api.app.project_evaluations.analysis.prompts import (
    ProjectContextSchema,
    build_context_prompt,
)
from services.api.app.project_evaluations.persistence.models import ProjectArtifactRow

ROOT_DOC_NAMES = {
    "claude.md",
    "readme.md",
    "pyproject.toml",
    "package.json",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "requirements.txt",
}

TECH_BY_EXTENSION = {
    ".py": "Python",
    ".js": "JavaScript",
    ".jsx": "React",
    ".ts": "TypeScript",
    ".tsx": "React/TypeScript",
    ".java": "Java",
    ".kt": "Kotlin",
    ".go": "Go",
    ".rs": "Rust",
    ".sql": "SQL",
    ".html": "HTML",
    ".css": "CSS",
    ".toml": "TOML 설정",
    ".yaml": "YAML 설정",
    ".yml": "YAML 설정",
    ".json": "JSON 설정",
}
RISK_KEYWORDS = ("TODO", "FIXME", "error", "exception", "security", "hack")


def build_project_context(
    artifacts: list[ProjectArtifactRow], llm: LlmClient | None = None
) -> dict[str, object]:
    extracted = [a for a in artifacts if a.raw_text.strip()]
    if llm and llm.enabled():
        try:
            return _build_with_llm(extracted, llm)
        except Exception:
            pass
    return _build_rule_based(extracted)


def _build_with_llm(
    artifacts: list[ProjectArtifactRow], llm: LlmClient
) -> dict[str, object]:
    snippets = [f"[{a.source_path}]\n{a.raw_text[:1500]}" for a in artifacts[:20]]
    messages = build_context_prompt(snippets)
    result: ProjectContextSchema = llm.parse(messages, ProjectContextSchema, max_tokens=4000)
    areas = [
        {
            "name": area.name,
            "summary": area.summary,
            "confidence": area.confidence,
            "source_refs": _match_source_refs(area.name, artifacts),
        }
        for area in result.areas
    ]
    return {
        "summary": result.summary,
        "tech_stack": result.tech_stack,
        "features": result.features,
        "architecture_notes": result.architecture_notes,
        "data_flow": result.data_flow,
        "risk_points": result.risk_points,
        "question_targets": result.question_targets,
        "areas": areas,
    }


def _match_source_refs(area_name: str, artifacts: list[ProjectArtifactRow]) -> list[dict]:
    keyword = area_name.lower()
    matched = [
        a
        for a in artifacts
        if keyword in a.source_path.lower() or keyword in a.raw_text.lower()[:500]
    ]
    return [
        {
            "path": a.source_path,
            "snippet": _normalize(a.raw_text)[:200],
            "artifact_id": a.id,
        }
        for a in matched[:3]
    ]


def _build_rule_based(artifacts: list[ProjectArtifactRow]) -> dict[str, object]:
    summary = _build_summary(artifacts)
    tech_stack = _infer_tech_stack(artifacts)
    features = _infer_features(artifacts)
    architecture_notes = _infer_architecture(artifacts)
    data_flow = _infer_data_flow(artifacts)
    risk_points = _infer_risk_points(artifacts)
    areas = _infer_project_areas(artifacts)
    question_targets = [area["name"] for area in areas]
    return {
        "summary": summary,
        "tech_stack": tech_stack,
        "features": features,
        "architecture_notes": architecture_notes,
        "data_flow": data_flow,
        "risk_points": risk_points,
        "question_targets": question_targets,
        "areas": areas,
    }


def _build_summary(artifacts: list[ProjectArtifactRow]) -> str:
    preferred = sorted(
        artifacts,
        key=lambda item: (
            "readme" not in item.source_path.lower(),
            item.source_type != "document",
            item.source_path,
        ),
    )
    snippets = []
    for artifact in preferred[:3]:
        text = _normalize(artifact.raw_text)[:700]
        if text:
            snippets.append(f"{artifact.source_path}: {text}")
    if not snippets:
        return "업로드된 자료에서 추출 가능한 텍스트가 거의 없습니다."
    return "\n\n".join(snippets)


def _infer_tech_stack(artifacts: list[ProjectArtifactRow]) -> list[str]:
    found = []
    lowered_text = "\n".join(a.raw_text.lower()[:2000] for a in artifacts)
    for artifact in artifacts:
        suffix = PurePosixPath(artifact.source_path).suffix.lower()
        if suffix in TECH_BY_EXTENSION:
            found.append(TECH_BY_EXTENSION[suffix])
    keyword_map = {
        "fastapi": "FastAPI",
        "streamlit": "Streamlit",
        "sqlite": "SQLite",
        "react": "React",
        "next.js": "Next.js",
        "qdrant": "Qdrant",
        "openai": "OpenAI API",
        "sqlalchemy": "SQLAlchemy",
    }
    for keyword, label in keyword_map.items():
        if keyword in lowered_text:
            found.append(label)
    return sorted(set(found))[:12]


def _infer_features(artifacts: list[ProjectArtifactRow]) -> list[str]:
    candidates = []
    for artifact in artifacts:
        path = PurePosixPath(artifact.source_path)
        if path.stem.lower() in {"readme", "requirements", "pyproject", "package"}:
            continue
        if len(path.parts) > 1:
            candidates.append(path.parts[0])
        candidates.append(path.stem.replace("_", " ").replace("-", " "))
    counter = Counter(item for item in candidates if item and len(item) > 2)
    return [name for name, _ in counter.most_common(8)]


def _infer_architecture(artifacts: list[ProjectArtifactRow]) -> list[str]:
    top_dirs = Counter(
        PurePosixPath(a.source_path).parts[0]
        for a in artifacts
        if len(PurePosixPath(a.source_path).parts) > 1
    )
    notes = [
        f"`{name}/` 디렉터리에 주요 코드가 집중되어 있습니다."
        for name, _ in top_dirs.most_common(5)
    ]
    if any("api" in a.source_path.lower() for a in artifacts):
        notes.append("API 계층으로 보이는 파일이 포함되어 있습니다.")
    if any("test" in a.source_path.lower() for a in artifacts):
        notes.append("테스트 또는 검증 관련 파일이 포함되어 있습니다.")
    return notes


def _infer_data_flow(artifacts: list[ProjectArtifactRow]) -> list[str]:
    flow = []
    if any("upload" in a.raw_text.lower() for a in artifacts):
        flow.append("업로드 입력을 처리하는 흐름이 자료에 나타납니다.")
    if any(
        "database" in a.raw_text.lower() or "sql" in a.source_path.lower()
        for a in artifacts
    ):
        flow.append("데이터 저장소와 연결되는 흐름이 자료에 나타납니다.")
    if any("report" in a.raw_text.lower() for a in artifacts):
        flow.append("분석 결과를 리포트로 생성하는 흐름이 자료에 나타납니다.")
    return flow or ["파일 구조와 문서 설명을 기반으로 세부 데이터 흐름 확인이 필요합니다."]


def _infer_risk_points(artifacts: list[ProjectArtifactRow]) -> list[str]:
    risks = []
    for artifact in artifacts:
        text = artifact.raw_text
        for keyword in RISK_KEYWORDS:
            if keyword.lower() in text.lower():
                risks.append(
                    f"{artifact.source_path}에서 `{keyword}` 관련 확인 지점이 발견되었습니다."
                )
                break
    return risks[:8]


def _infer_project_areas(
    artifacts: list[ProjectArtifactRow],
) -> list[dict[str, object]]:
    groups: dict[str, list[ProjectArtifactRow]] = {}
    root_docs: list[ProjectArtifactRow] = []
    for artifact in artifacts:
        area_name = _area_name_for_path(artifact.source_path)
        if area_name is None:
            root_docs.append(artifact)
            continue
        groups.setdefault(area_name, []).append(artifact)

    if root_docs and groups:
        for index, artifact in enumerate(root_docs):
            target_name = sorted(groups, key=lambda name: len(groups[name]), reverse=True)[
                index % len(groups)
            ]
            groups[target_name].append(artifact)
    elif root_docs:
        groups["project-docs"] = root_docs

    areas = []
    for name, items in sorted(
        groups.items(), key=lambda p: (_code_count(p[1]), len(p[1])), reverse=True
    )[:6]:
        refs = sorted(items, key=lambda item: _source_ref_priority(item.source_path))[:3]
        paths = [item.source_path for item in refs]
        areas.append(
            {
                "name": name,
                "summary": (
                    f"{len(items)}개 파일이 연결된 `{name}` 영역입니다."
                    f" 대표 파일: {', '.join(paths)}"
                ),
                "confidence": min(0.95, 0.45 + len(items) * 0.08),
                "source_refs": [
                    {
                        "path": item.source_path,
                        "snippet": _normalize(item.raw_text)[:240],
                        "artifact_id": item.id,
                    }
                    for item in refs
                ],
            }
        )
    return areas or [
        {
            "name": "project",
            "summary": "업로드된 자료 전체를 하나의 프로젝트 영역으로 분석합니다.",
            "confidence": 0.4,
            "source_refs": [],
        }
    ]


def _area_name_for_path(source_path: str) -> str | None:
    path = PurePosixPath(source_path)
    parts = [part for part in path.parts if part]
    if not parts:
        return None
    if len(parts) == 1 and parts[0].lower() in ROOT_DOC_NAMES:
        return None
    cleaned = parts[1:] if parts[0].lower() in {"tests", "test"} and len(parts) > 1 else parts
    if len(cleaned) >= 3 and cleaned[1].lower() in {"modules", "features", "domains"}:
        return "/".join(cleaned[:3])
    if len(cleaned) >= 2 and cleaned[0].lower() in {"app", "src", "services", "apps"}:
        return "/".join(cleaned[:2])
    if len(cleaned) >= 2:
        return "/".join(cleaned[:2])
    stem = PurePosixPath(cleaned[0]).stem
    return None if stem.lower() in {"claude", "readme", "pyproject"} else stem


def _code_count(items: list[ProjectArtifactRow]) -> int:
    return sum(1 for item in items if item.source_type == "code")


def _source_ref_priority(source_path: str) -> tuple[int, str]:
    path = PurePosixPath(source_path)
    is_root_doc = len(path.parts) == 1 and path.name.lower() in ROOT_DOC_NAMES
    return (1 if is_root_doc else 0, source_path)


def _normalize(value: str) -> str:
    return " ".join(value.split())
