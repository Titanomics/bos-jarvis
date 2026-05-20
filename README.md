# BOS자비스

기린컴퍼니의 **AI 파트너 시스템**. BOS 12주 프레임을 통달한 30년차 컨설턴트가 24/7 상주하며 외부 클라이언트 컨설팅 + 자기 회사 진단을 동시 수행.

## 비전

> **BOS 강의 + 컨설팅 경험 + 일상 운영 데이터를 AI 파트너 1명에 통합. 외부 컨설팅과 자가 진단 둘 다.**

## kirin-slack-bot과의 차이 (중요)

| | kirin-slack-bot | BOS자비스 |
|--|---|---|
| 역할 | 데이터 보여주기 (간트차트 + 다이제스트) | **데이터로 사고하기 + 컨설팅** |
| 데이터 source | Notion 두 DB | 슬랙 대화 + vault + BOS 지식 + 미팅 녹음 |
| 분석 엔진 | Python 통계 | Claude API + BOS 12주 프레임 |
| 출력 | 매일 09/12/15/18시 데이터 알림 | 주간 자가 진단 + 외부 컨설팅 리포트 |

→ **완전히 다른 시스템**. 같은 슬랙 워크스페이스에 살지만 역할 절대 겹치면 안 됨.

## 운영 모드 (2가지)

### 모드 1: 자가 진단 (자기 회사)
- **주기**: 매주 일요일 19:30 KST 자동 + 본인 요청 시
- **데이터**: 슬랙 운영 채널 대화 history + 옵시디언 vault (decision-log, business-dashboard, 회의록)
- **출력**: BOS 12차원 진단 리포트 → BOS자비스 슬랙 채널

### 모드 2: 외부 컨설팅 (클라이언트 병원)
- **트리거**: 본인이 클라이언트 자료 입력 시
- **데이터**: 클라이언트 자료 (재무/조직도/마케팅) + BOS 12주 프레임
- **출력**: 1차 진단 리포트 (강점/약점/리스크 + 90일 액션 3개)

## 셋업 현황 (2026-05-20 23:28 기준)

### ✅ 완료
- 슬랙 봇 생성 (`BOS자비스`, App Home 설정 완료)
- Bot Token Scopes: `chat:write`, `chat:write.public`, `files:write`, `channels:read`, `channels:history`, `groups:history`, `app_mentions:read`, `commands`, `users:read`
- Socket Mode 활성화 (App-Level Token 발급)
- BOS자비스 슬랙 채널 + 봇 초대
- 본 repo 생성
- GitHub Secrets:
  - `BOS_SLACK_BOT_TOKEN` (xoxb-...)
  - `BOS_SLACK_APP_TOKEN` (xapp-...)
  - `BOS_SLACK_CHANNEL_ID`

### 🔴 W22 시작 시 필요
- `ANTHROPIC_API_KEY` GitHub Secret 추가 (Claude API)
- 모니터링 대상 슬랙 채널 결정 + 봇 초대 (cm-05-big3 등)
- 옵시디언 vault → repo 통합 방식 결정 (서브모듈 / 복사 / S3 sync 등)
- BOS 12주 강의 자료 vault에 정리 완료

## 다음 단계

상세 로드맵 → [ROADMAP.md](ROADMAP.md)
아키텍처 → [ARCHITECTURE.md](ARCHITECTURE.md)

## 관련 문서 (옵시디언 vault)

- `05-resources/bos-jarvis-concept.md` — 컨셉 풀버전 (5/19 명명)
- `05-resources/bos-system/` — BOS 12주 강의 자료
- `03-projects/kirin-slack-bot-status.md` — 자매 봇 상태
