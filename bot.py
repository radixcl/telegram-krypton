#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Krypton telegram bot
# - Matias Fernandez <matias.fernandez@gmail.com>
#

import argparse
import logging
import sqlite3
import time
from collections import deque

from telegram.ext import Updater, CommandHandler, MessageHandler, Filters

from lib import ai, ai_worker, bot_commands, globvars, lib

logger = logging.getLogger(__name__)

# Global AI worker instance (set by main(), used by ai_reply and sig_handler)
ai_worker_instance = None


# --- tracking ---------------------------------------------------------------

def track(update, user):
    """Remember username -> id, group names and group members."""
    chat = update.effective_chat
    msg = update.message

    if user.username is not None:
        globvars.users_track[user.username] = user.id

    members = globvars.groups_member_track.setdefault(str(chat.id), [])
    if chat.type not in ('group', 'channel', 'supergroup'):
        return

    globvars.groups_name_track[str(chat.id)] = chat.title  # str: JSON keys are always str

    if msg.new_chat_members:
        joined = list(msg.new_chat_members)
    elif msg.left_chat_member is not None:
        left = msg.left_chat_member
        if left.username is not None:
            globvars.users_track[left.username] = left.id
        if left.id in members:
            members.remove(left.id)
        return
    else:
        joined = [user]

    for member in joined:
        if member.username is not None:
            globvars.users_track[member.username] = member.id
        if member.id not in members:
            members.append(member.id)


# --- knowledge base commands ("??" and "!xxx") -------------------------------
# Each takes (update, context, username, args) where args excludes the command.

def say(update, context, text, parse_mode=None):
    """Reply and record it in the chat history, so the AI knows what the bot said."""
    lib.send(update, context, text, parse_mode, remember=True)

def need_key(update, context, args):
    """First argument, or None after replying "Expected key"."""
    if not args:
        say(update, context, "Expected key, found NUL.")
        return None
    return args[0]

def cmd_query(update, context, username, args):
    """?? [-a] key"""
    verbose = bool(args) and args[0] == '-a'
    if verbose:
        args = args[1:]
        if not args:
            say(update, context, "Error while parsing flags.")
            return

    key = need_key(update, context, args)
    if key is None:
        return

    res = lib.get_def(key)
    if res is None:
        say(update, context, "Entry *%s* not found." % key, 'Markdown')
        return

    res_txt = res[4]
    answer_mode = 'Markdown'
    if lib.is_url(res_txt):
        answer_mode = 'html'
        response = '<b>%s</b> == %s' % (res[0], res_txt)
    else:
        res_txt = res_txt.replace('%n', '`@' + username + '`')
        response = '*%s* == `%s`' % (res[0], res_txt)

    # stored photo: ".tg_reply_to:<message_id>:<file_id>"
    if res_txt.startswith('.tg_reply_to:'):
        _, _, file_id = res_txt.split(':')
        caption = "<b>%s</b> == " % res[0]
        if verbose:
            caption += '\n<i>(author: %s) (%s)</i>' % (res[2], time.ctime(int(res[1])))
        context.bot.send_photo(chat_id=update.effective_chat.id, photo=file_id, caption=caption, parse_mode='html')
        return

    if verbose and answer_mode == 'Markdown':
        response += '\n_(author: %s) (%s)' % (res[2], time.ctime(int(res[1]))) + '_'
    elif verbose:
        response += '\n<i>(author: %s) (%s)</i>' % (res[2], time.ctime(int(res[1])))

    try:
        say(update, context, response, answer_mode)
    except Exception as ex:
        say(update, context, 'ERROR CTM! (FIXME): ' + str(ex), 'Markdown')

def _learn_text_from_message(update, context):
    """Definition text taken from the replied message (or the message itself).
    Returns None after replying with an error."""
    msg = update.message
    reply = msg.reply_to_message
    if not reply:
        return msg.text

    if lib.is_message_text_only(reply):
        author = reply.from_user.username or reply.from_user.first_name
        return f'<@{author}> {reply.text}'

    if lib.message_contains_media(reply):
        # only photos can be replayed by "??" (send_photo)
        if not reply.photo:
            say(update, context, 'Only photos can be learned.')
            return None
        return f'.tg_reply_to:{reply.message_id}:{reply.photo[-1].file_id}'

    return ''

