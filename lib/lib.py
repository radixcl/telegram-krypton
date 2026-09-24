# common use functions

import sys
import json
import os
import sqlite3
import shlex
import re
import time
from collections import deque

from lib import globvars

# get configuration
def load_config():
    try:
        cfg = json.load(open(globvars.config_file))
    except:
        print('Could not open config file %s' % globvars.config_file, file=sys.stderr)
        sys.exit(1)

    globvars.groups_name_track = cfg.get('groups_name_track', {})
    globvars.groups_member_track = cfg.get('groups_member_track', {})
    globvars.users_track = cfg.get('users_track', {})

    globvars.config = cfg  # single source of truth for the config
    return cfg

# save config to json file
def save_config(cfg):
    cfg['groups_name_track'] = globvars.groups_name_track
    cfg['groups_member_track'] = globvars.groups_member_track
    cfg['users_track'] = globvars.users_track

    with open(globvars.config_file, 'w') as f:
        json.dump(cfg, f, indent=4)

def _history_file():
    return globvars.config_file + '.history.json'

def save_history():
    """Dump the per-chat AI history next to the config (atomic, so a crash can't corrupt it)."""
    data = {chat: list(msgs) for chat, msgs in list(globvars.chat_history.items())}
    tmp = _history_file() + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(data, f)
    os.replace(tmp, _history_file())

def load_history(maxlen):
    try:
        with open(_history_file()) as f:
            data = json.load(f)
    except (OSError, ValueError):
        return  # first run or unreadable file: start empty
    for chat, msgs in data.items():
        globvars.chat_history[chat] = deque(msgs, maxlen=maxlen)

# Connection initialized in bot.py main()
c = None
conn = None

REMINDERS_SQL = ('CREATE TABLE IF NOT EXISTS reminders '
                 '(id INTEGER PRIMARY KEY, chat_id INTEGER, user TEXT, due INTEGER, text TEXT)')

def open_db():
    global c, conn
    db_file = globvars.config.get('database_file', 'learn.db')
    try:
        conn = sqlite3.connect(db_file, check_same_thread=False)
        c = conn.cursor()
        conn.execute(REMINDERS_SQL)
        conn.commit()
    except:
        print('Could not open database file %s' % db_file, file=sys.stderr)
        sys.exit(1)


# reminders use conn.execute (own cursor): called from the AI worker and the job queue threads
def add_reminder(chat_id, user, due, text):
    conn.execute('INSERT INTO reminders (chat_id, user, due, text) VALUES (?, ?, ?, ?)', [chat_id, user, due, text])
    conn.commit()

def count_reminders(chat_id, user):
    return conn.execute('SELECT COUNT(*) FROM reminders WHERE chat_id = ? AND user IS ?', [chat_id, user]).fetchone()[0]

def pop_due_reminders(now):
    """Remove and return [(chat_id, user, text)] whose time has come."""
    rows = conn.execute('SELECT id, chat_id, user, text FROM reminders WHERE due <= ?', [now]).fetchall()
    for row in rows:
        conn.execute('DELETE FROM reminders WHERE id = ?', [row[0]])
    conn.commit()
    return [row[1:] for row in rows]


def is_admin(username):
    return username in globvars.config['admins']

def is_learner(username):
    return username in globvars.config['admins'] or username in globvars.config['learners']

def parse_args(text):
    """Arguments of a "!cmd a b" / "/cmd a b" message (command excluded).
    Falls back to whitespace split on bad quoting."""
    try:
        parts = shlex.split(text)
    except ValueError:
        parts = text.split()
    return parts[1:]

def send(update, context, text, parse_mode=None, remember=False):
    """Reply in the chat the update came from.
    remember=True also records the reply in the chat history the AI uses as
    context (author 'You' = the bot)."""
    chat_id = update.effective_chat.id
    context.bot.send_message(chat_id=chat_id, text=text, parse_mode=parse_mode)
    if remember:
        size = (globvars.config or {}).get('ai_context_size', 50)
        history = globvars.chat_history.setdefault(str(chat_id), deque(maxlen=size))
        history.append({'author': 'You', 'text': text, 'timestamp': time.time()})

