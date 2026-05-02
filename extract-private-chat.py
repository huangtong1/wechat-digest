#!/usr/bin/env python3
"""
从微信数据库提取指定联系人的私聊消息。

用法：
  python3 extract-private-chat.py <contact_name> <date> [--hour-offset 2]

  --hour-offset N: 时间窗口从当天 N:00 到次日 N:00（默认 0）

例如：
  python3 extract-private-chat.py "张三" 2026-04-09 --hour-offset 2
  # 提取 2026-04-09 02:00 ~ 2026-04-10 02:00 与张三的私聊消息

依赖：
  pip3 install zstandard pycryptodome
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
    """从 contact.db 加载 username -> 显示名 和微信号 -> username 的映射"""
    enc_key = bytes.fromhex(keys['contact/contact.db']['enc_key'])
    db_path = os.path.join(db_dir, 'contact/contact.db')
    if not os.path.exists(db_path):
        return {}, {}

    cache_dir = tempfile.mkdtemp(prefix='wechat-contact-')
    out_path = os.path.join(cache_dir, 'dec.db')
    full_decrypt(db_path, out_path, enc_key)
    wal_path = db_path + '-wal'
    if os.path.exists(wal_path):
        decrypt_wal(wal_path, out_path, enc_key)

    conn = sqlite3.connect(out_path)
    rows = conn.execute("SELECT username, remark, nick_name, alias FROM contact").fetchall()
    conn.close()
    os.remove(out_path)

    names = {}
    aliases = {}
    for username, remark, nick_name, alias in rows:
        names[username] = remark or nick_name or username
        if alias:
            aliases[alias] = username
    return names, aliases


def find_contact_username(contact_name, contact_names, aliases):
    """通过备注名、昵称或微信号查找username"""
    # 1. 先通过备注名或昵称查找
    for username, display_name in contact_names.items():
        if display_name == contact_name:
            return username
    
    # 2. 通过微信号查找
    if contact_name in aliases:
        return aliases[contact_name]
    
    # 3. 如果输入的就是username，直接返回
    if contact_name in contact_names:
        return contact_name
    
    return None


def _load_voice_data(db_dir, keys, ts_start, ts_end):
    """从 media_0.db 加载语音二进制数据"""
    if 'message/media_0.db' not in keys:
        return {}
    enc_key = bytes.fromhex(keys['message/media_0.db']['enc_key'])
    db_path = os.path.join(db_dir, 'message/media_0.db')
    if not os.path.exists(db_path):
        return {}

    cache_dir = tempfile.mkdtemp(prefix='wechat-voice-')
    out_path = os.path.join(cache_dir, 'dec.db')
    try:
        full_decrypt(db_path, out_path, enc_key)
        wal_path = db_path + '-wal'
        if os.path.exists(wal_path):
            decrypt_wal(wal_path, out_path, enc_key)
        conn = sqlite3.connect(out_path)
        rows = conn.execute("""
            SELECT create_time, voice_data FROM VoiceInfo
            WHERE create_time >= ? AND create_time < ?
        """, (ts_start, ts_end)).fetchall()
        conn.close()
        return {ts: data for ts, data in rows}
    except Exception:
        return {}
    finally:
        try:
            os.remove(out_path)
        except OSError:
            pass


def _get_transcriber(voice_engine):
    """按需加载 VoiceTranscriber"""
    try:
        from voice_to_text import VoiceTranscriber
        return VoiceTranscriber(engine=voice_engine)
    except Exception:
        return None


def extract_private_chat(contact_username, target_date, hour_offset=0, voice_engine='auto'):
    """提取指定联系人的私聊消息"""
    cfg, keys_file = load_config()
    with open(keys_file) as f:
        keys = json.load(f)

    db_dir = cfg['db_dir']
    dctx = zstandard.ZstdDecompressor()

    base = datetime.datetime.strptime(target_date, '%Y-%m-%d')
    ts_start = int((base + datetime.timedelta(hours=hour_offset)).timestamp())
    ts_end = int((base + datetime.timedelta(days=1, hours=hour_offset)).timestamp())

    enc_key = bytes.fromhex(keys['message/message_0.db']['enc_key'])
    db_path = os.path.join(db_dir, 'message/message_0.db')
    if not os.path.exists(db_path):
        print(f"数据库不存在: {db_path}", file=sys.stderr)
        return []

    cache_dir = tempfile.mkdtemp(prefix='wechat-private-')
    out_path = os.path.join(cache_dir, 'dec.db')
    full_decrypt(db_path, out_path, enc_key)
    wal_path = db_path + '-wal'
    if os.path.exists(wal_path):
        decrypt_wal(wal_path, out_path, enc_key)

    conn = sqlite3.connect(out_path)

    contact_names, aliases = load_contact_names(db_dir, keys)
    table = 'Msg_' + hashlib.md5(contact_username.encode()).hexdigest()

    try:
        rows = conn.execute(f"""
            SELECT create_time, message_content, WCDB_CT_message_content, local_type
            FROM "{table}"
            WHERE create_time >= ? AND create_time < ?
            ORDER BY create_time
        """, (ts_start, ts_end)).fetchall()
    except sqlite3.OperationalError:
        print(f"表不存在: {table}", file=sys.stderr)
        conn.close()
        os.remove(out_path)
        return []

    conn.close()
    os.remove(out_path)

    voice_data_map = _load_voice_data(db_dir, keys, ts_start, ts_end)
    transcriber = _get_transcriber(voice_engine) if voice_data_map else None

    output_lines = []
    for ts, content, ct, lt in rows:
        real_type = lt & 0xFFFFFFFF
        if real_type not in (1, 34, 49):
            continue
        if not content:
            continue

        dt_str = datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M')

        try:
            if ct == 4:
                text = dctx.decompress(content).decode('utf-8', errors='replace')
            else:
                text = content if isinstance(content, str) else content.decode('utf-8', errors='replace')
        except Exception:
            continue

        if real_type == 1:
            if ':\n' in text:
                parts = text.split(':\n', 1)
                sender = contact_names.get(parts[0].strip(), parts[0].strip())
                msg = parts[1].strip()
            else:
                sender = '我'
                msg = text.strip()
            output_lines.append(f'[{dt_str}] {sender}: {msg}')

        elif real_type == 34:
            sender_m = re.search(r'fromusername="(.*?)"', text)
            sender_id = sender_m.group(1) if sender_m else None
            if sender_id:
                sender = contact_names.get(sender_id, sender_id)
            else:
                sender = '我'
            length_m = re.search(r'voicelength="(\d+)"', text)
            length_sec = int(length_m.group(1)) / 1000 if length_m else 0

            voice_bytes = voice_data_map.get(ts)
            transcribed = None
            if voice_bytes and transcriber:
                transcribed = transcriber.transcribe(voice_bytes)

            if transcribed:
                output_lines.append(f'[{dt_str}] {sender}: [语音] {transcribed}')
            else:
                output_lines.append(f'[{dt_str}] {sender}: [语音 {length_sec:.0f}秒]')

        elif real_type == 49:
            title_m = re.search(r'<title><!\[CDATA\[(.*?)\]\]></title>', text, re.DOTALL)
            if not title_m:
                title_m = re.search(r'<title>(.*?)</title>', text, re.DOTALL)
            url_m = re.search(r'<url><!\[CDATA\[(.*?)\]\]></url>', text, re.DOTALL)
            if not url_m:
                url_m = re.search(r'<url>(.*?)</url>', text, re.DOTALL)

            title = title_m.group(1).strip() if title_m else ''
            url = url_m.group(1).strip().replace('&amp;', '&') if url_m else ''

            if not title:
                continue

            sender_m = re.search(r'<fromusername>(.*?)</fromusername>', text)
            if sender_m:
                sender_id = sender_m.group(1)
                sender = contact_names.get(sender_id, sender_id)
            else:
                sender = '我'

            line = f'[{dt_str}] {sender}: [链接] {title}'
            if url and url.startswith('http'):
                line += f'\n  URL: {url}'
            output_lines.append(line)

    return output_lines


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='从微信数据库提取指定联系人的私聊消息')
    parser.add_argument('contact_name', help='联系人名称（备注名或昵称）')
    parser.add_argument('date', help='目标日期 (YYYY-MM-DD)')
    parser.add_argument('--hour-offset', type=int, default=0,
                        help='时间窗口偏移小时数（默认 0）')
    parser.add_argument('--voice-engine', choices=['auto', 'xfyun', 'whisper', 'none'],
                        default='auto', help='语音转写引擎（默认 auto）')
    args = parser.parse_args()

    cfg, keys_file = load_config()
    with open(keys_file) as f:
        keys = json.load(f)

    db_dir = cfg['db_dir']
    contact_names, aliases = load_contact_names(db_dir, keys)

    contact_username = find_contact_username(args.contact_name, contact_names, aliases)
    if not contact_username:
        print(f"找不到联系人「{args.contact_name}」", file=sys.stderr)
        print("提示：请使用备注名、昵称或微信号", file=sys.stderr)
        sys.exit(1)

    print(f"联系人: {args.contact_name} ({contact_username})", file=sys.stderr)
    print(f"时间窗口: {args.date} {args.hour_offset:02d}:00 ~ +1d {args.hour_offset:02d}:00", file=sys.stderr)

    lines = extract_private_chat(contact_username, args.date, args.hour_offset,
                                  voice_engine=args.voice_engine)
    print(f"提取 {len(lines)} 条消息", file=sys.stderr)

    print('\n'.join(lines))