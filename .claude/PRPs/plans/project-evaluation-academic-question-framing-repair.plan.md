# Plan: Project Evaluation Academic Question Framing Repair

## Summary

현재 구현된 질문 생성은 자료 기반이라는 조건은 일부 만족하지만, 제품 목적을 완전히 반영하지 못한다. 이 서비스는 회사 채용 면접이나 직무 적합성 평가가 아니라, 대학교 프로젝트 과제에서 교수가 학생이 실제로 프로젝트를 수행했고 전체 구조를 이해하는지 확인하는 도구다. 따라서 질문은 “왜 이 회사/직무에 지원했는가” 같은 채용 프레이밍을 절대 포함하지 않아야 하며, 특정 함수·라인·코드 조각을 암기했는지 묻는 방식도 실패로 본다. 질문은 source ref를 근거로 삼되, 학생이 실제 구현자라면 설명할 수 있는 전체 동작 흐름, 설계 의도, 구현 선택, 문제 해결 경험, 한계 인식을 묻도록 보정한다.

## Problem Classification

이 문제는 사용자 관찰이나 신규 요구사항이 아니라 **현재 구현 결함**이다. 이미 구현된 질문 생성/인터뷰 프롬프트가 제품 맥락을 잘못 반영했거나, source-grounded를 지나치게 세부 코드 확인으로 해석할 위험이 있다.

## User Story

As a 교수,
I want AI가 학생에게 프로젝트 전체 동작과 설계 이해를 확인하는 질문을 하기를,
so that 학생이 프로젝트 과제를 실제로 수행했고 내용을 이해하는지 판단할 수 있다.

As a 학생,
I want 코드 암기 시험이 아니라 내가 구현한 프로젝트의 구조, 흐름, 의사결정, 시행착오를 설명할 기회를 얻기를,
so that 실제 수행 경험과 이해도를 공정하게 보여줄 수 있다.

## Current Failure Modes

- 질문이 회사/직무 지원 동기처럼 채용 면접 맥락으로 생성된다.
- “지원자”라는 용어가 기업 채용 지원자로 읽히는 문맥에서 사용된다.
- source path나 snippet keyword를 포함한다는 이유로 특정 코드 세부사항 암기형 질문이 될 수 있다.
- fallback 질문이 파일명을 직접 언급하더라도, 전체 동작 흐름을 묻지 않으면 프로젝트 이해도 검증으로 부족하다.
- realtime interviewer instruction이 “프로젝트 진위 검증”만 말하고, 교수-학생 과제 평가 맥락과 금지 질문을 충분히 제한하지 않는다.

## Question Policy

### Required Framing

- 평가자는 교수 또는 프로젝트 평가자다.
- 응답자는 학생 또는 프로젝트 수행자다.
- 평가 대상은 회사 지원 동기가 아니라 제출한 프로젝트 과제의 실제 수행 여부와 이해도다.
- 질문은 제출 자료의 source ref를 근거로 삼되, source ref는 암기 대상이 아니라 설명을 유도하는 근거다.

### Required Question Types

질문 세트는 다음 축을 균형 있게 포함해야 한다.

1. 전체 동작 흐름: 입력, 처리, 저장, 출력 또는 사용자 플로우가 어떻게 이어지는지
2. 구조 이해: 주요 모듈/계층/컴포넌트가 어떤 책임을 갖는지
3. 설계 의도: 왜 해당 구조, 라이브러리, 데이터 흐름을 선택했는지
4. 구현 선택: 중요한 trade-off와 대안은 무엇이었는지
5. 문제 해결 경험: 구현 중 막힌 지점, 디버깅, 수정 과정을 어떻게 겪었는지
6. 한계 인식: 지금 다시 개선한다면 무엇을 바꾸고 어떤 위험을 확인할지

### Forbidden Question Types

- 회사, 직무, 입사, 지원 동기, 커리어 적합성, 조직 문화 적합성 질문
- “이 함수의 정확한 인자/반환값/라인/분기 조건을 말하라” 같은 코드 암기 질문
- 특정 파일의 세부 구현을 외우지 않으면 답할 수 없는 질문
- 제출 자료와 무관한 일반 CS/기술 면접 질문
- source ref의 파일명만 바꿔 끼운 generic 질문

### Acceptable Specificity

- 허용: “`services/api/...`와 `apps/streamlit/...` 흐름을 기준으로 업로드된 zip이 질문 생성까지 이어지는 과정을 설명해 주세요.”
- 허용: “이 구조에서 FastAPI와 Streamlit의 책임을 나눈 이유와 장단점을 설명해 주세요.”
- 금지: “`_fallback_question` 함수의 세 번째 조건문이 어떤 문자열을 반환하나요?”
- 금지: “이 회사/직무에 지원한 이유는 무엇인가요?”

