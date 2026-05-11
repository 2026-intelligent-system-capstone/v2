# Architecture Decisions

이 문서는 `v2/` 프로젝트에서 내려진 주요 제품·기술 결정과 변경 이력을 기록한다. 현재 정책의 상세 설명은 각 주제별 문서를 source of truth로 삼고, 이 문서는 왜 이전 접근을 유지하거나 폐기했는지에 집중한다.

## 2026-05-10. 프로젝트 범위를 수행 진위 검증으로 재정의

- 상태: 채택
- 이전 접근: 기존 기획은 강의실, 학생/교수자 역할, 일반 시험 운영, 학습 대시보드 같은 교육 플랫폼 도메인을 포함했다.
- 새 접근: `v2/`는 인터뷰 용도의 프로젝트 평가 기능 하나만 다루며, 모든 질문은 “지원자가 이 프로젝트를 진짜로 수행했는가?”를 기준으로 판단한다.
- 결정 이유: 캡스톤 시연에서 필요한 핵심 가치는 일반 학습 평가가 아니라 제출 프로젝트의 실제 수행 여부 검증이다.
- 영향을 받는 문서: `CLAUDE.md`, `docs/project-evaluation-scope.md`, `docs/tech-stack.md`
- 검증 기준: 새 요구사항과 구현 계획에서 manyfast, 강의실, 학교 로그인, 성적 관리, 일반 시험 운영을 기본 전제로 삼지 않는다.

## 2026-05-10. FastAPI + Streamlit + SQLite3 기반 MVP 채택

- 상태: 채택
- 이전 접근: 기존 backend/frontend 구조를 확장하거나 더 복잡한 Web frontend와 운영 DB를 사용하는 선택지가 있었다.
- 새 접근: FastAPI backend, Streamlit frontend, SQLite3 persistence를 기본으로 하고 Qdrant와 OpenAI API를 RAG/LLM 처리에 사용한다.
- 결정 이유: 기존 CLI core가 Python 기반이고, 캡스톤 시연에서는 설치와 실행이 단순한 구조가 더 중요하다.
- 영향을 받는 문서: `docs/tech-stack.md`, `docs/api-and-job-flow.md`
- 검증 기준: 프로젝트 생성, zip 업로드, 분석, 질문 생성, 인터뷰, 리포트 확인 흐름이 로컬 환경에서 빠르게 실행된다.

## 2026-05-10. 완전한 WebRTC 실시간 음성 대화 제외

- 상태: 채택
- 이전 접근: 제품 설명에서 실시간 음성 인터뷰로 오해될 수 있는 표현이 있었다.
- 새 접근: MVP는 Streamlit 기반 단계형 인터뷰를 제공하고, 텍스트 답변을 기본으로 하며 `st.audio_input` 기반 오디오 녹음을 선택적으로 지원한다.
- 결정 이유: 실시간 WebRTC 대화는 MVP 시연 범위 대비 구현 부담이 크며, 수행 진위 검증에는 단계형 질문·답변·평가 흐름이 충분하다.
- 영향을 받는 문서: `docs/project-evaluation-scope.md`, `docs/tech-stack.md`, `docs/api-and-job-flow.md`
- 검증 기준: 문서에서 WebRTC 실시간 대화가 MVP 필수 기능처럼 표현되지 않는다.

## 2026-05-10. 단일 zip 제출만 MVP 입력으로 채택

- 상태: 채택
- 이전 접근: GitHub URL 직접 분석, 개별 파일 업로드, 여러 자료 입력 방식을 함께 고려할 수 있었다.
- 새 접근: MVP는 프로젝트 소스 코드와 README, PDF, PPTX, DOCX, API 명세, 설명 텍스트를 하나의 zip 파일로 받는다.
- 결정 이유: 입력 경로를 단순화해야 추출, indexing, 질문 생성, 리포트 흐름을 빠르게 검증할 수 있다.
- 영향을 받는 문서: `docs/project-evaluation-scope.md`, `docs/tech-stack.md`, `docs/security-and-data-policy.md`
- 검증 기준: GitHub URL 직접 분석과 개별 파일 업로드는 현 MVP 제외 범위로 문서화된다.

## 2026-05-10. 상위 N개 artifact 발췌 방식 폐기

- 상태: 채택
- 이전 접근: 질문 생성 또는 프로젝트 context 생성에서 업로드 artifact 일부, 앞부분, 상위 10개 파일에 편향될 수 있는 방식이 있었다.
- 새 접근: zip 내부 코드베이스와 프로젝트 문서를 `artifact_role`로 분류하고, role별 splitter와 Qdrant retrieval을 통해 구조화된 context pack을 만든다.
- 결정 이유: 실제 구현 흐름과 문서-코드 일치 여부를 검증하려면 일부 파일 발췌만으로는 근거가 부족하다.
- 영향을 받는 문서: `CLAUDE.md`, `docs/project-evaluation-scope.md`, `docs/tech-stack.md`, `docs/rag-ingestion-and-retrieval.md`
- 검증 기준: 질문 생성 결과가 코드 근거, 문서 근거, source refs를 포함하고 artifact 순서나 상위 N개 파일에 의존하지 않는다.

## 2026-05-10. 코드와 프로젝트 문서의 alignment를 핵심 검증 근거로 채택

- 상태: 채택
- 이전 접근: 코드 파일 또는 문서 자료를 각각 독립적인 텍스트 근거로만 사용할 수 있었다.
- 새 접근: 질문 생성과 리포트 평가에서 프로젝트 문서의 주장과 코드 구현 근거가 일치하는지, 문서에는 있지만 코드 근거가 약한지, 코드에는 있지만 문서 설명이 부족한지 확인한다.
- 결정 이유: 실제 수행자는 문서에 쓴 설계 의도와 코드 구현 사이의 연결을 설명할 수 있어야 한다.
- 영향을 받는 문서: `docs/project-evaluation-scope.md`, `docs/rag-ingestion-and-retrieval.md`
- 검증 기준: 질문 유형과 리포트 구조에 document-code alignment와 source refs가 포함된다.

## 2026-05-10. RAG/LLM/파일 처리 실패를 조용한 fallback으로 숨기지 않음

- 상태: 채택
- 이전 접근: broad `try/except`, 조용한 fallback, 일부 실패 무시로 핵심 기능 실패가 성공처럼 보일 수 있었다.
- 새 접근: 외부 입력 문제, Qdrant 연결 문제, RAG index 비어 있음, LLM 실패는 job/API/UI 상태에서 원인을 추적 가능하게 드러낸다.
- 결정 이유: 질문 생성과 평가가 근거 없이 성공한 것처럼 보이면 수행 진위 검증이라는 제품 목적 자체가 깨진다.
- 영향을 받는 문서: `docs/api-and-job-flow.md`, `docs/security-and-data-policy.md`, `docs/rag-ingestion-and-retrieval.md`
- 검증 기준: RAG index가 비어 있거나 핵심 dependency가 실패하면 명확한 실패 상태와 확인 대상이 남는다.
