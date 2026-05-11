# RAG Ingestion and Retrieval

## 목적

RAG는 지원자가 제출한 자료를 근거로 프로젝트 수행 진위 검증 질문을 생성하기 위한 핵심 흐름이다. 목표는 단순히 파일 몇 개를 요약하는 것이 아니라, zip 내부 코드베이스와 프로젝트 문서를 함께 분석해 실제 구현자만 답하기 쉬운 질문 근거를 만드는 것이다.

질문 생성은 상위 N개 artifact 발췌나 파일 앞부분 요약에 의존하지 않는다. 코드 근거, 문서 근거, 문서-코드 alignment 근거를 함께 검색해 context pack으로 구성한다.

## Artifact role taxonomy

zip 내부 자료는 source type만으로 충분하지 않으므로 `artifact_role`을 함께 가진다.

| role | 의미 | 예시 |
|---|---|---|
| `codebase_source` | 실제 제품 코드 | `.py`, `.ts`, `.tsx`, `.js`, `.java`, `.kt`, `.go`, `.rs` |
| `codebase_test` | 테스트 코드 | `tests/`, `test_*.py`, `*.test.ts`, `*.spec.ts` |
| `codebase_config` | 실행·의존성·환경 설정 | `pyproject.toml`, `package.json`, `docker-compose.yml`, `.env.example`, `requirements.txt` |
| `codebase_api_spec` | API 명세 | `openapi.yaml`, `swagger.json`, `api.yaml` |
| `codebase_overview` | 코드베이스 설명 문서 | `README.md`, `CLAUDE.md`, `docs/*.md` |
| `project_report` | 제출 보고서 | `*.pdf` |
| `project_presentation` | 발표 자료 | `*.pptx` |
| `project_design_doc` | 설계 문서 | `*.docx` |
| `project_description` | 설명 텍스트 | 제출 설명 `.txt`, 설명용 markdown |
| `ignored` | 분석 제외 | build output, binary, cache, vendor directory |

경로만으로 애매한 경우에는 확장자, 상위 디렉터리, 파일명, 텍스트 앞부분의 키워드를 함께 사용한다.

## Role별 splitter 전략

### Code splitter

대상 role:

- `codebase_source`
- `codebase_test`

처리 방식:

- 파일마다 `file_manifest` chunk를 만든다.
- Python은 AST 기반으로 class, function, method 단위 chunk를 만든다.
- 다른 언어는 MVP에서 symbol regex scan과 generic code fallback으로 시작한다.
- 긴 symbol chunk는 내부 raw chunk로 재분할한다.
- 가능한 경우 `line_start`, `line_end`, `char_start`, `char_end`, `language`, `symbol_name`, `symbol_type`을 저장한다.

### Codebase overview / markdown splitter

대상 role:

- `codebase_overview`

처리 방식:

- markdown heading section 단위로 split한다.
- README와 docs는 코드베이스 구조, 실행 방법, 설계 의도를 설명하는 근거로 사용한다.
- 제출 보고서와 혼동하지 않도록 `artifact_role`로 구분한다.

### Project document splitter

대상 role:

- `project_report`
- `project_presentation`
- `project_design_doc`
- `project_description`

처리 방식:

- PDF는 page 단위 metadata와 semantic chunk를 우선한다.
- PPTX는 slide number, title, bullet group을 가능한 범위에서 보존한다.
- DOCX는 heading hierarchy와 paragraph 구조를 가능한 범위에서 보존한다.
- TXT/markdown 제출 문서는 section/paragraph 단위로 나눈다.
- extractor가 page/slide 정보를 아직 보존하지 못하면 path, role, section 기반 metadata로 시작하고 후속 개선 대상으로 남긴다.

### Structured config / spec splitter

대상 role:

- `codebase_config`
- `codebase_api_spec`

처리 방식:

- JSON/YAML/TOML은 section 또는 key path 중심으로 split한다.
- OpenAPI/Swagger는 path/method 단위 chunk를 만든다.
- config chunk는 의존성, 실행 방식, DB/API/LLM 설정 근거로 사용한다.

## Qdrant payload

