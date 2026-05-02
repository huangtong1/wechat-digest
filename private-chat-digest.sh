#!/bin/bash
#
# 单人私聊每日摘要脚本
# 从微信数据库提取与指定联系人的聊天记录，调用 LLM 做结构化总结
#
# 用法：
#   CONTACT_NAME="张三" bash private-chat-digest.sh
#   CONTACT_NAME="张三" bash private-chat-digest.sh 2026-04-09
#

set -euo pipefail

# ============ 等待微信启动 ============
MAX_WAIT=1800
WAIT_INTERVAL=30
waited=0
echo "$(date '+%Y-%m-%d %H:%M:%S') 等待微信启动..."
while ! pgrep -x "WeChat" > /dev/null 2>&1; do
    if [[ $waited -ge $MAX_WAIT ]]; then
        echo "等待超时，微信未启动，跳过本次摘要"
        exit 0
    fi
    sleep $WAIT_INTERVAL
    waited=$((waited + WAIT_INTERVAL))
    echo "  已等待 ${waited}s..."
done
echo "微信已启动，等待 2 分钟同步消息..."
sleep 120

# ============ 配置 ============
CONTACT_NAME="${CONTACT_NAME:-张三}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUTPUT_DIR="${OUTPUT_DIR:-$SCRIPT_DIR/output}"
HOUR_OFFSET=2
VOICE_ENGINE="${VOICE_ENGINE:-auto}"

# 日期：参数传入 或 默认昨天
if [[ $# -ge 1 ]]; then
    TARGET_DATE="$1"
else
    if [[ "$(uname)" == "Darwin" ]]; then
        TARGET_DATE=$(date -v-1d +%Y-%m-%d)
    else
        TARGET_DATE=$(date -d "yesterday" +%Y-%m-%d)
    fi
fi

echo "正在获取与「${CONTACT_NAME}」${TARGET_DATE} 的聊天记录..."

# ============ 提取聊天记录 ============
ENRICHED=$(mktemp /tmp/wechat-private-XXXXXX.txt)
trap "rm -f $ENRICHED" EXIT

python3 "${SCRIPT_DIR}/extract-private-chat.py" "$CONTACT_NAME" "$TARGET_DATE" \
    --hour-offset "$HOUR_OFFSET" --voice-engine "$VOICE_ENGINE" > "$ENRICHED" 2>/dev/null

total=$(grep -c "^\[" "$ENRICHED" || true)

if [[ $total -eq 0 ]]; then
    echo "${TARGET_DATE} 没有找到与「${CONTACT_NAME}」的聊天记录"
    exit 0
fi

# ============ 保存聊天记录 ============
mkdir -p "$OUTPUT_DIR"
CHAT_LOG="${OUTPUT_DIR}/${TARGET_DATE}-${CONTACT_NAME}-聊天记录.md"
cp "$ENRICHED" "$CHAT_LOG"
echo "$(date '+%H:%M:%S') 共 ${total} 条消息，聊天记录已保存到：${CHAT_LOG}"

# ============ 调用 LLM 总结 ============
if [[ -z "${LLM_CMD:-}" ]]; then
    echo ""
    echo "未配置 LLM_CMD 环境变量，跳过 AI 总结。"
    echo "如需自动总结，请设置 LLM_CMD，例如："
    echo "  export LLM_CMD=\"claude -p\""
    exit 0
fi

echo "$(date '+%H:%M:%S') 正在用 LLM 生成摘要..."

OUTPUT_FILE="${OUTPUT_DIR}/${TARGET_DATE}-${CONTACT_NAME}-摘要.md"

PROMPT_TEMPLATE="${SCRIPT_DIR}/private-chat-prompt-template.txt"
if [[ ! -f "$PROMPT_TEMPLATE" ]]; then
    echo "错误：找不到 prompt 模板文件 ${PROMPT_TEMPLATE}"
    exit 1
fi

PROMPT=$(sed \
    -e "s/{{CONTACT_NAME}}/${CONTACT_NAME}/g" \
    -e "s/{{TARGET_DATE}}/${TARGET_DATE}/g" \
    -e "s/{{TOTAL}}/${total}/g" \
    "$PROMPT_TEMPLATE")

{
    echo "$PROMPT"
    echo ""
    echo "--- 以下是聊天记录 ---"
    echo ""
    cat "$ENRICHED"
} | $LLM_CMD > "$OUTPUT_FILE"

echo "$(date '+%H:%M:%S') 摘要生成完毕"
echo "摘要：${OUTPUT_FILE}"
echo "聊天记录：${CHAT_LOG}"