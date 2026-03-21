#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Krypton telegram bot
# - Matias Fernandez <matias.fernandez@gmail.com>
#

import sys
import logging
import argparse

# Debug: Check what happens at module load time
if __name__ == '__main__':
    print(f"DEBUG: __name__ = {__name__}")
    print(f"DEBUG: sys.argv = {sys.argv}")

from telegram import Update, ForceReply
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext

import sys
import logging
import argparse
import sqlite3
import time
import shlex
import pickle
import pprint
from collections import deque

# Initialize per-chat data structures in globvars
# chat_history and responded_to_message_ids are already initialized in globvars

def proc_message(update: Update, context: CallbackContext) -> None:
    # Import modules inside function to ensure proper initialization
    from lib import globvars
    from lib import lib
    from lib import ai_worker

    # Load config to get ai_context_size
    if lib.config is None:
        lib.config = lib.load_config()
    
    #chat_id = update.message.chat.id
    chat_id = update.effective_chat.id
    user = update.effective_user
    user_id = user.id
    bot = context.bot
    text = update.message.text
    verbose = False

    if user.username is not None:
        username = user.username
    else:
        username = "%s %s" % (user.first_name, user.last_name)

    # tracking
    if not None in (username, update.message.from_user.id):
        globvars.users_track[update.message.from_user.username] = update.message.from_user.id
        #print("TRACK USER: %s -> %s" % (update.message.from_user.username, update.message.from_user.id))

    if not str(chat_id) in globvars.groups_member_track:
        globvars.groups_member_track[str(chat_id)] = []

    # Track message in chat history (for AI context)
    if not str(chat_id) in globvars.chat_history:
        globvars.chat_history[str(chat_id)] = deque(maxlen=ai_context_size)
    
    if text and text.strip():
        msg_record = {
            'author': username,
            'text': text,
            'timestamp': time.time()
        }
        globvars.chat_history[str(chat_id)].append(msg_record)

    if update.message.chat.type in ('group', 'channel', 'supergroup'):
        globvars.groups_name_track[chat_id] = update.message.chat.title

        if len(update.message.new_chat_members) > 0:
            for member in update.message.new_chat_members:
                if member.username is not None:
                    globvars.users_track[member.username] = member.id
                    #print("TRACK USER: %s -> %s" % (member.username, member.id))
                if user_id not in set(globvars.groups_member_track[str(chat_id)]):
                    globvars.groups_member_track[str(chat_id)].append(member.id)
                    #print("TRACK ADD MEMBER: %s -> %s" % (chat_id, member.id))

        elif update.message.left_chat_member is not None:
            member = update.message.left_chat_member
            if member.username is not None:
                globvars.users_track[member.username] = member.id
                #print("TRACK USER: %s -> %s" % (member.username, member.id))
            try:
                globvars.groups_member_track[str(chat_id)].remove(member.id)
                #print("TRACK REMOVE MEMBER: %s -> %s" % (chat_id, member.id))
                return
            except:
                pass

        else:
            if user_id not in set(globvars.groups_member_track[str(chat_id)]):
                globvars.groups_member_track[str(chat_id)].append(user_id)
                #print("TRACK ADD MEMBER: %s -> %s" % (chat_id, user_id))


    if text is None or text == '':
        # not a chat message
        return

    cmd = text.split()[0]
    # parse "?? definition" queries
    if cmd == '??':
        try:
            data = shlex.split(text)
        except ValueError:
            data = text.split()
        
        if len(data) < 2:
            bot.send_message(chat_id=chat_id, text="Expected key, found NUL.")
            return

        _key = data[1]

        if _key == '-a':
            verbose = True
            try:
                _key = data[2]
            except:
                bot.send_message(chat_id=chat_id, text="Error while parsing flags.")
                return

        res = lib.get_def(_key)
        if res is None:
            bot.send_message(chat_id=chat_id, text="Entry *%s* not found." % _key, parse_mode='Markdown')
            return
        res_txt = res[4]
        answer_mode = 'Markdown'
        if lib.is_url(res_txt):
            answer_mode = 'html'
            response = response = '<b>%s</b> == %s' % (res[0], res_txt)
        else:
            res_txt = res_txt.replace('%n', '`@' + username + '`')
            response = '*%s* == `%s`' % (res[0], res_txt)
        
        # check if res_txt starts with .tg_reply_to:
        if res_txt.startswith('.tg_reply_to:'):
            answer_mode = 'html'
            # get message_id and file_id
            _, message_id, file_id = res_txt.split(':')
            # send photo
            #bot.send_photo(chat_id=chat_id, photo=file_id, reply_to_message_id=int(message_id))
            text = "<b>%s</b> == " % res[0]
            if verbose == True:
                text += '\n<i>(author: %s) (%s)</i>' % (res[2], time.ctime(int(res[1])))
            bot.send_photo(chat_id=chat_id, photo=file_id, caption=text, parse_mode=answer_mode)
            return

        if verbose == True and answer_mode == 'Markdown':
            response += '\n_(author: %s) (%s)' % (res[2], time.ctime(int(res[1]))) + '_'
        elif verbose == True and answer_mode == 'html':
            response += '\n<i>(author: %s) (%s)</i>' % (res[2], time.ctime(int(res[1])))
        
        try:
            bot.send_message(chat_id=chat_id, text=response, parse_mode=answer_mode)
        except Exception as ex:
            # FIXME
            bot.send_message(chat_id=chat_id, text='ERROR CTM! (FIXME): ' + str(ex), parse_mode='Markdown')
            print(response)
    
    # parse "!learn key value" requests
    elif cmd == '!learn':
        if not lib.is_learner(username):
            #response = "Adonde la viste @%s" % username
            #bot.send_message(chat_id=chat_id, text=response, parse_mode='Markdown')
            return

        data = shlex.split(text)
        # remove !learn from data
        _ = lib.pop_first(data)

        learn_flags = ''
        try:
            if data[0] == '-l':
                if lib.is_admin(username):
                    learn_flags = 'l'
                _ = lib.pop_first(data)
        except:
            pass

        try:
            if data[0] == '-f':
                if lib.is_admin(username):
                    lib.del_key(data[1])
                _ = lib.pop_first(data)
        except:
            pass

        # get key
        try:
            key = lib.pop_first(data)
        except:
            bot.send_message(chat_id=chat_id, text="Expected key, found NUL.")
            return
        
        # get definition
        try:
            def_txt = ' '.join(data)
        except:
            def_txt = ''
        
        print(update.message)

        if def_txt == '':
            allowed_media_types = ['photo', 'video', 'animation', 'document', 'audio', 'voice', 'video_note']

            # Verificar si el mensaje es una respuesta a otro mensaje
            if update.message.reply_to_message:
                # Manejar mensajes citados
                if lib.is_message_text_only(update.message.reply_to_message):
                    if hasattr(update.message.reply_to_message.from_user, 'username'):
                        _user = update.message.reply_to_message.from_user.username
                    else:
                        _user = update.message.reply_to_message.from_user.first_name

                    def_txt = f'<@{_user}> {str(update.message.reply_to_message.text)}'

                elif lib.message_contains_media(update.message.reply_to_message):
                    # Obtener el tipo de medio actual
                    media_type = next(media_type for media_type in allowed_media_types if hasattr(update.message.reply_to_message, media_type))
                    print("media type:", media_type)
                    if hasattr(update.message.reply_to_message.from_user, 'username'):
                        _user = update.message.reply_to_message.from_user.username
                    else:
                        _user = update.message.reply_to_message.from_user.first_name

                    # Guardar la referencia del mensaje para usarla más tarde
                    message_id = update.message.reply_to_message.message_id
                    # Obtener el file_id de la foto
                    file_id = update.message.reply_to_message.photo[-1].file_id
                    def_txt = f'.tg_reply_to:{message_id}:{file_id}'

            # Manejar mensajes directos con medios
            # FIXME: No funca pq cmd viene desde text, buscar otra forma
            elif lib.message_contains_media(update.message):
                media_type = next(media_type for media_type in allowed_media_types if hasattr(update.message, media_type))
                print("media type:", media_type)
                if hasattr(update.message.from_user, 'username'):
                    _user = update.message.from_user.username
                else:
                    _user = update.message.from_user.first_name

                # Guardar la referencia del mensaje para usarla más tarde
                message_id = update.message.message_id
                # Obtener el file_id de la foto
                file_id = update.message.photo[-1].file_id
                def_txt = f'.tg_reply_to:{message_id}:{file_id}'

            # Manejar mensajes directos que solo contienen texto
            elif update.message.text:
                def_txt = update.message.text

            else:
                response = 'Expected definition, found NUL.'
                bot.send_message(chat_id=chat_id, text=response)
                return
            
        try:
            lib.add_def(key, int(time.time()), '@' + username + ' (Telegram)', learn_flags, def_txt)
        except(sqlite3.IntegrityError):
            response = "key *%s* already exists" % key
            bot.send_message(chat_id=chat_id, text=response, parse_mode='Markdown')
            return
        
        if def_txt == '':
            response = 'Learned blank entry for *%s*. (Why did you do that?)' % key
        else:
            response = 'Learned *%s*.' % key
        bot.send_message(chat_id=chat_id, text=response, parse_mode='Markdown')

    # parse "!forget key" requests
    elif cmd == '!forget':
        if not lib.is_learner(username):
            return

        data = shlex.split(text)
        # remove !command from data
        _ = lib.pop_first(data)

        # check if force flag
        force = False
        if data[0] == '-f':
            _ = lib.pop_first(data)
            if lib.is_admin(username): force = True

        # get key
        try:
            key = lib.pop_first(data)
        except:
            bot.send_message(chat_id=chat_id, text="Expected key, found NUL.")
            return
        
        if lib.is_def_locked(key) and force == False:
            response = 'Can\'t forget: Key is locked.'
            bot.send_message(chat_id=chat_id, text=response)
            return
        
        lib.del_key(key)

        response = 'Removed *%s*.' % key
        bot.send_message(chat_id=chat_id, text=response, parse_mode='Markdown')

    # parse "!lock key" requests
    elif cmd == '!lock':
        if not lib.is_admin(username):
            return

        data = shlex.split(text)
        # remove !command from data
        _ = lib.pop_first(data)

        # get key
        try:
            key = lib.pop_first(data)
        except:
            bot.send_message(chat_id=chat_id, text="Expected key, found NUL.")
            return
        
        lib.lock_key(key)

        response = 'Locked *%s*.' % key
        bot.send_message(chat_id=chat_id, text=response, parse_mode='Markdown')

    # parse "!unlock key" requests
    elif cmd == '!unlock':
        if not lib.is_admin(username):
            return

        data = shlex.split(text)
        # remove !command from data
        _ = lib.pop_first(data)

        # get key
        try:
            key = lib.pop_first(data)
        except:
            bot.send_message(chat_id=chat_id, text="Expected key, found NUL.")
            return
        
        lib.unlock_key(key)

        response = 'Unlocked *%s*.' % key
        bot.send_message(chat_id=chat_id, text=response, parse_mode='Markdown')

    # parse "!listkeys" requests
    elif cmd == '!listkeys':
        data = shlex.split(text)
        # remove !command from data
        _ = lib.pop_first(data)

        # get key
        try:
            key = lib.pop_first(data)
        except:
            bot.send_message(chat_id=chat_id, text="Expected key, found NUL.")
            return

        total, results = lib.find_keys(key)

        response = 'Matched %s key(s): %s' % (total, results)
        bot.send_message(chat_id=chat_id, text=response)

    # parse "!find" requests
    elif cmd == '!find':
        data = shlex.split(text)
        # remove !command from data
        _ = lib.pop_first(data)

        # get key
        try:
            key = lib.pop_first(data)
        except:
            bot.send_message(chat_id=chat_id, text="Expected key, found NUL.")
            return

        total, results = lib.find_value(key)

        response = 'Matched %s key(s): %s' % (total, results)
        bot.send_message(chat_id=chat_id, text=response)

    # AI handler (groups: mention required, private: auto if enabled)
    elif ai_enabled:
        # Determine if AI should respond
        should_respond = False

        # Initialize responded_to_message_ids if needed (chat_history already initialized above)
        if not str(chat_id) in globvars.responded_to_message_ids:
            globvars.responded_to_message_ids[str(chat_id)] = set()

        # Get current message ID
        message_id = update.message.message_id

        # Check if we've already responded to this message (avoid duplicates)
        already_responded = message_id in globvars.responded_to_message_ids[str(chat_id)]

        # Use reply_to_message for Python 3.6/older telegram library (defined for both private and group)
        reply_msg = getattr(update.message, 'reply_to_message', getattr(update.message, 'reply_message', None))

        if update.message.chat.type == 'private':
            # Private chat: respond if ai_enable_private is True and not already responded
            should_respond = ai_enable_private and not already_responded
        else:
            # Group chat: respond if bot is mentioned in text OR in reply OR replying to bot
            bot_mention = f"@{bot.username}"
            # Should respond if:
            # 1. Bot is mentioned in the message text, OR
            # 2. Bot is mentioned in the replied message, OR
            # 3. User is replying directly to a bot message (no mention needed)
            # BUT: Never respond if the message itself is from the bot (avoid self-reply loop)
            # AND: Never respond if we've already responded to this message
            should_respond = user_id != bot.id and not already_responded and (
                bot_mention in text or \
                (reply_msg and bot_mention in (reply_msg.text or reply_msg.caption or '')) or \
                (reply_msg and reply_msg.from_user.id == bot.id)
            )
        
        if should_respond:
            # Extract question (remove bot mention if present)
            bot_mention = f"@{bot.username}"
            if bot_mention in text:
                question = text.replace(bot_mention, '').strip()
            else:
                question = text.strip()
            
            if question:
                # Get chat context
                chat_history = globvars.chat_history.get(str(chat_id), [])
                context_messages = ai.build_context(chat_history, ai_context_size)

                # If replying to bot message, add that message to context for better relevance
                if reply_msg and reply_msg.from_user.id == bot.id:
                    context_msg = {
                        'author': 'You',  # Bot
                        'text': reply_msg.text or reply_msg.caption or ''
                    }
                    # Insert reply message at the beginning of context
                    context_messages.insert(0, context_msg)
                    # Pass message_id so bot replies to the USER's message (not the bot's)
                    reply_to_message_id = update.message.message_id
                elif reply_msg:
                    # Reply to any message (not from bot)
                    reply_to_message_id = reply_msg.message_id
                else:
                    reply_to_message_id = None

                # Submit to AI worker (non-blocking)
                ai_worker_instance.submit(chat_id, context_messages, question, config, reply_to_message_id, message_id)

