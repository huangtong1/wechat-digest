#!/usr/bin/env python3
"""
测试 OpenAI 兼容接口
"""

import os
from openai import OpenAI

# 配置
api_key = "sk-sp-800b19b28daf4411b1f3954d389b9b37"
# 阿里百炼 OpenAI 兼容接口地址
base_url = "https://ark-cn-beijing.bytedance.net/api/v3"

# 初始化客户端
client = OpenAI(
    api_key=api_key,
    base_url=base_url
)

# 测试消息
messages = [
    {"role": "system", "content": "你是一个助手，负责总结微信聊天记录。"},
    {"role": "user", "content": "测试消息：今天讨论了项目进度和下周计划"}
]

# 调用模型
try:
    response = client.chat.completions.create(
        model="gpt-4o",  # 替换为实际支持的模型
        messages=messages,
        temperature=0.7
    )
    print("测试成功！")
    print("回复:", response.choices[0].message.content)
except Exception as e:
    print(f"测试失败: {e}")