## Mandatory Reading

| Priority | File | Why |
|---|---|---|
| P0 | `services/api/app/project_evaluations/analysis/prompts.py` | LLM context/question/evaluation prompt의 역할·대상자 표현과 질문 정책 수정 대상 |
| P0 | `services/api/app/project_evaluations/interview/question_generator.py` | rule-based fallback 질문 문구, intent, expected signal 수정 대상 |
| P0 | `services/api/app/project_evaluations/realtime/proxy.py` | 음성 인터뷰 진행 instruction과 꼬리질문 정책 수정 대상 |
| P1 | `services/api/tests/test_evaluation_api.py` | 기존 질문 생성 smoke assertion 확인 및 최소 수정 대상 |
| P1 | `apps/streamlit/Home.py` | 질문 preview 표시 문구가 채용/암기 프레이밍을 유도하지 않는지 확인 |
| P1 | `.claude/PRPs/prds/fastapi-streamlit-project-evaluation.prd.md` | Phase 9 요구사항과 수용 기준 원천 |

## Files to Change

| File | Action | Justification |
|---|---|---|
| `services/api/app/project_evaluations/analysis/prompts.py` | UPDATE | system/user prompts에서 지원자/채용으로 읽힐 수 있는 표현을 학생/프로젝트 수행자 평가 맥락으로 교체하고 금지 질문을 명시한다. |
| `services/api/app/project_evaluations/interview/question_generator.py` | UPDATE | fallback question focus, intents, expected signals를 세부 코드 암기에서 전체 동작/설계/경험 설명 중심으로 조정한다. |
| `services/api/app/project_evaluations/realtime/proxy.py` | UPDATE | realtime interviewer가 교수의 프로젝트 과제 평가자처럼 질문하고, 짧은 꼬리질문도 암기 확인이 아니라 설명 확장으로 제한한다. |
| `services/api/tests/test_evaluation_api.py` | UPDATE MINIMALLY | 기존 테스트가 너무 세부 source path 포함만 확인한다면, 채용 프레이밍 금지와 전체 설명형 질문 여부를 최소 smoke로 확인한다. |
| `.claude/PRPs/prds/fastapi-streamlit-project-evaluation.prd.md` | UPDATE | Phase 9 pending 상태와 수용 기준을 기록한다. |

## NOT Building

- 새 질문 생성 엔진 전체 재작성
- 정적 코드 분석기 도입
- 학생별 난이도 적응형 인터뷰
- 회사 채용 면접 기능
- 일반 CS 지식 시험 기능
- 코드 라인 단위 퀴즈 생성 기능
- 대규모 테스트 확장

## Step-by-Step Tasks

### Task 1: Repair LLM prompt framing

- **ACTION**: Update `analysis/prompts.py`.
- **IMPLEMENT**:
  - `CONTEXT_SYSTEM`, `QUESTION_SYSTEM`, `EVAL_SYSTEM`에서 기업 채용으로 읽힐 수 있는 “지원자” 단독 표현을 “학생/프로젝트 수행자” 중심으로 바꾼다.
  - `QUESTION_SYSTEM`에 Required/Forbidden policy를 짧고 명확하게 넣는다.
  - 질문은 source ref에 근거해야 하지만, 파일/함수 암기 질문을 만들지 말라고 명시한다.
  - user prompt의 “지원자가 제출한” 표현도 “학생이 제출한” 또는 “프로젝트 수행자가 제출한”으로 바꾼다.
- **GOTCHA**: source-grounded를 제거하지 않는다. 근거성은 유지하되 질문 목적을 전체 이해 검증으로 바꾼다.
- **VALIDATE**: 생성 prompt에 회사/직무/입사/지원 동기가 나타나지 않는지 검색한다.

### Task 2: Repair rule-based fallback question wording

- **ACTION**: Update `interview/question_generator.py`.
- **IMPLEMENT**:
  - `QUESTION_FOCUS`를 전체 흐름, 역할 분담, 설계 의도, 문제 해결, 개선 판단 중심으로 유지하되 “주요 함수나 클래스의 책임”처럼 암기형으로 오해될 표현은 “주요 모듈/컴포넌트의 책임과 연결 방식”으로 완화한다.
  - `INTENTS`에서 “코드 수준 이해도 검증”을 “구조와 동작 이해도 검증”으로 바꾼다.
  - `EXPECTED_SIGNALS`에서 “구체적인 함수, 클래스, 설정”을 반드시 요구하지 말고, 필요 시 예시로만 허용한다. 핵심은 흐름, 역할, 근거, 경험이다.
  - `_fallback_question`은 path를 언급하더라도 “기준으로 전체 흐름/역할/결정 이유를 설명”하도록 한다.
