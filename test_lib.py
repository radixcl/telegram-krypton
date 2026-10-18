# run: python3 -m unittest
import sqlite3
import unittest
from types import SimpleNamespace as NS

from unittest import mock

from lib import ai, ai_tools, ai_worker, bot_commands, globvars, lib


class LibTest(unittest.TestCase):
    def setUp(self):
        lib.conn = sqlite3.connect(':memory:')
        lib.c = lib.conn.cursor()
        lib.c.execute(open('learn.db.sql').read())
        lib.conn.execute(lib.REMINDERS_SQL)
        globvars.config = {'admins': ['adm'], 'learners': ['lrn']}

    def test_permissions(self):
        self.assertTrue(lib.is_admin('adm') and not lib.is_admin('lrn'))
        self.assertTrue(lib.is_learner('adm') and lib.is_learner('lrn') and not lib.is_learner('x'))

    def test_setcfg_updates_and_persists_json_value(self):
        update = NS(message=NS(from_user=NS(username='adm', id=1)),
                    effective_message=NS(text='/setcfg ai_system_prompt "hello world"'),
                    effective_chat=NS(type='private'))
        with mock.patch.object(lib, 'save_config') as save, mock.patch.object(lib, 'send') as send:
            bot_commands.COMMANDS['setcfg'](update, NS())
        self.assertEqual(globvars.config['ai_system_prompt'], 'hello world')
        save.assert_called_once_with(globvars.config)
        self.assertIn('guardada', send.call_args.args[2])

    def test_setcfg_rejects_invalid_json(self):
        update = NS(message=NS(from_user=NS(username='adm', id=1)),
                    effective_message=NS(text='/setcfg ai_enabled maybe'),
                    effective_chat=NS(type='private'))
        with mock.patch.object(lib, 'save_config') as save, mock.patch.object(lib, 'send') as send:
            bot_commands.COMMANDS['setcfg'](update, NS())
        self.assertNotIn('ai_enabled', globvars.config)
        save.assert_not_called()
        self.assertIn('JSON inválido', send.call_args.args[2])

    def test_setcfg_rejects_wrong_type(self):
        globvars.config['ai_enabled'] = True
        update = NS(message=NS(from_user=NS(username='adm', id=1)),
                    effective_message=NS(text='/setcfg ai_enabled "yes"'),
                    effective_chat=NS(type='private'))
        with mock.patch.object(lib, 'save_config') as save, mock.patch.object(lib, 'send') as send:
            bot_commands.COMMANDS['setcfg'](update, NS())
        self.assertIs(globvars.config['ai_enabled'], True)
        save.assert_not_called()
        self.assertIn('tipo actual', send.call_args.args[2])

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

    def test_ai_tool_loop(self):
        cfg = {'ai_api_url': 'u', 'ai_model_id': 'm', 'ai_api_key': 'k', 'ai_tools_enabled': True}
        call = {'id': 'c1', 'type': 'function', 'function': {'name': 'calculator', 'arguments': '{"expression": "2+3*4"}'}}
        replies = [{'choices': [{'message': {'content': None, 'tool_calls': [call]}}]},
                   {'choices': [{'message': {'content': 'listo'}}]}]
        with mock.patch.object(ai.requests, 'post') as post:
            post.return_value.json.side_effect = replies
            self.assertEqual(ai.call_ai_api([], 'q', cfg), 'listo')
        names = [t['function']['name'] for t in post.call_args_list[0].kwargs['json']['tools']]
        self.assertIn('calculator', names)
        self.assertNotIn('web_search', names)   # no tavily key
        self.assertNotIn('set_reminder', names)  # no chat ctx
        first = post.call_args_list[0].kwargs['json']['messages']
        self.assertIn('Current date and time', first[0]['content'])
        last = post.call_args_list[1].kwargs['json']['messages'][-1]
        self.assertEqual((last['role'], last['content']), ('tool', '14'))

    def test_preview_request_skips_model(self):
        cfg = {'ai_api_url': 'u', 'ai_model_id': 'm', 'ai_api_key': 'k', 'ai_tools_enabled': True}
        def fake(args, config, ctx):
            ctx['media'] = [('text', None, args['url'])]
            return 'x'
        with mock.patch.object(ai.requests, 'post') as post, \
                mock.patch.dict(ai_tools.TOOLS, {'link_preview': (ai_tools.TOOLS['link_preview'][0], fake)}):
            ctx = {'chat_id': 1, 'user': 'a'}
            self.assertEqual(ai.call_ai_api([], 'preview https://a.com/x?y=1', cfg, ctx=ctx), 'ok')
        post.assert_not_called()
        self.assertEqual(ctx['media'][0][2], 'https://a.com/x?y=1')

    def test_instagram_preview(self):
        f = ai_tools.instagram_preview
        for bad in ('https://evil.com/p/abc/', 'https://instagram.com.evil.com/p/abc/',
                    'https://www.instagram.com/someuser/', 'ftp://instagram.com/p/abc/'):
            with self.assertRaises(ValueError):
                f({'url': bad}, {}, {})
        page = mock.Mock(text=r'"video_url\":\"https:\\\/\\\/x.fbcdn.net\\\/a.mp4?a=1\\u00262\"')
        dl = mock.MagicMock()
        dl.__enter__.return_value = mock.Mock(headers={'Content-Type': 'video/mp4'},
                                              raw=mock.Mock(read=lambda n, decode_content: b'MP4'))
        ctx = {}
        with mock.patch.object(ai_tools.requests, 'get', side_effect=[page, dl]) as g, \
                mock.patch.object(ai_tools, '_check_public'):
            f({'url': 'https://www.kkinstagram.com/reel/AbC-d_1/?igsh=x'}, {}, ctx)
        self.assertEqual(g.call_args_list[0][0][0], 'https://www.instagram.com/reel/AbC-d_1/embed/captioned/')
        self.assertEqual(g.call_args_list[1][0][0], 'https://x.fbcdn.net/a.mp4?a=1&2')
        self.assertEqual(ctx['media'], [('video', b'MP4', '')])
        # a media URL outside Instagram's CDN is refused
        page = mock.Mock(text='class="EmbeddedMediaImage" alt="x" src="http://169.254.169.254/x.jpg"')
        ctx = {}
        with mock.patch.object(ai_tools.requests, 'get', return_value=page):
            out = f({'url': 'https://www.instagram.com/p/abc/'}, {}, ctx)
        self.assertTrue(out.startswith('FAILED') and 'age-restricted' in out and 'media' not in ctx)

    def test_history_roundtrip(self):
        import tempfile, os
        from collections import deque
        old = (lib.globvars.config_file, lib.globvars.chat_history)
        d = tempfile.mkdtemp()
        lib.globvars.config_file = os.path.join(d, 'c.json')
        try:
            lib.globvars.chat_history = {'1': deque([{'author': 'a', 'text': f'm{i}', 'timestamp': i} for i in range(5)])}
            lib.save_history()
            lib.globvars.chat_history = {}
            lib.load_history(3)
            self.assertEqual([m['text'] for m in lib.globvars.chat_history['1']], ['m2', 'm3', 'm4'])
            os.remove(lib.globvars.config_file + '.history.json')
            lib.load_history(3)  # missing file: no crash
        finally:
            lib.globvars.config_file, lib.globvars.chat_history = old

    def test_link_preview(self):
        def resp(ctype, body):
            return mock.Mock(is_redirect=False, headers={'Content-Type': ctype}, encoding='utf-8',
                             raw=mock.Mock(read=lambda n, decode_content: body))
        html = (b'<html><head><title>Fallback</title><meta property="og:title" content="Hola &amp; chao">'
                b'<meta property="og:description" content="Una  descripcion">'
                b'<meta property="og:image" content="/img.jpg"></head></html>')
        ctx = {}
        with mock.patch.object(ai_tools.requests, 'get', side_effect=[resp('text/html; charset=utf-8', html),
                                                                      resp('image/jpeg', b'JPG')]) as g, \
                mock.patch.object(ai_tools, '_check_public'):
            out = ai_tools.link_preview({'url': 'https://example.com/a'}, {}, ctx)
        self.assertEqual(g.call_args_list[1][0][0], 'https://example.com/img.jpg')
        self.assertEqual(ctx['media'], [('image', b'JPG', 'Hola & chao\nUna descripcion\nhttps://example.com/a')])
        # image download fails -> text card; no metadata at all -> FAILED with the reason
        ctx = {}
        with mock.patch.object(ai_tools.requests, 'get', side_effect=[resp('text/html', html), resp('text/plain', b'x')]), \
                mock.patch.object(ai_tools, '_check_public'):
            ai_tools.link_preview({'url': 'https://example.com/a'}, {}, ctx)
        self.assertEqual(ctx['media'][0][0], 'text')
        ctx = {}
        with mock.patch.object(ai_tools.requests, 'get', return_value=resp('text/html', b'<html></html>')), \
                mock.patch.object(ai_tools, '_check_public'):
            out = ai_tools.link_preview({'url': 'https://example.com/a'}, {}, ctx)
        self.assertTrue(out.startswith('FAILED') and 'no title' in out and 'media' not in ctx)
        out = ai_tools.link_preview({'url': 'http://127.0.0.1/x'}, {}, {})
        self.assertTrue(out.startswith('FAILED') and 'private' in out)

    def test_calculator(self):
        calc = lambda e: ai_tools.calculator({'expression': e}, {}, {})
        self.assertEqual(calc('(12.5+3)*4/2'), 31.0)
        self.assertEqual(calc('-2**3'), -8)
        for bad in ('__import__("os")', '2**999', '9**9**9', 'a+1', '1/0'):
            with self.assertRaises(Exception):
                calc(bad)

    def test_fetch_blocks_private_and_non_http(self):
        for url in ('http://127.0.0.1/', 'http://169.254.169.254/latest', 'http://10.0.0.5:8080/',
                    'http://[::1]/', 'file:///etc/passwd', 'ftp://example.com/'):
            with self.assertRaises(ValueError):
                ai_tools._check_public(url)

    def test_kb_tools(self):
        lib.add_def('perro', 1, 'a', '', 'guau')
        lib.add_def('gato', 1, 'a', '', 'ver perro y miau')
        self.assertEqual(ai_tools.kb_lookup({'key': 'PERRO'}, {}, {}), 'guau')
        self.assertEqual(ai_tools.kb_lookup({'key': 'x'}, {}, {}), 'Entry not found.')
        out = ai_tools.kb_search({'text': 'perro'}, {}, {})
        self.assertIn('perro', out.splitlines()[0])
        self.assertIn('gato', out.splitlines()[1])

    def test_reminders(self):
        ctx = {'chat_id': 7, 'user': 'bob'}
        for _ in range(ai_tools.MAX_PENDING_REMINDERS):
            ai_tools.set_reminder({'minutes': 1, 'text': 'x'}, {}, ctx)
        self.assertIn('Too many', ai_tools.set_reminder({'minutes': 1, 'text': 'x'}, {}, ctx))
        with self.assertRaises(ValueError):
            ai_tools.set_reminder({'minutes': 0, 'text': 'x'}, {}, {'chat_id': 8, 'user': 'bob'})
        self.assertEqual(lib.pop_due_reminders(0), [])
        due = lib.pop_due_reminders(2**40)
        self.assertEqual(len(due), 5)
        self.assertEqual(due[0], (7, 'bob', 'x'))
        self.assertEqual(lib.pop_due_reminders(2**40), [])

    def test_add_mentions(self):
        globvars.users_track = {'GeovanniAndreotti': 1, 'radix': 2}
        self.assertEqual(ai_worker.add_mentions('hola geovanniandreotti y @radix, radixal no'),
                         'hola @GeovanniAndreotti y @radix, radixal no')

    def test_ai_images_use_vision_model(self):
        cfg = {'ai_api_url': 'u', 'ai_model_id': 'm', 'ai_vision_model_id': 'vl', 'ai_api_key': 'k'}
        with mock.patch.object(ai.requests, 'post') as post:
            post.return_value.json.return_value = {'choices': [{'message': {'content': 'un gato'}}]}
            self.assertEqual(ai.call_ai_api([], 'qué es?', cfg, images=['data:image/jpeg;base64,AA==']), 'un gato')
            payload = post.call_args.kwargs['json']
            self.assertEqual(payload['model'], 'vl')
            self.assertEqual(payload['messages'][-1]['content'],
                             [{'type': 'text', 'text': 'qué es?'},
                              {'type': 'image_url', 'image_url': {'url': 'data:image/jpeg;base64,AA=='}}])
            ai.call_ai_api([], 'hola', cfg)
            self.assertEqual(post.call_args.kwargs['json']['model'], 'm')   # no image: default model

    def test_worker_downloads_images(self):
        w = ai_worker.AIWorker()
        w.bot = mock.Mock()
        w.bot.get_file.side_effect = [mock.Mock(download_as_bytearray=lambda: bytearray(b'PNG')), Exception('gone')]
        self.assertEqual(w._download_images([('a', 'image/png'), ('b', 'image/jpeg')]),
                         ['data:image/png;base64,UE5H'])

    def test_bot_image_messages(self):
        import bot
        photo = lambda fid, size: NS(file_id=fid, file_size=size)
        msg = NS(photo=[photo('s', 10), photo('m', 100), photo('huge', bot.MAX_IMAGE_BYTES + 1)], document=None)
        self.assertEqual(bot.image_refs(msg), [('m', 'image/jpeg')])
        doc = lambda mime: NS(photo=[], document=NS(file_id='d', mime_type=mime, file_size=10))
        self.assertEqual(bot.image_refs(doc('image/png')), [('d', 'image/png')])
        self.assertEqual(bot.image_refs(doc('application/pdf')), [])

        # private photo without caption: recorded in history and sent to the AI with the image
        globvars.config = {'ai_enabled': True, 'ai_enable_private': True}
        self.addCleanup(globvars.chat_history.pop, '77', None)
        user = NS(id=1, username='bob', full_name='Bob')
        msg = NS(photo=[photo('p', 10)], document=None, caption=None, text=None, message_id=9,
                 reply_to_message=None, media_group_id=None, chat=NS(type='private'),
                 new_chat_members=[], left_chat_member=None)
        upd = NS(message=msg, effective_user=user, effective_chat=NS(id=77, type='private', title=None))
        worker = mock.Mock()
        with mock.patch.object(bot, 'ai_worker_instance', worker):
            bot.proc_message(upd, NS(bot=NS(id=99, username='kbot')))
        self.assertEqual(globvars.chat_history['77'][-1]['text'], '[image]')
        self.assertEqual(worker.submit.call_args.args[-1], [('p', 'image/jpeg')])


if __name__ == '__main__':
    unittest.main()