def error(bot, update, a):
    """Log Errors caused by Updates."""
    logger.warning('Update "%s" caused error "%s"', bot, update)

def sig_handler(signum, frame):
    print("Saving config...")
    lib.save_config(config)
    ai_worker_instance.stop()

def main():
    # Debug
    import sys
    print(f"DEBUG [main start]: __name__={__name__}", file=sys.stderr)
    print(f"DEBUG [main start]: sys.argv={sys.argv}", file=sys.stderr)
    
    # Import modules inside main() to ensure proper initialization order
    from lib import globvars
    print(f"DEBUG [main import globvars]: globvars.config_file={globvars.config_file}", file=sys.stderr)
    
    from lib import lib
    from lib import ai_worker
    from lib import bot_commands
    
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='Krypton Telegram Bot')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Enable verbose/debug logging')
    parser.add_argument('--config', '-c', type=str, default='config.json',
                        help='Path to config file (default: config.json)')
    args = parser.parse_args()
    
    print(f"DEBUG [args]: args={args}", file=sys.stderr)
    # Set logging level based on verbose flag
    log_level = logging.DEBUG if args.verbose else logging.INFO
    
    # Enable logging
    logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                        level=log_level)

    logger = logging.getLogger(__name__)

    # Set config file BEFORE importing lib
    config_path = args.config if hasattr(args, 'config') and args.config else './config.json'
    logger.info(f"DEBUG: Setting config_file to '{config_path}'")
    globvars.config_file = config_path
    
    # Debug: check if globvars.config_file was set
    logger.info(f"DEBUG: globvars.config_file = '{globvars.config_file}'")
    
    # Now load config (globvars.config_file is already set)
    config = lib.load_config()
    
    # Extract AI settings from config
    ai_context_size = config.get('ai_context_size', 50)
    ai_enabled = config.get('ai_enabled', False)
    ai_enable_private = config.get('ai_enable_private', False)
    ai_rate_limit = config.get('ai_rate_limit_seconds', 5)
    
    lib.open_db()
    logger.info("Using config file: %s" % globvars.config_file)

    
    updater = Updater(token=config["telegram_token"], user_sig_handler=sig_handler)
    dp = updater.dispatcher

    # Initialize AI worker if enabled
    if ai_enabled:
        ai_worker_instance = ai_worker.AIWorker(rate_limit_seconds=ai_rate_limit)
        ai_worker_instance.start(updater.bot)

    # on different commands - answer in Telegram
    dp.add_handler(CommandHandler("getcfg", bot_commands.proc_command))
    dp.add_handler(CommandHandler("getadmins", bot_commands.proc_command))
    dp.add_handler(CommandHandler("getlearners", bot_commands.proc_command))
    dp.add_handler(CommandHandler("addadmin", bot_commands.proc_command))
    dp.add_handler(CommandHandler("addlearner", bot_commands.proc_command))
    dp.add_handler(CommandHandler("dellearner", bot_commands.proc_command))
    dp.add_handler(CommandHandler("deladmin", bot_commands.proc_command))
    dp.add_handler(CommandHandler("reloadcfg", bot_commands.proc_command))
    dp.add_handler(CommandHandler("savecfg", bot_commands.proc_command))
    dp.add_handler(CommandHandler("getchatid", bot_commands.proc_command))
    dp.add_handler(CommandHandler("globvars", bot_commands.proc_command))
    dp.add_handler(CommandHandler("getuserid", bot_commands.proc_command))
    dp.add_handler(CommandHandler("kick", bot_commands.proc_command))
    dp.add_handler(CommandHandler("op", bot_commands.proc_command))
    dp.add_handler(CommandHandler("deop", bot_commands.proc_command))
    dp.add_handler(CommandHandler("listgroups", bot_commands.proc_command))
    dp.add_handler(CommandHandler("listmembers", bot_commands.proc_command))

    # text message handler
    dp.add_handler(MessageHandler(Filters.all, proc_message))

    # log all errors
    #dp.add_error_handler(error)
    # Start the Bot
    updater.start_polling()
    updater.idle()


# Global config (loaded in main())
config = None

if __name__ == '__main__':
    main()