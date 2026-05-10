# FastAPI + Streamlit 프로젝트 수행 진위 평가 서비스

## Problem Statement

캡스톤 프로젝트 과제를 평가하는 교수는 학생이 제출한 프로젝트를 실제로 수행했는지 확인하기 어렵다. 현재 방식은 코드를 직접 읽고, 문서를 대조하고, 학생에게 구두 질문을 반복해야 하므로 평가 시간이 길고 평가자의 주관이 개입되기 쉽다.

## Evidence

- 사용자 관찰: “학생이 프로젝트를 진짜 했는지 알기 힘들다.”
- 사용자 관찰: “프로젝트의 코드를 전부 읽어봐야 하고, 코드를 분석해야 하며, 학생에게 질문하는 총 평가 과정이 너무 오래 걸린다.”
- 사용자 관찰: 사람 대 사람 질문은 시간이 오래 걸리고 평가자의 주관이 포함된다.
- Market signal: CoderPad, Dora, Dobr.AI, Infyva, Saffron 등 AI/technical interview assessment 제품이 존재하지만, 대학 캡스톤 프로젝트 수행 진위 검증에 직접 맞춘 도구는 별도 검증이 필요하다.
- Academic signal: code interview, conversational exam, voice AI oral assessment 연구는 구술 기반 평가가 프로젝트/코드 이해 검증에 유효할 가능성을 시사한다.

## Proposed Solution

교수가 학생의 프로젝트 자료를 하나의 zip 파일로 업로드하면, 시스템이 문서와 코드를 분리 분석해 프로젝트 context를 만들고, 자료 기반 질문과 꼬리질문을 생성한다. 교수 또는 학생은 Streamlit 화면에서 10분 내외의 단계형 인터뷰를 진행하고, FastAPI backend는 답변을 Bloom’s Taxonomy와 루브릭으로 평가해 프로젝트 영역별 신뢰도 리포트를 생성한다. 기술 스택은 빠른 캡스톤 시연 구현을 위해 FastAPI backend, Streamlit frontend, SQLite3 저장소로 고정한다.

## Key Hypothesis

We believe 자료 기반 AI 인터뷰와 루브릭 평가가 교수의 프로젝트 진위 검증 시간을 줄이고 평가 일관성을 높일 것이다.
We'll know we're right when 10분 인터뷰 후 프로젝트 영역별 신뢰도 리포트가 생성되고, 교수가 추가 확인 지점을 바로 파악할 수 있다.

## What We're NOT Building

- 학교 로그인 - 캡스톤 시연용 MVP에는 복잡한 인증/권한 시스템이 필요하지 않다.
- 학생 계정 관리 - 핵심은 제출 프로젝트의 수행 진위 검증이지 학생 포털 운영이 아니다.
- 일반 시험/퀴즈 기능 - 이 서비스는 학습 평가 플랫폼이 아니라 프로젝트 진위 검증 도구다.
- 성적 관리 - 최종 성적 산출이 아니라 교수의 판단을 돕는 신뢰도 리포트가 목적이다.
- 학습 대시보드 - 학습 추적은 범위 밖이다.
- 여러 팀 비교 - MVP는 단일 프로젝트 평가에 집중한다.
- 화상 감독 - 부정행위 감시보다 자료 기반 질의응답 검증이 우선이다.
- PDF export - 시연용 MVP에서는 화면 리포트로 충분하다.
- GitHub URL 직접 제출 - v1 입력은 단일 zip 제출로 고정한다.
- PostgreSQL 운영 저장소 - 빠른 구현을 위해 SQLite3를 사용한다.

## Success Metrics

| Metric | Target | How Measured |
|--------|--------|--------------|
| 평가 완료 시간 | 10분 내외 인터뷰 후 리포트 생성 | 업로드 완료부터 리포트 생성까지 timestamp 기록 |
| 리포트 완성도 | 프로젝트 영역별 신뢰도, 질문별 점수, 의심 지점 포함 | 리포트 schema validation |
| 질문 근거성 | 생성 질문 80% 이상이 제출 자료 source reference와 연결 | 질문별 `source_refs` 존재 여부 검사 |
| 교수 판단 지원성 | 교수가 추가 확인 지점을 바로 파악 가능 | 캡스톤 시연 피드백 또는 수동 체크리스트 |
| 로컬 시연 준비 시간 | 새 환경에서 10분 이내 실행 준비 | setup/runbook 검증 |

