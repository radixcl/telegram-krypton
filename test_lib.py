# run: python3 -m unittest
import sqlite3
import unittest
from types import SimpleNamespace as NS

from unittest import mock

from lib import ai, globvars, lib


class LibTest(unittest.TestCase):
    def setUp(self):
        lib.conn = sqlite3.connect(':memory:')
        lib.c = lib.conn.cursor()
        lib.c.execute(open('learn.db.sql').read())
        globvars.config = {'admins': ['adm'], 'learners': ['lrn']}

    def test_permissions(self):
        self.assertTrue(lib.is_admin('adm') and not lib.is_admin('lrn'))
        self.assertTrue(lib.is_learner('adm') and lib.is_learner('lrn') and not lib.is_learner('x'))

    def test_defs_alias_and_lock(self):
        lib.add_def('Foo', 1, 'a', '', 'bar')
        lib.add_def('alias', 1, 'a', '', 'see foo')
        self.assertEqual(lib.get_def('ALIAS')[4], 'bar')
        lib.lock_key('foo')
        self.assertTrue(lib.is_def_locked('foo'))
        lib.unlock_key('foo')
        self.assertFalse(lib.is_def_locked('foo'))
        lib.del_key('FOO')
        self.assertIsNone(lib.get_def('foo'))

    def test_find_escapes_sql_wildcards(self):
        for k in ('foo_bar', 'fooxbar', 'foo'):
            lib.add_def(k, 1, 'a', '', '50%')
        self.assertEqual(lib.find_keys('foo_bar'), (1, 'foo_bar'))
        self.assertEqual(lib.find_keys('foo*')[0], 3)
        self.assertEqual(lib.find_value('50%')[0], 3)

    def test_parse_args(self):
        self.assertEqual(lib.parse_args('!learn "a b" c'), ['a b', 'c'])
        self.assertEqual(lib.parse_args("!learn it's ok"), ["it's", 'ok'])  # bad quoting falls back
        self.assertEqual(lib.parse_args('??'), [])

    def test_send_remember_records_bot_reply(self):
        sent = []
        ctx = NS(bot=NS(send_message=lambda **kw: sent.append(kw['text'])))
        upd = NS(effective_chat=NS(id=5))
        lib.send(upd, ctx, 'plain')                    # admin-style reply: not recorded
        lib.send(upd, ctx, 'hi', remember=True)
        self.assertEqual(sent, ['plain', 'hi'])
        self.assertEqual([m['author'] + ':' + m['text'] for m in globvars.chat_history['5']], ['You:hi'])

    def test_ai_prompt_prefixes_users_but_not_bot(self):
        cfg = {'ai_api_url': 'u', 'ai_model_id': 'm', 'ai_api_key': 'k'}
        ctx = [{'author': 'bob', 'text': 'hola'}, {'author': 'You', 'text': 'buenas'}]
        with mock.patch.object(ai.requests, 'post') as post:
            post.return_value.json.return_value = {'choices': [{'message': {'content': 'ok'}}]}
            ai.call_ai_api(ctx, 'q', cfg)
        msgs = post.call_args.kwargs['json']['messages']
        self.assertEqual([(m['role'], m['content']) for m in msgs[1:3]],
                         [('user', 'bob: hola'), ('assistant', 'buenas')])


if __name__ == '__main__':
    unittest.main()
