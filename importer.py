#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Esta mierda es para convertir la base de datos TXT de zLearn a sqlite3
# - Matias Fernandez <matias.fernandez@gmail.com>

import sys
import sqlite3

conn = sqlite3.connect('learn.db')
c = conn.cursor()

with open('zLearn.txt', 'r', encoding='utf-8', errors='ignore') as f:

    while True:
        try:
            _key = f.readline()[1:].strip()
            _ts = f.readline()[1:].strip()
            _author = f.readline()[1:].strip()
            _flags = f.readline()[1:].strip()
            _def = f.readline()[1:].strip()
        except:
            break

        vals = [_key, _ts, _author, _flags, _def]

        if vals == ['', '', '', '', '']:
            break

        print("key: ", _key)
        vals = [_key, _ts, _author, _flags, _def]
        try:
            c.execute("INSERT INTO defs (k ,c, a, f, d) VALUES (?, ?, ?, ?, ?)", vals)
            conn.commit()
        except:
            print("Oooops", _key, file=sys.stderr)


conn.close()
