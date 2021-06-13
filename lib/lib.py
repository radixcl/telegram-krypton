# common use functions

import sys
import json
import sqlite3
import shlex
import re

from lib import globvars

# get configuration
def load_config():
    global config
    try:
        cfg = json.load(open(globvars.config_file))
    except:
        print('Could not open config file %s' % globvars.config_file, file=sys.stderr)
        sys.exit(1)

    globvars.groups_name_track = cfg.get('groups_name_track', {})
    globvars.groups_member_track = cfg.get('groups_member_track', {})
    globvars.users_track = cfg.get('users_track', {})

    config = cfg
    return cfg

# save config to json file
def save_config(cfg):
    cfg['groups_name_track'] = globvars.groups_name_track
    cfg['groups_member_track'] = globvars.groups_member_track
    cfg['users_track'] = globvars.users_track

    with open(globvars.config_file, 'w') as f:
        json.dump(cfg, f, indent=4)

config = load_config()

c = None
conn = None

# common functions
def open_db():
    global c, conn
    # open database
    db_file = config.get('database_file', 'learn.db')
    try:
        conn = sqlite3.connect(db_file, check_same_thread=False)
        c = conn.cursor()
    except:
        print('Could not open database file %s' % db_file, file=sys.stderr)
        sys.exit(1)


def is_admin(username):
    return username in config['admins']

def is_learner(username):
    return username in config['admins'] or username in config['learners']

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

def find_keys(s):
    s = s.replace('*', '%')
    c.execute('SELECT COUNT(k) FROM defs WHERE LOWER(k) LIKE ?', [s.lower()])
    res = c.fetchone()
    count = res[0]
    retval = ''
    c.execute('SELECT k FROM defs WHERE LOWER(k) LIKE ? LIMIT 50', [s.lower()])
    res = c.fetchall()
    for k in res:
        retval += k[0] + ' '
    retval = retval.strip()
    return count, retval

def find_value(s):
    s = s.replace('*', '%')
    c.execute('SELECT COUNT(k) FROM defs WHERE LOWER(d) LIKE ?', [s.lower()])
    res = c.fetchone()
    count = res[0]
    retval = ''
    c.execute('SELECT k FROM defs WHERE LOWER(d) LIKE ? LIMIT 50', [s.lower()])
    res = c.fetchall()
    for k in res:
        retval += k[0] + ' '
    retval = retval.strip()
    return count, retval

def pop_first(l):
    l.reverse()
    r = l.pop()
    l.reverse()
    return r

def is_url(text):
    regex = re.compile(
            r'^(?:http|ftp)s?://' # http:// or https://
            r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+(?:[A-Z]{2,6}\.?|[A-Z0-9-]{2,}\.?)|' #domain...
            r'localhost|' #localhost...
            r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})' # ...or ip
            r'(?::\d+)?' # optional port
            r'(?:/?|[/?]\S+)$', re.IGNORECASE)
    
    return re.match(regex, text) is not None