## Open Questions

- [ ] Streamlit에서 음성 인터뷰를 어느 수준까지 자연스럽게 구현할 것인가?
- [ ] zip 내부 코드 크기 제한을 얼마로 둘 것인가?
- [ ] 코드 분석 범위를 정적 파일 요약으로 둘지, 실행/테스트 분석까지 포함할 것인가?
- [ ] 프로젝트 영역 분류를 LLM 자동 추론만으로 둘지, 교수 수정 UI를 제공할 것인가?
- [ ] 10분 인터뷰에서 질문 수와 꼬리질문 수의 기본값을 어떻게 둘 것인가?
- [ ] SQLite3 파일과 업로드 artifact를 어디에 저장하고 데모 reset을 어떻게 할 것인가?

---

## Users & Context

**Primary User**
- **Who**: 프로젝트 과제에서 학생이 실제로 해당 프로젝트를 수행했는지 평가하고 싶은 교수
- **Current behavior**: 제출 문서와 코드를 직접 읽고, 구현 내용을 분석한 뒤, 학생에게 직접 질문한다.
- **Trigger**: 캡스톤 프로젝트 발표 또는 과제 평가 시점에 학생의 실제 수행 여부를 판단해야 할 때
- **Success state**: 10분 내외 인터뷰 후 프로젝트 영역별 신뢰도 리포트를 확인하고, 의심 지점과 추가 질문 포인트를 바로 파악한다.

**Job to Be Done**
When 캡스톤 프로젝트를 평가해야 할 때, I want to 제출 자료 기반 인터뷰와 자동 리포트를 생성하고, so I can 학생의 실제 수행 여부와 프로젝트 이해도를 빠르고 일관되게 판단한다.

**Non-Users**
TBD - user skipped. Current assumption: 기업 채용 면접관, 일반 온라인 시험 감독관, 학생 자기학습 사용자, 학교 LMS 관리자는 MVP의 직접 대상이 아니다.

---

## Solution Detail

### Core Capabilities (MoSCoW)

| Priority | Capability | Rationale |
|----------|------------|-----------|
| Must | 단일 zip 업로드 | 모든 프로젝트 자료를 하나의 제출 단위로 받아 MVP 입력 흐름을 단순화한다. |
| Must | zip 내부 문서/코드 분리 추출 | 질문 생성과 근거 평가를 위해 문서와 코드 context가 필요하다. |
| Must | 자료 기반 질문 생성 | 교수-학생 프로젝트 과제 평가 맥락에서 실제 수행자라면 설명할 수 있는 전체 동작 흐름, 설계 의도, 구현 선택 질문을 만들어야 한다. |
| Must | 답변 평가와 꼬리질문 생성 | 세부 코드 암기 여부가 아니라 학생의 구조 이해도, 구현 경험, 문제 해결 과정, 한계 인식을 더 깊게 검증한다. |
| Must | Bloom + 루브릭 기반 리포트 | 평가 일관성과 설명 가능성을 제공한다. |
| Must | SQLite3 기반 로컬 저장 | 캡스톤 시연을 빠르게 구현하고 별도 DB 운영 부담을 없앤다. |
| Should | Streamlit 오디오 입력 기반 인터뷰 | 음성 인터뷰 데모 가치를 높인다. |
| Should | 교수용 분석 결과 미리보기 | 인터뷰 전에 프로젝트 영역과 질문 후보를 확인할 수 있다. |
| Could | 리포트 PDF export | 제출/보관 편의성이 있지만 MVP 검증에는 필수 아님. |
| Could | 여러 팀 비교 | 운영 단계에서 유용하지만 단일 평가 검증 이후로 미룬다. |
| Won't | 학교 로그인/학생 계정 | 캡스톤 시연 범위와 핵심 문제에 직접 필요하지 않다. |
| Won't | GitHub URL 직접 분석 | v1 입력 정책은 단일 zip 제출이다. |
| Won't | PostgreSQL 도입 | 빠른 로컬 시연 구현이 우선이다. |

### MVP Scope

