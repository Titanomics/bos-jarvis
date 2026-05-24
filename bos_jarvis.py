"""
BOS자비스 — 주간 자가 진단 자동화

매주 일요일 19:30 KST 자동 실행 (또는 수동 트리거).

흐름:
1. kirin-vault-sync repo clone (VAULT_SYNC_TOKEN)
2. vault 핵심 파일 read (의사결정 로그, 대시보드, 최근 일일 노트, 회의록)
3. 슬랙 채널 history fetch (지난 7일, 전 채널 + DM)
4. PERSONA + KNOWLEDGE_BASE + DIAGNOSTIC_MATRIX + 데이터 → Claude API
5. BOS 12차원 진단 리포트 생성
6. 슬랙 BOS자비스 채널에 발송
"""

import os
import sys
import argparse
import subprocess
import shutil
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from anthropic import Anthropic
from slack_sdk import WebClient as SlackClient
from slack_sdk.errors import SlackApiError

KST = timezone(timedelta(hours=9))
TODAY = datetime.now(KST).strftime("%Y-%m-%d (%a)")
WEEK_AGO = (datetime.now(KST) - timedelta(days=7)).isoformat()
WEEK_AGO_TS = (datetime.now(KST) - timedelta(days=7)).timestamp()


# --------------------------------------------------------------------------- #
# Env
# --------------------------------------------------------------------------- #
def get_env(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        raise RuntimeError(f"환경 변수 {name} 누락")
    return v


ANTHROPIC_API_KEY = get_env("ANTHROPIC_API_KEY")
SLACK_BOT_TOKEN = get_env("BOS_SLACK_BOT_TOKEN")
SLACK_CHANNEL_ID = get_env("BOS_SLACK_CHANNEL_ID")
VAULT_SYNC_TOKEN = get_env("VAULT_SYNC_TOKEN")
VAULT_REPO = "Titanomics/kirin-vault-sync"

claude = Anthropic(api_key=ANTHROPIC_API_KEY)
slack = SlackClient(token=SLACK_BOT_TOKEN)


# --------------------------------------------------------------------------- #
# Vault clone & read
# --------------------------------------------------------------------------- #
def clone_vault() -> Path:
    """kirin-vault-sync repo를 temp dir에 clone."""
    tmp = Path(tempfile.mkdtemp(prefix="vault-"))
    url = f"https://x-access-token:{VAULT_SYNC_TOKEN}@github.com/{VAULT_REPO}.git"
    subprocess.run(
        ["git", "clone", "--depth", "1", url, str(tmp)],
        check=True,
        capture_output=True,
    )
    print(f"✅ vault clone → {tmp}")
    return tmp


def safe_read(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except Exception as e:
        return f"(읽기 실패: {e})"


def collect_vault_data(vault: Path) -> dict[str, str]:
    """vault 핵심 파일을 dict로 모은다."""
    data = {}

    # 사업 대시보드 + 의사결정 로그 (최우선)
    data["business_dashboard"] = safe_read(vault / "03-projects/business-dashboard.md")
    data["decision_log"] = safe_read(vault / "03-projects/decision-log.md")

    # 메모리 (피드백 + 프로젝트 컨텍스트)
    memory_dir = vault / ".claude-memory"
    if memory_dir.exists():
        memory_parts = []
        for f in sorted(memory_dir.glob("*.md")):
            memory_parts.append(f"### {f.name}\n\n{safe_read(f)}")
        data["memory"] = "\n\n---\n\n".join(memory_parts)

    # 최근 일일 노트 (지난 14일)
    today = datetime.now(KST).date()
    daily_parts = []
    for days_back in range(14):
        d = today - timedelta(days=days_back)
        path = vault / f"02-daily-notes/{d.year}/{d.month:02d}/{d.isoformat()}.md"
        if path.exists():
            daily_parts.append(f"### {d.isoformat()}\n\n{safe_read(path)}")
    data["recent_daily_notes"] = "\n\n---\n\n".join(daily_parts) if daily_parts else "(최근 일일 노트 없음)"

    # 최근 주간 리뷰 (last 4)
    weekly_parts = []
    weekly_dir = vault / f"02-daily-notes/{today.year}/{today.month:02d}"
    if weekly_dir.exists():
        for f in sorted(weekly_dir.glob("weekly-*.md"))[-4:]:
            weekly_parts.append(f"### {f.name}\n\n{safe_read(f)}")
    data["recent_weekly_reviews"] = "\n\n---\n\n".join(weekly_parts) if weekly_parts else "(최근 주간 리뷰 없음)"

    # 회의록 (최근 1개월)
    meeting_parts = []
    project_dir = vault / "03-projects"
    if project_dir.exists():
        for f in sorted(project_dir.glob("meeting-*.md")):
            mtime = datetime.fromtimestamp(f.stat().st_mtime)
            if mtime >= datetime.now() - timedelta(days=30):
                meeting_parts.append(f"### {f.name}\n\n{safe_read(f)}")
    data["recent_meetings"] = "\n\n---\n\n".join(meeting_parts) if meeting_parts else "(최근 회의록 없음)"

    # BOS자비스 지식 베이스 (페르소나가 참조)
    bos_dir = vault / "05-resources/bos-system"
    data["bos_knowledge_base"] = safe_read(bos_dir / "bos-12-week-knowledge-base.md")
    data["bos_diagnostic_matrix"] = safe_read(bos_dir / "bos-diagnostic-12-matrix.md")
    data["bos_textbook_w3"] = safe_read(bos_dir / "textbook-w3-corevalue.md")
    data["bos_case_hospital"] = safe_read(bos_dir / "case-hospital-diagnostic.md")
    data["bos_textbook_position"] = safe_read(bos_dir / "textbook-work-environment-design.md")

    # 5월 결정 보드 (있으면)
    data["may_decisions"] = safe_read(vault / "03-projects/may-2026-decisions.md")

    return data


# --------------------------------------------------------------------------- #
# Slack history fetch
# --------------------------------------------------------------------------- #
def fetch_slack_history() -> str:
    """전 채널 + DM 지난 7일 메시지 fetch."""
    sections = []

    # 1. 채널 list (public + private)
    try:
        channels = []
        cursor = None
        while True:
            resp = slack.conversations_list(
                types="public_channel,private_channel",
                limit=200,
                cursor=cursor,
            )
            channels.extend(resp["channels"])
            cursor = resp.get("response_metadata", {}).get("next_cursor")
            if not cursor:
                break
        # 봇이 멤버인 채널만
        channels = [c for c in channels if c.get("is_member")]
        print(f"✅ 멤버 채널 {len(channels)}개 발견")
    except SlackApiError as e:
        print(f"⚠️ 채널 리스트 실패: {e.response['error']}")
        channels = []

    # 2. 각 채널 history (지난 7일)
    for ch in channels:
        ch_id = ch["id"]
        ch_name = ch["name"]
        try:
            resp = slack.conversations_history(
                channel=ch_id,
                oldest=str(WEEK_AGO_TS),
                limit=200,
            )
            msgs = resp.get("messages", [])
            if not msgs:
                continue
            msg_texts = []
            for m in msgs:
                if m.get("subtype"):  # skip system messages
                    continue
                user = m.get("user", "unknown")
                text = m.get("text", "")[:500]  # truncate per message
                if text.strip():
                    msg_texts.append(f"- [{user}] {text}")
            if msg_texts:
                sections.append(f"### #{ch_name} ({len(msg_texts)}개 메시지)\n\n" + "\n".join(msg_texts[-50:]))
        except SlackApiError as e:
            err = e.response["error"]
            if err not in ("not_in_channel", "channel_not_found"):
                print(f"⚠️ #{ch_name} history 실패: {err}")
            continue

    # 3. DMs (지난 7일)
    try:
        resp = slack.conversations_list(types="im", limit=200)
        for im in resp.get("channels", []):
            im_id = im["id"]
            user = im.get("user", "unknown")
            try:
                msg_resp = slack.conversations_history(channel=im_id, oldest=str(WEEK_AGO_TS), limit=50)
                msgs = msg_resp.get("messages", [])
                msg_texts = [f"- [{m.get('user', 'unknown')}] {m.get('text', '')[:500]}" for m in msgs if m.get("text")]
                if msg_texts:
                    sections.append(f"### DM with {user} ({len(msg_texts)}개)\n\n" + "\n".join(msg_texts[-20:]))
            except SlackApiError:
                continue
    except SlackApiError as e:
        print(f"⚠️ DM list 실패: {e.response['error']}")

    return "\n\n---\n\n".join(sections) if sections else "(지난 7일 슬랙 메시지 없음)"


# --------------------------------------------------------------------------- #
# Claude API
# --------------------------------------------------------------------------- #
def build_system_prompt(data: dict[str, str]) -> str:
    """PERSONA + 지식 베이스 + 진단 매트릭스 결합."""
    persona_path = Path(__file__).parent / "PERSONA.md"
    persona = safe_read(persona_path)

    return f"""{persona}

---

# 📚 BOS 지식 베이스 (12주 강의 통합)

{data.get('bos_knowledge_base', '')}

---

# 📊 BOS 12차원 진단 매트릭스

{data.get('bos_diagnostic_matrix', '')}

---

# 📖 W3 핵심가치 교안 (보강)

{data.get('bos_textbook_w3', '')}

---

# 🏥 병원 컨설팅 사례 (외부 컨설팅 참고)

{data.get('bos_case_hospital', '')}

---

# 📝 W4-W5 포지션 개약서 교안 (보강)

{data.get('bos_textbook_position', '')}
"""


def build_user_message(data: dict[str, str], slack_history: str) -> str:
    """진단에 사용할 모든 데이터를 user message로 구성."""
    return f"""# 기린컴퍼니 자가 진단 — {TODAY}

오늘 일요일이고, 매주 일요일 19:30 KST 정기 자가 진단 시점입니다.

아래 데이터를 종합해서 BOS 12차원 진단 리포트를 작성해주세요. PERSONA.md에 명시된 출력 형식을 따르세요.

## 사업 대시보드 (현재 KPI + 팀 + 마일스톤)

{data.get('business_dashboard', '(없음)')}

---

## 의사결정 로그 (최근 결정 + 근거)

{data.get('decision_log', '(없음)')}

---

## 5월 결정 보드

{data.get('may_decisions', '(없음)')}

---

## 메모리 (사용자 프로필 + 피드백 + 프로젝트 컨텍스트)

{data.get('memory', '(없음)')[:30000]}

---

## 최근 일일 노트 (지난 14일)

{data.get('recent_daily_notes', '(없음)')[:30000]}

---

## 최근 주간 리뷰

{data.get('recent_weekly_reviews', '(없음)')}

---

## 최근 회의록 (지난 30일)

{data.get('recent_meetings', '(없음)')[:20000]}

---

## 슬랙 채널 History (지난 7일, 전 채널 + DM)

{slack_history[:30000]}

---

# 진단 요청

위 데이터를 종합해서 다음을 작성해주세요:

1. **종합 점수**: 12차원 🟢🟡🔴 분포
2. **차원별 결과 테이블** (W1~W12, 점수, 핵심 시그널)
3. **이번 주 가장 큰 변화** (긍정 + 우려)
4. **90일 처방 액션 3개** (담당자 + 기한 명시)
5. **다음 점검 시점**
6. **🔥 추가 알림** (임박한 D-Day, 결정 보드 D-7, 4/30 후속 등)

PERSONA.md 출력 형식 그대로. 한국어. 데이터 부족 시 명시. 추정 금지.
"""


def call_claude(system_prompt: str, user_message: str) -> str:
    print("🤖 Claude API 호출 중...")
    resp = claude.messages.create(
        model="claude-opus-4-7",
        max_tokens=8000,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )
    return resp.content[0].text


# --------------------------------------------------------------------------- #
# Slack post
# --------------------------------------------------------------------------- #
def post_to_slack(report: str):
    """슬랙 메시지 4000자 제한 → chunked 발송."""
    chunks = []
    current = ""
    for line in report.split("\n"):
        if len(current) + len(line) + 1 > 3800:
            chunks.append(current)
            current = line + "\n"
        else:
            current += line + "\n"
    if current:
        chunks.append(current)

    print(f"📤 슬랙 발송 ({len(chunks)} 청크)")
    for i, chunk in enumerate(chunks, 1):
        prefix = "" if i == 1 else f"_(이어서 {i}/{len(chunks)})_\n\n"
        slack.chat_postMessage(channel=SLACK_CHANNEL_ID, text=prefix + chunk)
    print("✅ 슬랙 발송 완료")


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def build_dry_run_report(data: dict[str, str], slack_history: str, system_prompt: str, user_message: str) -> str:
    """Claude API 호출 없이 fetch 결과만 요약."""
    # Vault 파일별 사이즈
    vault_summary = []
    for key, val in data.items():
        if val:
            preview = val.split("\n")[0][:100] if val else "(빈 값)"
            vault_summary.append(f"  • `{key}`: {len(val):,} chars — {preview}")
        else:
            vault_summary.append(f"  • `{key}`: (없음)")

    # 슬랙 채널 추출 (sections에서 ### 헤더)
    slack_channels = []
    for line in slack_history.split("\n"):
        if line.startswith("### "):
            slack_channels.append(f"  • {line[4:]}")

    # 토큰 추정 (대략 1 token = 3.5 chars for 한국어)
    total_input_chars = len(system_prompt) + len(user_message)
    estimated_tokens = total_input_chars // 3
    opus_cost = (estimated_tokens / 1_000_000) * 15  # $15 per 1M input
    sonnet_cost = (estimated_tokens / 1_000_000) * 3

    return f"""🔍 *BOS자비스 Dry-Run 검증 — {TODAY}*

Claude API 호출 X. fetch한 데이터만 요약.

---

*📁 Vault 데이터 ({sum(len(v) for v in data.values()):,} chars)*

{chr(10).join(vault_summary)}

---

*💬 슬랙 History ({len(slack_history):,} chars)*

봇이 멤버로 있는 채널 + DM에서 지난 7일 메시지:

{chr(10).join(slack_channels) if slack_channels else "  (메시지 없음 — 봇이 채널에 초대 안 됐을 가능성)"}

---

*🧮 토큰/비용 추정*

• 총 입력 chars: `{total_input_chars:,}`
• 추정 input tokens: `~{estimated_tokens:,}` (한국어 1 token ≈ 3 chars)
• 추정 출력 tokens: `~5,000`
• 비용 추정:
  - Opus 4.7: **~${opus_cost + 0.375:.2f}** (input ${opus_cost:.2f} + output $0.375)
  - Sonnet 4.6: **~${sonnet_cost + 0.075:.2f}**
  - Haiku 4.5: **~${(estimated_tokens / 1_000_000) * 0.8 + 0.02:.2f}**

---

*✅ 다음 액션*

1. 위 데이터가 충분한지 확인 (vault 핵심 파일 모두 fetch됐는지)
2. 슬랙 채널 누락이 없는지 (필요한 채널에 봇 초대됐는지)
3. 비용이 OK면 → Actions에서 다시 트리거 (`dry_run`을 `false`로) → 진짜 진단 발송

문제 있으면: 어떤 데이터 누락? 어떤 채널 추가 필요? 알려주세요.
"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Claude API 호출 X, fetch 결과만 슬랙에 발송")
    args = parser.parse_args()

    mode = "🔍 DRY-RUN" if args.dry_run else "🤖 REAL"
    print(f"{mode} BOS자비스 시작 — {datetime.now(KST).isoformat()}")

    vault = None
    try:
        # 1. vault clone
        vault = clone_vault()
        data = collect_vault_data(vault)
        print(f"✅ vault 데이터 수집 ({sum(len(v) for v in data.values())} chars)")

        # 2. 슬랙 history
        slack_history = fetch_slack_history()
        print(f"✅ 슬랙 history ({len(slack_history)} chars)")

        # 3. 시스템 프롬프트 + 사용자 메시지 구성
        system_prompt = build_system_prompt(data)
        user_message = build_user_message(data, slack_history)
        print(f"📊 시스템 프롬프트 {len(system_prompt)} chars / 사용자 메시지 {len(user_message)} chars")

        if args.dry_run:
            # Dry-run: API 호출 X, 데이터 요약 발송
            report = build_dry_run_report(data, slack_history, system_prompt, user_message)
            print("🔍 Dry-run 리포트 생성 (Claude API 호출 X)")
        else:
            # 실제 진단
            report = call_claude(system_prompt, user_message)
            print(f"✅ 진단 리포트 생성 ({len(report)} chars)")

        # 4. 슬랙 발송
        post_to_slack(report)

    finally:
        # vault temp 정리
        if vault and vault.exists():
            shutil.rmtree(vault, ignore_errors=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"❌ 실패: {e}")
        # 슬랙에 실패 알림 (옵션)
        try:
            slack.chat_postMessage(
                channel=SLACK_CHANNEL_ID,
                text=f"⚠️ BOS자비스 주간 진단 실패: {type(e).__name__}: {e}\n로그: GitHub Actions",
            )
        except Exception:
            pass
        sys.exit(1)
