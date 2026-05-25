"""
슬랙 검색 — 특정 키워드/사용자의 메시지를 cm-* (커머스팀) 채널에서 추출.

용도: 지수님이 요청한 개발 사항, 한샘님 의사결정, 특정 주제 추적 등.

수동 트리거 전용 (workflow_dispatch). 입력 파라미터:
- channel_prefix: 채널 접두어 (예: cm, ct)
- keywords: 쉼표 구분 키워드 (예: "스레드,키워드랭킹,개발,수정,버그")
- user_filter: 사용자 ID 또는 이름 (옵션, 빈 값이면 전체)
- days_back: 며칠 전부터 (기본 14일)
"""

import os
import sys
import argparse
from datetime import datetime, timedelta, timezone

from slack_sdk import WebClient as SlackClient
from slack_sdk.errors import SlackApiError

KST = timezone(timedelta(hours=9))


def get_env(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        raise RuntimeError(f"환경 변수 {name} 누락")
    return v


SLACK_BOT_TOKEN = get_env("BOS_SLACK_BOT_TOKEN")
SLACK_CHANNEL_ID = get_env("BOS_SLACK_CHANNEL_ID")
slack = SlackClient(token=SLACK_BOT_TOKEN)


def get_user_name(user_id: str, cache: dict) -> str:
    if user_id in cache:
        return cache[user_id]
    try:
        info = slack.users_info(user=user_id)
        name = info["user"].get("real_name") or info["user"].get("name", user_id)
        cache[user_id] = name
        return name
    except SlackApiError:
        return user_id


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--channel-prefix", default="cm", help="채널 접두어 (cm, ct 등)")
    parser.add_argument("--keywords", default="스레드,키워드랭킹,개발,수정,버그,추가,기능,개선", help="키워드 쉼표 구분")
    parser.add_argument("--user-filter", default="지수", help="사용자 이름 부분 매칭 (빈 값=전체)")
    parser.add_argument("--days-back", type=int, default=14, help="며칠 전부터")
    args = parser.parse_args()

    keywords = [k.strip() for k in args.keywords.split(",") if k.strip()]
    user_filter = args.user_filter.strip() if args.user_filter else None
    oldest_ts = (datetime.now(KST) - timedelta(days=args.days_back)).timestamp()

    print(f"🔍 검색 조건: channel={args.channel_prefix}-*, keywords={keywords}, user={user_filter}, days_back={args.days_back}")

    # 1. 채널 목록
    channels = []
    cursor = None
    while True:
        resp = slack.conversations_list(types="public_channel,private_channel", limit=200, cursor=cursor)
        channels.extend(resp["channels"])
        cursor = resp.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            break
    target_channels = [c for c in channels if c.get("is_member") and c["name"].startswith(args.channel_prefix + "-")]
    print(f"✅ 타겟 채널 {len(target_channels)}개")

    # 2. 메시지 검색
    user_cache = {}
    matches = []
    for ch in target_channels:
        try:
            resp = slack.conversations_history(channel=ch["id"], oldest=str(oldest_ts), limit=500)
            for m in resp.get("messages", []):
                if m.get("subtype"):
                    continue
                text = m.get("text", "")
                user_id = m.get("user", "unknown")

                # 사용자 필터
                if user_filter:
                    user_name = get_user_name(user_id, user_cache)
                    if user_filter not in user_name and user_filter not in user_id:
                        continue
                else:
                    user_name = get_user_name(user_id, user_cache)

                # 키워드 매칭
                matched_kws = [kw for kw in keywords if kw in text]
                if not matched_kws:
                    continue

                ts = float(m["ts"])
                dt = datetime.fromtimestamp(ts, KST).strftime("%m/%d %H:%M")
                matches.append({
                    "channel": ch["name"],
                    "user": user_name,
                    "time": dt,
                    "text": text[:400],
                    "matched": matched_kws,
                })
        except SlackApiError as e:
            print(f"⚠️ #{ch['name']} 실패: {e.response['error']}")
            continue

    # 3. 리포트
    print(f"✅ {len(matches)}개 메시지 매칭")
    if not matches:
        slack.chat_postMessage(
            channel=SLACK_CHANNEL_ID,
            text=f"🔍 검색 결과 없음 (channel_prefix={args.channel_prefix}, keywords={args.keywords}, user={args.user_filter})",
        )
        return

    # 채널별 그룹화
    by_channel = {}
    for m in matches:
        by_channel.setdefault(m["channel"], []).append(m)

    lines = [
        f"🔍 *슬랙 검색 결과 — {datetime.now(KST).strftime('%Y-%m-%d %H:%M')}*",
        f"",
        f"• 채널: `{args.channel_prefix}-*` ({len(target_channels)}개)",
        f"• 사용자: `{args.user_filter or '전체'}`",
        f"• 키워드: `{', '.join(keywords)}`",
        f"• 기간: 지난 {args.days_back}일",
        f"• 매칭: *{len(matches)}건*",
        f"",
    ]

    for ch_name in sorted(by_channel.keys()):
        msgs = by_channel[ch_name]
        lines.append(f"\n*#{ch_name}* ({len(msgs)}건)")
        for m in msgs[:20]:
            kws = ", ".join(f"`{k}`" for k in m["matched"])
            lines.append(f"  • [{m['time']}] {m['user']} ({kws})")
            lines.append(f"    > {m['text']}")

    # Slack 4000자 청크
    report = "\n".join(lines)
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

    for i, chunk in enumerate(chunks, 1):
        prefix = "" if i == 1 else f"_(이어서 {i}/{len(chunks)})_\n\n"
        slack.chat_postMessage(channel=SLACK_CHANNEL_ID, text=prefix + chunk)
    print(f"✅ 슬랙 발송 ({len(chunks)} 청크)")


if __name__ == "__main__":
    main()