교수가 하나의 zip 파일을 업로드하면 시스템이 프로젝트 자료를 분석하고, 자료 기반 질문으로 10분 내외 인터뷰를 진행한 뒤, 프로젝트 영역별 신뢰도 리포트를 생성한다. 모든 평가 데이터는 SQLite3 파일에 저장하고, 업로드 artifact와 추출 결과는 로컬 디렉터리에 저장한다.

### User Flow

```text
교수 Streamlit 접속
  ↓
프로젝트명, 학생/팀 식별 정보, 설명 입력
  ↓
프로젝트 자료 zip 업로드
  ↓
FastAPI가 zip 저장 및 해제
  ↓
문서와 코드 추출/분리
  ↓
SQLite3에 평가 상태와 artifact metadata 저장
  ↓
RAG context와 프로젝트 영역 생성
  ↓
질문 후보 생성
  ↓
Streamlit에서 단계형 인터뷰 진행
  ↓
답변 평가 및 꼬리질문 반복
  ↓
최종 리포트 생성
  ↓
교수가 신뢰도, 의심 지점, 추가 확인 질문 확인
```

---

## Technical Approach

**Feasibility**: HIGH

**Architecture Notes**
- Backend는 FastAPI로 구현한다. 기존 `cli/`의 Python core를 이식하기 쉽고, Pydantic schema를 API contract와 LLM structured output에 같이 사용할 수 있다.
- Frontend는 Streamlit으로 구현한다. 캡스톤 시연용 UI를 빠르게 만들고 Python 중심 개발 흐름을 유지한다.
- Storage는 SQLite3로 시작한다. 단일 사용자/로컬 시연 중심이므로 PostgreSQL보다 설정 비용이 낮다.
- Streamlit은 authoritative business logic을 갖지 않는다. 화면, form, upload, 진행 상태 표시, API 호출만 담당한다.
- FastAPI는 zip upload, artifact extraction, RAG, question generation, answer evaluation, report generation의 원천이다.
- SQLite3는 평가, artifact metadata, 질문, 답변, 점수, 리포트를 저장한다.
- Qdrant는 문서/코드 chunk embedding을 저장한다. 단, 더 빠른 MVP가 필요하면 Qdrant도 in-memory/local 대체안을 별도 spike로 검토한다.
- MVP 음성은 Streamlit `st.audio_input` 기반의 단계형 녹음 흐름으로 시작한다. 완전한 WebRTC 실시간 대화는 후순위다.

**Technical Risks**

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Streamlit 음성 UX가 실시간 대화처럼 자연스럽지 않음 | High | MVP는 질문 출력 → 녹음 → STT → 평가 → 다음 질문의 단계형 인터뷰로 정의한다. |
| zip 파일이 너무 크거나 불필요한 파일이 많음 | Medium | `.gitignore`, 확장자 allowlist, 크기 제한, binary skip 정책을 둔다. |
| LLM 질문이 제출 자료와 무관해짐 | Medium | 모든 질문에 source reference를 요구하고 schema validation을 수행한다. |
| 평가 결과가 주관적으로 보임 | Medium | Bloom level, rubric criterion, evidence reference, reasoning을 함께 저장한다. |
| 기존 CLI 모델이 교육 도메인 필드를 포함함 | High | `subject`, `week`, 일반 exam type을 제거하고 project evaluation domain model로 재정의한다. |
| SQLite3 동시성 한계 | Low | MVP는 단일 교수/단일 시연 흐름으로 제한하고, 필요 시 PostgreSQL 전환을 후순위로 둔다. |
| 장기 분석 작업이 request timeout을 초과함 | Medium | FastAPI BackgroundTasks와 job 상태 테이블로 시작한다. SQLite에 job status를 저장한다. |

---

## Implementation Phases