Qdrant payload는 질문과 리포트에서 근거를 추적할 수 있어야 한다.

공통 payload 예시:

```json
{
  "evaluation_id": "eval_123",
  "artifact_id": "artifact_456",
  "source_path": "backend/app/main.py",
  "source_type": "code",
  "artifact_role": "codebase_source",
  "chunk_type": "code_symbol",
  "top_dir": "backend",
  "project_area": "backend_api",
  "content_hash": "sha256:synthetic",
  "text": "chunk text"
}
```

코드 chunk 추가 payload 예시:

```json
{
  "language": "python",
  "symbol_name": "generate_questions",
  "symbol_type": "function",
  "line_start": 42,
  "line_end": 88,
  "char_start": 1200,
  "char_end": 2800
}
```

문서 chunk 추가 payload 예시:

```json
{
  "page_number": 5,
  "slide_number": null,
  "section_title": "시스템 아키텍처"
}
```

## Retrieval query groups

질문 생성은 단일 query top-k에만 의존하지 않는다. 다음 목적별 query group을 사용한다.

1. 코드베이스 전체 구조와 주요 모듈
2. zip 업로드, 파일 추출, artifact 저장 흐름
3. RAG embedding, Qdrant ingest, retrieval 흐름
4. 질문 생성 LLM prompt와 context 구성 흐름
5. 답변 평가와 리포트 생성 흐름
6. 프로젝트 문서에서 주장한 목표, 아키텍처, 핵심 기능
7. 문서 주장과 실제 코드 구현이 만나는 지점
8. 예외 처리, 실패 가능성, TODO/FIXME, 트러블슈팅 지점

## Result diversity

검색 결과는 다양성을 유지해야 한다.

- 같은 `source_path`에서 너무 많은 chunk가 몰리지 않게 제한한다.
- code와 project document chunk를 모두 포함한다.
- `file_manifest`, `code_symbol`, `project_document_semantic`을 우선한다.
- raw chunk는 세부 근거로만 사용한다.
- score가 낮은 chunk는 제외한다.
- 질문별 source refs를 유지한다.

## Context pack format

질문 생성 LLM에는 다음 구조를 전달한다.

```text
[CODEBASE MAP]
- 디렉터리 구조
- 주요 모듈
- 핵심 파일
- 주요 symbol
- 설정/의존성

[PROJECT DOCUMENT EVIDENCE]
- 보고서에서 주장한 목적/기능/아키텍처
- 발표자료의 설계 설명
- 설계 문서의 기능 설명

[CODE EVIDENCE]
- 실제 구현 파일
- 관련 함수/클래스/설정
- 데이터 흐름

[DOCUMENT-CODE ALIGNMENT]
- 문서 주장과 코드 구현이 일치하는 지점
- 문서에는 있지만 코드 근거가 약한 지점
- 코드에는 있지만 문서 설명이 부족한 지점

[QUESTION GENERATION RULES]
- 실제 구현자만 답할 수 있는 질문 생성
- 파일 하나를 단독으로 설명하라는 질문 금지
- 코드와 문서 근거를 함께 사용
- 구현 흐름, 의사결정, 트러블슈팅, 한계 인식 포함
```

## Source refs

질문과 리포트에는 근거 추적을 위한 source refs를 유지한다.

예시:

```json
{
  "source_path": "docs/system-design.md",
  "artifact_role": "codebase_overview",
  "chunk_type": "markdown_section",
  "section_title": "RAG pipeline",
  "line_start": 10,
  "line_end": 38
}
```

source refs는 다음 용도로 사용한다.

- 질문 생성 근거 표시
- 답변 평가 근거 표시
- 문서-코드 불일치 지점 표시
- 추가 확인 질문 생성

## 실패 처리 원칙

- RAG index가 비어 있으면 질문 생성을 성공으로 처리하지 않는다.
- Qdrant ingest 실패는 조용히 무시하지 않는다.
- artifact는 존재하지만 chunk가 없으면 skipped reason을 남긴다.
- 실패 상태와 사용자 표시 방식은 `docs/api-and-job-flow.md`와 `docs/security-and-data-policy.md`를 따른다.
