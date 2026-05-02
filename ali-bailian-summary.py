#!/usr/bin/env python3
"""
阿里百炼模型调用脚本（OpenAI 兼容接口）
从 stdin 读取聊天记录，调用阿里百炼 API 生成摘要，输出到 stdout
"""

import sys
import os
from openai import OpenAI

# 配置参数
API_KEY = os.environ.get('ALI_BAILIAN_API_KEY', 'sk-sp-800b19b28daf4411b1f3954d389b9b37')
BASE_URL = os.environ.get('ALI_BAILIAN_BASE_URL', 'https://ark-cn-beijing.bytedance.net/api/v3')
MODEL_NAME = os.environ.get('ALI_BAILIAN_MODEL', 'gpt-4o')

if not API_KEY:
    print('Error: ALI_BAILIAN_API_KEY environment variable is required', file=sys.stderr)
    sys.exit(1)

# 从标准输入读取内容
input_content = sys.stdin.read()

# 构建提示词
prompt = f"请对以下微信聊天记录进行结构化总结，包括：\n1. 主要讨论话题及观点\n2. 重要信息和链接\n3. 参与人员及互动\n4. 总结结论\n\n聊天记录：\n{input_content}"

# 调用阿里百炼模型（OpenAI 兼容接口）
try:
    # 初始化客户端
    client = OpenAI(
        api_key=API_KEY,
        base_url=BASE_URL
    )
    
    # 生成摘要
    response = client.chat.completions.create(
        model=MODEL_NAME,
        messages=[
            {"role": "system", "content": "你是一个助手，负责总结微信聊天记录。"},
            {"role": "user", "content": prompt}
        ],
        temperature=0.7
    )
    
    # 输出结果
    print(response.choices[0].message.content)
except Exception as e:
    print(f'Error calling Ali Bailian API: {e}', file=sys.stderr)
    sys.exit(1)