| # | Phase | Description | Status | Parallel | Depends | PRP Plan |
|---|-------|-------------|--------|----------|---------|----------|
| 1 | Project skeleton | FastAPI service, Streamlit app, shared local dev structure, SQLite file path, Qdrant local baseline | complete | - | - | `.claude/PRPs/plans/fastapi-streamlit-project-skeleton.plan.md` |
| 2 | Domain model and SQLite persistence | ProjectEvaluation, Artifact, Context, Question, Session, Turn, RubricScore, Report schema | complete | - | 1 | - |
| 3 | Zip ingestion pipeline | 단일 zip 업로드, 안전한 해제, 문서/코드 분리, 텍스트 추출 | complete | - | 2 | - |
| 4 | RAG and question generation | Qdrant embedding, project context, project areas, Bloom 기반 질문 생성 | complete | - | 3 | - |
| 5 | Interview engine | Streamlit 단계형 인터뷰, 답변 저장, 평가, 꼬리질문 생성 | complete | with 6 | 4 | - |
| 6 | Report UI | 프로젝트 영역별 신뢰도 리포트 API와 Streamlit 화면 | complete | with 5 | 4 | - |
| 7 | MVP validation | 10분 인터뷰 golden path, fixture 기반 LLM 테스트, 시연 데이터 정리 | complete | - | 5, 6 | - |
| 8 | Room flow, artifact transparency, and grounded questions | 교수자 방 생성/관리자 비밀번호/학생 입장 정책을 추가하고, 업로드 제외 사유와 자료 기반 질문 생성 문제를 보정 | complete | - | 7 | `.claude/PRPs/plans/project-evaluation-room-artifact-question-repair.plan.md` |
| 9 | Academic project question framing repair | 현재 구현의 질문이 채용 면접/지원 동기 맥락이나 과도한 세부 코드 확인으로 흐르지 않도록, 교수의 프로젝트 과제 수행 진위 평가에 맞는 질문 정책과 프롬프트를 보정 | complete | - | 8 | `.claude/PRPs/plans/project-evaluation-academic-question-framing-repair.plan.md` |

### Phase Details

**Phase 1: Project skeleton**
- **Goal**: FastAPI + Streamlit + SQLite3 기반 실행 가능한 프로젝트 뼈대를 만든다.
- **Scope**: `services/api`, `apps/streamlit`, SQLite data directory, root run script, 환경변수 예시, 기본 health check.
- **Success signal**: FastAPI health endpoint와 Streamlit 화면이 로컬에서 실행되고 SQLite 파일이 생성된다.

**Phase 2: Domain model and SQLite persistence**
- **Goal**: 프로젝트 평가 도메인 데이터를 SQLite3에 저장할 수 있게 한다.
- **Scope**: Pydantic models, SQLAlchemy models, SQLite engine/session, lightweight migration 또는 create_all 정책, repository/service skeleton.
- **Success signal**: 평가 생성, 조회, artifact metadata 저장 API 테스트가 통과한다.

**Phase 3: Zip ingestion pipeline**
- **Goal**: 단일 zip 제출물을 안전하게 해제하고 분석 가능한 텍스트로 변환한다.
- **Scope**: zip slip 방어, 파일 크기 제한, 문서 추출, 코드 파일 필터링, source refs 생성.
- **Success signal**: fixture zip에서 PDF/PPTX/DOCX/코드 텍스트와 source refs가 생성된다.

**Phase 4: RAG and question generation**
- **Goal**: 제출 자료 기반 프로젝트 context와 질문 후보를 생성한다.
- **Scope**: chunking, embedding, Qdrant 저장, retrieval, project areas, Bloom/rubric question schema.
- **Success signal**: 질문마다 project area, Bloom level, expected signal, source refs가 포함된다.

**Phase 5: Interview engine**
- **Goal**: 10분 내외 단계형 인터뷰를 진행하고 답변을 평가한다.
- **Scope**: Streamlit interview state, text answer fallback, optional audio input, STT adapter, answer evaluation, follow-up loop.
- **Success signal**: 질문 → 답변 → 평가 → 꼬리질문/다음 질문 흐름이 SQLite에 저장된다.

**Phase 6: Report UI**
- **Goal**: 교수에게 프로젝트 수행 진위 판단에 필요한 상세 리포트를 보여준다.
- **Scope**: final decision, authenticity score, area analyses, rubric scores, suspicious points, follow-up questions.
- **Success signal**: 하나의 평가 세션에서 최종 리포트 화면이 생성된다.

