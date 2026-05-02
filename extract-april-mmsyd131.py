#!/usr/bin/env python3
"""
提取4月份与 mmsyd131 的所有聊天记录
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


def _load_voice_data(db_dir, keys, ts_start, ts_end):
    """从 media_0.db 加载语音二进制数据，返回 {create_time: voice_data}"""
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


def extract_all_private(target_date, hour_offset=0, min_messages=1, voice_engine='auto'):
    """提取所有私聊消息，返回 {username: [(timestamp, sender, text), ...]}"""
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
        return {}, {}

    cache_dir = tempfile.mkdtemp(prefix='wechat-private-')
    out_path = os.path.join(cache_dir, 'dec.db')
    full_decrypt(db_path, out_path, enc_key)
    wal_path = db_path + '-wal'
    if os.path.exists(wal_path):
        decrypt_wal(wal_path, out_path, enc_key)

    conn = sqlite3.connect(out_path)

    private_users = conn.execute(
        "SELECT user_name FROM Name2Id WHERE user_name NOT LIKE '%@chatroom'"
    ).fetchall()

    contact_names = load_contact_names(db_dir, keys)

    voice_data_map = _load_voice_data(db_dir, keys, ts_start, ts_end)
    transcriber = _get_transcriber(voice_engine) if voice_data_map else None

    all_chats = {}
    for (username,) in private_users:
        table = 'Msg_' + hashlib.md5(username.encode()).hexdigest()
        try:
            rows = conn.execute(f"""
                SELECT create_time, message_content, WCDB_CT_message_content, local_type
                FROM "{table}"
                WHERE create_time >= ? AND create_time < ?
                ORDER BY create_time
            """, (ts_start, ts_end)).fetchall()
        except sqlite3.OperationalError:
            continue

        if not rows:
            continue

        messages = []
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
                messages.append(f'[{dt_str}] {sender}: {msg}')

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
                    messages.append(f'[{dt_str}] {sender}: [语音] {transcribed}')
                else:
                    messages.append(f'[{dt_str}] {sender}: [语音 {length_sec:.0f}秒]')

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
                messages.append(line)

        if len(messages) >= min_messages:
            all_chats[username] = messages

    conn.close()
    os.remove(out_path)

    return all_chats, contact_names


target_username = 'wxid_s6n393ouvgx121'
all_messages = []

start_date = datetime.date(2026, 4, 1)
end_date = datetime.date(2026, 4, 27)

current_date = start_date
while current_date <= end_date:
    date_str = current_date.strftime('%Y-%m-%d')
    print(f"正在提取 {date_str}...", file=sys.stderr)
    
    try:
        chats, contact_names = extract_all_private(date_str, hour_offset=0, min_messages=1)
        
        if target_username in chats:
            messages = chats[target_username]
            all_messages.extend(messages)
            print(f"  找到 {len(messages)} 条消息", file=sys.stderr)
    except Exception as e:
        print(f"  提取失败: {e}", file=sys.stderr)
    
    current_date += datetime.timedelta(days=1)

print(f"\n总共找到 {len(all_messages)} 条消息", file=sys.stderr)

if all_messages:
    display_name = contact_names.get(target_username, target_username)
    print(f"\n# 与 {display_name} ({target_username}) 的4月份聊天记录\n")
    print(f"时间范围: 2026-04-01 至 2026-04-27")
    print(f"消息总数: {len(all_messages)} 条\n")
    print('\n'.join(all_messages))
else:
    print(f"未找到与 {target_username} 的聊天记录", file=sys.stderr)