def cmd_learn(update, context, username, args):
    """!learn [-l] [-f] key [definition]   (-l lock, -f overwrite: admins only)"""
    admin = lib.is_admin(username)
    flags = ''
    if args and args[0] == '-l':
        if admin:
            flags = 'l'
        args = args[1:]
    if args and args[0] == '-f':
        if admin and len(args) > 1:
            lib.del_key(args[1])
        args = args[1:]

    key = need_key(update, context, args)
    if key is None:
        return

    def_txt = ' '.join(args[1:])
    if def_txt == '':
        def_txt = _learn_text_from_message(update, context)
        if def_txt is None:
            return

    try:
        lib.add_def(key, int(time.time()), '@' + username + ' (Telegram)', flags, def_txt)
    except sqlite3.IntegrityError:
        say(update, context, "key *%s* already exists" % key, 'Markdown')
        return

    if def_txt == '':
        response = 'Learned blank entry for *%s*. (Why did you do that?)' % key
    else:
        response = 'Learned *%s*.' % key
    say(update, context, response, 'Markdown')

def cmd_forget(update, context, username, args):
    """!forget [-f] key   (-f removes locked keys: admins only)"""
    force = False
    if args and args[0] == '-f':
        args = args[1:]
        force = lib.is_admin(username)

    key = need_key(update, context, args)
    if key is None:
        return

    if lib.is_def_locked(key) and not force:
        say(update, context, "Can't forget: Key is locked.")
        return

    lib.del_key(key)
    say(update, context, 'Removed *%s*.' % key, 'Markdown')

def key_action(action, past):
    """Command that runs action(key) and answers "<past> *key*."."""
    def cmd(update, context, username, args):
        key = need_key(update, context, args)
        if key is None:
            return
        action(key)
        say(update, context, '%s *%s*.' % (past, key), 'Markdown')
    return cmd

def search(finder):
    """Command that answers with the keys matched by finder(pattern)."""
    def cmd(update, context, username, args):
        key = need_key(update, context, args)
        if key is None:
            return
        total, results = finder(key)
        say(update, context, 'Matched %s key(s): %s' % (total, results))
    return cmd

# first word -> (handler, who may use it: None = everybody, or a lib.is_xxx check)
KB_COMMANDS = {
    '??':        (cmd_query, None),
    '!learn':    (cmd_learn, lib.is_learner),
    '!forget':   (cmd_forget, lib.is_learner),
    '!lock':     (key_action(lib.lock_key, 'Locked'), lib.is_admin),
    '!unlock':   (key_action(lib.unlock_key, 'Unlocked'), lib.is_admin),
    '!listkeys': (search(lib.find_keys), None),
    '!find':     (search(lib.find_value), None),
}


# --- AI ---------------------------------------------------------------------

def ai_reply(update, context, text):
    """Queue an AI answer (groups: mention or reply to the bot required; private: always if enabled)."""
    cfg = globvars.config
    bot = context.bot
    msg = update.message
    chat_key = str(update.effective_chat.id)
    message_id = msg.message_id

    # never answer the same message twice
    responded = globvars.responded_to_message_ids.setdefault(chat_key, set())
    if message_id in responded:
        return

    reply_msg = msg.reply_to_message
    bot_mention = f"@{bot.username}"
    replying_to_bot = bool(reply_msg) and reply_msg.from_user.id == bot.id

    if msg.chat.type == 'private':
        if not cfg.get('ai_enable_private', False):
            return
    else:
        replied_text = (reply_msg.text or reply_msg.caption or '') if reply_msg else ''
        mentioned = bot_mention in text or bot_mention in replied_text
        if update.effective_user.id == bot.id or not (mentioned or replying_to_bot):
            return

    question = text.replace(bot_mention, '').strip()
    if not question:
        return

    # the last history entry is the current message, which goes separately as the query
    history = list(globvars.chat_history.get(chat_key, []))[:-1]
    context_messages = ai.build_context(history, cfg.get('ai_context_size', 50))

    if replying_to_bot:
        context_messages.insert(0, {'author': 'You', 'text': reply_msg.text or reply_msg.caption or ''})
        reply_to_message_id = message_id  # answer the user's message, not the bot's
    elif reply_msg:
        reply_to_message_id = reply_msg.message_id
        # the model can't see which message is quoted (may be outside the context window): add it
        quoted = reply_msg.text or reply_msg.caption or ''
        links = [e.url for e in (reply_msg.entities or reply_msg.caption_entities or []) if e.url]
        author = reply_msg.from_user.username or reply_msg.from_user.full_name
        question = f'(replying to {author}: "{quoted}" {" ".join(links)})\n{question}'
    else:
        reply_to_message_id = None

    if ai_worker_instance:
        ai_worker_instance.submit(update.effective_chat.id, context_messages, question, cfg,
                                  reply_to_message_id, message_id, update.effective_user.username)
    else:
        logger.warning("AI worker not initialized despite ai_enabled=True")