def get_def(key, rec=0):

    if rec == 10:
        # excess recursion
        return None

    c.execute('SELECT k, c, a, f, d FROM defs WHERE LOWER(k)=?', [key.lower()])
    res = c.fetchone()

    try:
        if res is not None and shlex.split(res[4])[0] == 'see' and len(shlex.split(res[4])) == 2:
            res = get_def(shlex.split(res[4])[1], rec+1)
    except IndexError :
        pass

    return res

def add_def(key, ts, author, flags, text):
    vals = [
        key.lower(),
        ts,
        author,
        flags,
        text
    ]
    c.execute("INSERT INTO defs (k ,c, a, f, d) VALUES (?, ?, ?, ?, ?)", vals)
    conn.commit()

def is_def_locked(key):
    res = get_def(key)
    try:
        return "l" in res[3]
    except:
        return False

def del_key(key):
    c.execute('DELETE FROM defs WHERE LOWER(k) = ?', [key.lower()])
    conn.commit()

def lock_key(key):
    if is_def_locked(key):
        return
    c.execute('SELECT f FROM defs WHERE LOWER(k) = ?', [key.lower()])
    res = c.fetchone()
    current_flags = res[0] + 'l'
    c.execute('UPDATE defs SET f = ? WHERE LOWER(k) = ?', [current_flags, key.lower()])
    conn.commit()

def unlock_key(key):
    if not is_def_locked(key):
        return
    c.execute('SELECT f FROM defs WHERE LOWER(k) = ?', [key.lower()])
    res = c.fetchone()
    current_flags = res[0].replace('l', '')
    c.execute('UPDATE defs SET f = ? WHERE LOWER(k) = ?', [current_flags, key.lower()])
    conn.commit()

def _like(s):
    # only '*' is a wildcard; escape SQL's own % and _
    s = s.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
    return s.replace('*', '%').lower()

def find_keys(s):
    s = _like(s)
    c.execute("SELECT COUNT(k) FROM defs WHERE LOWER(k) LIKE ? ESCAPE '\\'", [s])
    res = c.fetchone()
    count = res[0]
    retval = ''
    c.execute("SELECT k FROM defs WHERE LOWER(k) LIKE ? ESCAPE '\\' LIMIT 50", [s])
    res = c.fetchall()
    for k in res:
        retval += k[0] + ' '
    retval = retval.strip()
    return count, retval

def find_value(s):
    s = _like(s)
    c.execute("SELECT COUNT(k) FROM defs WHERE LOWER(d) LIKE ? ESCAPE '\\'", [s])
    res = c.fetchone()
    count = res[0]
    retval = ''
    c.execute("SELECT k FROM defs WHERE LOWER(d) LIKE ? ESCAPE '\\' LIMIT 50", [s])
    res = c.fetchall()
    for k in res:
        retval += k[0] + ' '
    retval = retval.strip()
    return count, retval

def is_url(text):
    regex = re.compile(
            r'^(?:http|ftp)s?://' # http:// or https://
            r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+(?:[A-Z]{2,6}\.?|[A-Z0-9-]{2,}\.?)|' #domain...
            r'localhost|' #localhost...
            r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})' # ...or ip
            r'(?::\d+)?' # optional port
            r'(?:/?|[/?]\S+)$', re.IGNORECASE)
    
    return re.match(regex, text) is not None

def message_contains_media(reply):
    if not reply:
        return False

    return any([
        reply.photo,
        reply.video,
        reply.animation,
        reply.document,
        reply.audio,
        reply.voice,
        reply.video_note,
        reply.sticker,
        reply.contact,
        reply.location,
        reply.venue,
    ])

def is_message_text_only(reply):
    return bool(reply) and not message_contains_media(reply) and reply.text is not None
