#!/usr/bin/env python3
"""
列出所有联系人的显示名和微信号
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


def load_contact_names(db_dir, keys):
    """从 contact.db 加载 username -> 显示名 的映射"""
    enc_key = bytes.fromhex(keys['contact/contact.db']['enc_key'])
    db_path = os.path.join(db_dir, 'contact/contact.db')
    if not os.path.exists(db_path):
        print("contact.db 不存在，将使用 username 作为显示名", file=sys.stderr)
        return {}

    cache_dir = tempfile.mkdtemp(prefix='wechat-contact-')
    out_path = os.path.join(cache_dir, 'dec.db')
    full_decrypt(db_path, out_path, enc_key)
    wal_path = db_path + '-wal'
    if os.path.exists(wal_path):
        decrypt_wal(wal_path, out_path, enc_key)

    conn = sqlite3.connect(out_path)
    rows = conn.execute("SELECT username, remark, nick_name FROM contact").fetchall()
    conn.close()
    os.remove(out_path)

    names = {}
    for username, remark, nick_name in rows:
        names[username] = remark or nick_name or username
    return names


cfg, keys_file = load_config()
with open(keys_file) as f:
    keys = json.load(f)

db_dir = cfg['db_dir']

contact_names = load_contact_names(db_dir, keys)

output_file = '/Users/linchengjian/Documents/trae_projects/PRD/wechat-digest/all-contacts.txt'
with open(output_file, 'w') as f:
    f.write(f"找到 {len(contact_names)} 个联系人：\n\n")
    for username, display_name in sorted(contact_names.items(), key=lambda x: x[1]):
        f.write(f"{display_name} ({username})\n")

print(f"已保存到 {output_file}", file=sys.stderr)