- **GOTCHA**: 파일명을 완전히 제거하지 않는다. 파일명은 근거 anchor로 남기되, 답변 요구는 암기가 아니라 설명이어야 한다.
- **VALIDATE**: LLM disabled 상태에서도 질문 5개가 모두 설명형인지 확인한다.

### Task 3: Repair realtime interviewer instruction

- **ACTION**: Update `realtime/proxy.py`.
- **IMPLEMENT**:
  - “지원자”를 “학생/프로젝트 수행자”로 바꾼다.
  - instruction에 “회사의 지원 동기나 직무 적합성을 묻지 말라”를 명시한다.
  - “세부 코드 암기 확인 질문을 하지 말고, 답변이 모호할 때는 전체 흐름·설계 이유·경험을 더 설명하게 하라”를 진행 규칙에 추가한다.
- **GOTCHA**: 기존 마이크/WebSocket 로직은 건드리지 않는다.
- **VALIDATE**: `build_interview_instructions()` 출력 문자열을 직접 확인한다.

### Task 4: Minimal smoke assertions

- **ACTION**: Update tests only if cheap and local.
- **IMPLEMENT**:
  - 기존 question generation 테스트가 있으면 질문 문자열에 `회사`, `직무`, `입사`, `지원 동기`가 없는지 확인한다.
  - fallback 질문에 `설명`/`흐름`/`구조`/`이유`/`개선` 중 하나 이상이 포함되는지 확인한다.
  - 특정 함수/라인 암기 여부까지 완벽히 판정하는 복잡한 테스트는 만들지 않는다.
- **GOTCHA**: 이 프로젝트는 feature-first MVP다. 테스트 때문에 구현을 지연하지 않는다.
- **VALIDATE**: `uv run pytest services/api/tests/test_evaluation_api.py`.

## Acceptance Criteria

- [ ] LLM 질문 생성 prompt가 교수-학생 프로젝트 과제 평가 맥락을 명시한다.
- [ ] LLM 질문 생성 prompt가 회사/직무/입사/지원 동기 질문을 금지한다.
- [ ] LLM 질문 생성 prompt가 세부 코드 암기형 질문을 금지한다.
- [ ] Rule-based fallback 질문은 source ref를 근거로 사용하지만, 답변 요구는 전체 동작 흐름/구조/설계/경험 설명이다.
- [ ] Realtime interviewer instruction은 학생의 프로젝트 수행 진위와 이해도 검증을 목표로 한다.
- [ ] 생성 질문 5개에는 채용 면접 맥락이 없다.
- [ ] 생성 질문 5개는 특정 코드 라인이나 함수 내부 세부사항 암기를 요구하지 않는다.
- [ ] 질문 preview에서 source path는 근거로 보이되, 질문 본문은 프로젝트 이해 설명형이다.
- [ ] 기존 microphone/realtime transport 로직은 변경하지 않는다.
- [ ] 최소 smoke validation이 통과한다.

## Validation Commands

### Search Forbidden Framing

```bash
grep -R -nE "회사|직무|입사|지원 동기|채용" services/api/app/project_evaluations apps/streamlit services/api/tests || true
```

EXPECT: 금지 표현은 정책/테스트의 forbidden list 외에 질문 생성 instruction으로 유도되지 않는다.

### Static Analysis

```bash
uv run ruff check services/api/app/project_evaluations/analysis/prompts.py services/api/app/project_evaluations/interview/question_generator.py services/api/app/project_evaluations/realtime/proxy.py
```

EXPECT: Zero lint errors.

### Minimal Test

```bash
uv run pytest services/api/tests/test_evaluation_api.py
```

EXPECT: Existing API tests pass with any minimal assertion updates.

### Manual Smoke

- [ ] LLM disabled or unavailable 상태에서 질문 생성.
- [ ] 질문 5개를 눈으로 확인.
- [ ] 회사/직무/지원동기/채용 면접 질문이 없는지 확인.
- [ ] 각 질문이 전체 흐름, 구조, 설계 이유, 구현 선택, 문제 해결, 개선 판단 중 하나를 묻는지 확인.
- [ ] realtime instruction 출력에 같은 정책이 반영됐는지 확인.

## Completion Checklist

- [ ] 이 문제를 사용자 관찰로 기록하지 않았다.
- [ ] 이 문제를 현재 구현 결함으로 기록했다.
- [ ] PRD Phase 9가 이 plan을 가리킨다.
- [ ] Prompt/fallback/realtime 세 계층이 같은 질문 정책을 공유한다.
- [ ] Source-grounded 원칙은 유지한다.
- [ ] 세부 코드 암기형 질문은 금지한다.
- [ ] 채용 면접 프레이밍은 금지한다.
