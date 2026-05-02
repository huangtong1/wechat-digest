#!/usr/bin/env python3
"""
列出所有私聊微信号并保存到文件
"""
import argparse
import datetime
import hashlib
import json
import os
import re
import sqlite3
import sys
import tempfile

import zstandard

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from crypto.decrypt import full_decrypt, decrypt_wal
from crypto.config import load_config


cfg, keys_file = load_config()
with open(keys_file) as f:
    keys = json.load(f)

db_dir = cfg['db_dir']

enc_key = bytes.fromhex(keys['message/message_0.db']['enc_key'])
db_path = os.path.join(db_dir, 'message/message_0.db')
if not os.path.exists(db_path):
    print(f"数据库不存在: {db_path}", file=sys.stderr)
    sys.exit(1)

cache_dir = tempfile.mkdtemp(prefix='wechat-list-')
out_path = os.path.join(cache_dir, 'dec.db')
full_decrypt(db_path, out_path, enc_key)
wal_path = db_path + '-wal'
if os.path.exists(wal_path):
    decrypt_wal(wal_path, out_path, enc_key)

conn = sqlite3.connect(out_path)

private_users = conn.execute(
    "SELECT user_name FROM Name2Id WHERE user_name NOT LIKE '%@chatroom'"
).fetchall()

output_file = '/Users/linchengjian/Documents/trae_projects/PRD/wechat-digest/all-wechat-ids.txt'
with open(output_file, 'w') as f:
    f.write(f"找到 {len(private_users)} 个私聊微信号：\n")
    for (username,) in private_users:
        f.write(f"{username}\n")

print(f"已保存到 {output_file}", file=sys.stderr)

conn.close()
os.remove(out_path)