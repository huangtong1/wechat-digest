#!/usr/bin/env python3
"""
测试 LLM 集成
模拟 wechat-digest 的摘要生成流程
"""

import os
import subprocess
import tempfile

# 模拟聊天记录
mock_chat = """[2026-04-12 10:00] 张三: 今天讨论项目进度
[2026-04-12 10:05] 李四: 前端开发已完成 80%
[2026-04-12 10:10] 王五: 后端 API 接口已部署
[2026-04-12 10:15] 赵六: 测试用例已编写完成
[2026-04-12 10:20] 张三: 下周计划发布 v1.0 版本
"""

# 生成临时文件
with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
    f.write(mock_chat)
    chat_file = f.name

try:
    # 测试阿里百炼 LLM 集成
    print("测试阿里百炼 LLM 集成...")
    print("=" * 50)
    print("模拟聊天记录:")
    print(mock_chat)
    print("=" * 50)
    print("生成摘要:")
    
    # 调用阿里百炼模型
    result = subprocess.run(
        ['python3', 'ali-bailian-summary.py'],
        input=mock_chat,
        capture_output=True,
        text=True
    )
    
    if result.returncode == 0:
        print(result.stdout)
        print("\n✅ 测试成功！LLM 集成正常工作")
    else:
        print(f"❌ 测试失败: {result.stderr}")
        print("\n💡 提示: 请检查网络连接和 API 密钥配置")
        
finally:
    # 清理临时文件
    if os.path.exists(chat_file):
        os.remove(chat_file)
