# 아키텍처

## 4-Layer 구조

```
┌────────────────────────────────────────────────────────┐
│  Layer 1: 입력 (Inputs)                                │
│                                                        │
│  A. 슬랙 대화 history (groups:history, channels:hist) │
│     - 운영 채널: cm-05-big3, cm-00-일정관리 등         │
│     - 회의 채널 (별도 정리 필요)                       │
│                                                        │
│  B. 옵시디언 vault                                     │
│     - 03-projects/business-dashboard.md (KPI)         │
│     - 03-projects/decision-log.md (의사결정)          │
│     - 02-daily-notes/ (일일 노트)                      │
│     - 03-projects/meeting-*.md (회의록)                │
│                                                        │
│  C. BOS 지식 베이스                                    │
│     - 05-resources/bos-system/ (강의 자료 12주)        │
│     - case-studies/ (컨설팅 사례)                      │
│                                                        │
│  D. 음성 입력 (Phase 0~)                               │
│     - 강의 녹음 → STT                                  │
│     - 미팅 녹음 → STT                                  │
└────────────────────────────────────────────────────────┘
                          ↓
┌────────────────────────────────────────────────────────┐
│  Layer 2: 지식 자동 정리 (Curator)                     │
│                                                        │
│  - 새 vault 파일 감지 → BOS 컨텍스트 갱신             │
│  - 슬랙 메시지 → 회의/결정/일상 분류                  │
│  - 오디오 → STT → 적절한 vault 위치 자동 저장         │
│  - 중복 제거 + 인덱싱                                  │
└────────────────────────────────────────────────────────┘
                          ↓
┌────────────────────────────────────────────────────────┐
│  Layer 3: BOS자비스 코어 (Reasoning Engine)            │
│                                                        │
│  - 페르소나: 30년차 BOS 컨설턴트 + 병원경영전문       │
│  - 엔진: Claude API (claude-opus-4-7)                  │
│  - 프롬프트: BOS 12주 프레임 시스템 프롬프트          │
│  - 출력 형식: 진단 + 처방 (액션 3개) + 리스크 +       │
│              다음 점검 시점                            │
│                                                        │
│  Skills (Slash commands):                              │
│  - /bos-진단 : 자가 진단 (수동 트리거)                │
│  - /bos-컨설팅 : 외부 컨설팅 모드                     │
│  - /bos-인사이트 : 최근 인사이트 조회                  │
└────────────────────────────────────────────────────────┘
                          ↓
┌────────────────────────────────────────────────────────┐
│  Layer 4: 출력 (Outputs)                               │
│                                                        │
│  A. 슬랙 (BOS자비스 채널)                              │
│     - 주간 자가 진단 (일요일 19:30 자동)               │
│     - 슬래시 명령 응답                                 │
│     - 멘션 응답 (@BOS자비스)                           │
│                                                        │
│  B. 옵시디언 vault                                     │
│     - 진단 리포트 자동 저장                            │
│     - 결정 추출 → decision-log.md                     │
│                                                        │
│  C. PDF (Phase 3, 클라이언트 발표용)                  │
└────────────────────────────────────────────────────────┘
```

## 데이터 흐름

### 자가 진단 모드 (매주 일요일)

```
1. GitHub Actions cron 트리거 (일요일 19:30 KST)
   ↓
2. 슬랙 API: 운영 채널들 1주간 메시지 fetch
   ↓
3. 옵시디언 vault: business-dashboard, decision-log, 최근 회의록 read
   ↓
4. BOS 12주 프레임 + 위 데이터 → Claude API 진단 요청
   ↓
5. Claude 응답: 12차원 진단 + 액션 3개 + 리스크
   ↓
6. 슬랙 BOS자비스 채널에 발송
   ↓
7. vault에 진단 리포트 저장 (03-projects/bos-diagnostics/W{N}.md)
```

### 외부 컨설팅 모드

```
1. 본인이 클라이언트 자료 작성 (template 기반)
   - 재무 (매출, 광고비, 인건비)
   - 조직도
   - 마케팅 현황
   ↓
2. /bos-컨설팅 클라이언트={이름} 슬래시 명령 또는 수동 실행
   ↓
3. Claude API 진단 (BOS 프레임 적용)
   ↓
4. 리포트 생성 → 슬랙 + PDF
   ↓
5. 본인 + 정익님 검토 후 클라이언트 발표
```

## 기술 스택

| Layer | 기술 |
|-------|------|
| Slack API | slack-sdk (Python) + Slack App (Bot Token + App Token) |
| 슬랙 메시지 fetch | conversations.history endpoint |
| Notion API (옵션) | requests + Notion API 2025-09-03 |
| 옵시디언 vault 통합 | 미정 (검토 필요): git submodule / S3 sync / 직접 push |
| 분석 엔진 | Anthropic SDK + claude-opus-4-7 |
| 호스팅 | GitHub Actions (cron 주간 발송) |
| Phase 1b 호스팅 (Socket Mode) | Railway / Fly.io (실시간 응답 시) |

## 옵시디언 vault 통합 — 검토 필요

GitHub Actions는 본인 로컬 vault에 접근 불가. 대안:

| 방안 | 장점 | 단점 |
|------|------|------|
| **A. vault 일부를 별도 repo로** | 단순 | vault 동기화 수동 |
| **B. 옵시디언 sync → S3 → GitHub Actions에서 fetch** | 자동 동기화 | S3 비용 ($0.5/월) + 복잡도 |
| **C. 본인 PC에 BOS자비스 호스팅** | vault 직접 read | PC 24/7 켜져야 함 |
| **D. 옵시디언 Sync API + 토큰** | 옵시디언 공식 | 유료 ($4/월), 미검증 |

→ W22 시작 시 결정.

## 보안

- 모든 토큰: GitHub Secrets에만 저장
- 클라이언트 컨설팅 데이터: 외부 노출 금지 (별도 private 처리)
- 슬랙 채널 모니터링 대상: 본인이 명시적 결정한 채널만