# --- entry points -------------------------------------------------------------

def proc_message(update, context):
    msg = update.message
    if msg is None:
        return

    user = update.effective_user
    # Users without a username get their numeric id (unspoofable, can be listed in admins/learners)
    username = user.username if user.username is not None else str(user.id)
    cfg = globvars.config

    track(update, user)

    text = msg.text
    if not text or not text.strip():
        return  # not a chat message

    history = globvars.chat_history.setdefault(str(update.effective_chat.id),
                                               deque(maxlen=cfg.get('ai_context_size', 50)))
    # readable name for the AI context (username is only for permissions)
    history.append({'author': user.username or user.full_name, 'text': text, 'timestamp': time.time()})

    entry = KB_COMMANDS.get(text.split()[0])
    if entry:
        handler, allowed = entry
        if allowed is None or allowed(username):
            handler(update, context, username, lib.parse_args(text))
    elif cfg.get('ai_enabled', False):
        ai_reply(update, context, text)

def send_due_reminders(context):
    for chat_id, user, text in lib.pop_due_reminders(int(time.time())):
        who = f"@{user}: " if user else ""
        try:
            context.bot.send_message(chat_id=chat_id, text=f"\u23f0 {who}{text}")
        except Exception as e:
            logger.warning("Could not send reminder to chat %s: %s", chat_id, e)

def sig_handler(signum, frame):
    print("Saving config...")
    lib.save_config(globvars.config)
    if ai_worker_instance:
        ai_worker_instance.stop()

def main():
    global ai_worker_instance

    parser = argparse.ArgumentParser(description='Krypton Telegram Bot')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Enable verbose/debug logging')
    parser.add_argument('--config', '-c', type=str, default='config.json',
                        help='Path to config file (default: config.json)')
    args = parser.parse_args()

    logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                        level=logging.DEBUG if args.verbose else logging.INFO)

    globvars.config_file = args.config
    config = lib.load_config()
    lib.open_db()
    logger.info("Using config file: %s", globvars.config_file)

    updater = Updater(token=config["telegram_token"], user_sig_handler=sig_handler)
    dp = updater.dispatcher

    if config.get('ai_enabled', False):
        ai_worker_instance = ai_worker.AIWorker(
            rate_limit_seconds=config.get('ai_rate_limit_seconds', 5),
            verbose=config.get('ai_verbose', args.verbose))
        ai_worker_instance.start(updater.bot)
        logger.info("AI worker initialized")
    else:
        logger.warning("AI worker NOT initialized: ai_enabled=False")

    # /commands (declared with @command in lib/bot_commands.py)
    for name, handler in bot_commands.COMMANDS.items():
        dp.add_handler(CommandHandler(name, handler))

    # text message handler
    dp.add_handler(MessageHandler(Filters.all, proc_message))

    # persist tracking every 5 min so a crash doesn't lose it (also saved on SIGINT/SIGTERM)
    updater.job_queue.run_repeating(lambda ctx: lib.save_config(globvars.config), interval=300, first=300)
    updater.job_queue.run_repeating(send_due_reminders, interval=30, first=10)
    updater.start_polling()
    updater.idle()


if __name__ == '__main__':
    main()
