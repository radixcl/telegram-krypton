# common use functions

import sys
import json
import sqlite3
import shlex

from lib import globvars

# get configuration
try:
    config = json.load(open(globvars.config_file))
except:
    print('Could not open config file %s' % globvars.config_file, file=sys.stderr)
    sys.exit(1)

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

def get_def(key):
    c.execute('SELECT k, c, a, f, d FROM defs WHERE LOWER(k)=?', [key.lower()])
    res = c.fetchone()

    if res is not None and shlex.split(res[4])[0] == 'see' and len(shlex.split(res[0])) == 2:
        res = get_def(shlex.split(res[4])[1])

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