**Phase 7: MVP validation**
- **Goal**: 캡스톤 시연 가능한 end-to-end 흐름을 안정화한다.
- **Scope**: golden path E2E, deterministic fixtures, demo zip, README/runbook, demo reset script.
- **Success signal**: 데모 zip 업로드부터 리포트 생성까지 끊기지 않고 실행된다.

**Phase 9: Academic project question framing repair**
- **Goal**: 현재 구현의 질문 생성 결과를 교수-학생 프로젝트 과제 평가 맥락으로 바로잡는다.
- **Scope**: 질문 생성 프롬프트, rule-based fallback, realtime interviewer instruction, 평가 기대 신호에서 채용 면접/회사/직무 지원 동기 프레이밍을 배제하고, 세부 코드 암기형 질문 대신 전체 동작 흐름·설계 의도·구현 선택·문제 해결 경험·한계 인식을 묻도록 보정한다.
- **Success signal**: 생성된 5개 질문과 realtime 첫 질문/꼬리질문이 모두 프로젝트 수행 진위 검증 맥락이며, 특정 함수/라인/코드 조각 암기를 요구하지 않고 source ref는 질문 근거로만 사용된다.

### Parallelism Notes

Phase 5와 Phase 6은 Phase 4 이후 병렬 진행 가능하다. Interview engine은 turn과 score를 생성하고, Report UI는 저장된 score/report schema를 표시하므로 API contract가 고정되면 동시에 구현할 수 있다.

---

## Decisions Log

| Decision | Choice | Alternatives | Rationale |
|----------|--------|--------------|-----------|
| Backend framework | FastAPI | Django, Flask, Next.js full-stack | 기존 CLI core가 Python이고 API/schema 작업이 빠르다. |
| Frontend framework | Streamlit | Next.js, Gradio | 캡스톤 시연용으로 Python 기반 UI를 가장 빠르게 만들 수 있다. |
| Relational storage | SQLite3 | PostgreSQL | 빠른 로컬 구현과 쉬운 시연이 우선이다. |
| Input policy | Single zip upload | GitHub URL, 개별 파일 업로드 | 제출 단위를 단순화하고 시연 안정성을 높인다. |
| Voice MVP | 단계형 audio input | 실시간 WebRTC 대화 | Streamlit 제약을 고려하면 녹음 기반 흐름이 더 안정적이다. |
| Evaluation method | Bloom + rubric | 단순 점수, LLM 자유평 | 평가 일관성과 설명 가능성을 확보한다. |
| Vector DB | Qdrant | pgvector, Chroma, in-memory retrieval | 기존 CLI core와 의존성이 이미 맞아 있다. |
| Background jobs | FastAPI BackgroundTasks + SQLite job table | Celery, arq/Valkey | MVP 복잡도를 낮추고 별도 infra를 줄인다. |

---

## Research Summary

**Market Context**
- CoderPad, Dora, Dobr.AI, Infyva, Saffron 등 AI/technical assessment 제품은 기술 평가와 인터뷰 자동화 수요가 있음을 보여준다.
- 다만 대학 캡스톤 프로젝트의 “학생이 이 프로젝트를 진짜 했는가”를 자료 기반 구술 인터뷰로 검증하는 사용 사례는 더 좁고 특화되어 있다.
- 관련 연구로 code interview, conversational exam, voice AI oral assessment가 있으며, 구술 기반 검증은 코드/프로젝트 이해 평가에 적합한 방향으로 보인다.

**Technical Context**
- 현재 `v2/cli`에는 자료 추출, RAG, 질문 생성, 답변 평가, 꼬리질문, 리포트 생성 core가 Python으로 존재한다.
- FastAPI는 이 core를 service layer로 이식하기에 적합하다.
- Streamlit은 `st.file_uploader`, `st.session_state`, `st.audio_input`, `st.chat_input`을 통해 캡스톤 시연용 인터페이스를 빠르게 구현할 수 있다.
- SQLite3는 단일 사용자 로컬 시연에서 가장 낮은 설정 비용으로 평가/질문/답변/리포트 상태를 저장할 수 있다.
- 기존 `docs/tech-stack.md`의 Next.js/PostgreSQL/WebRTC 전제는 FastAPI + Streamlit + SQLite3 정책으로 갱신되어야 한다.

---

*Generated: 2026-05-09*
*Status: DRAFT - needs validation*
