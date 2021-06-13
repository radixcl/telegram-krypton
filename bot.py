#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Krypton telegram bot
# - Matias Fernandez <matias.fernandez@gmail.com>
#

import sys
import logging

from telegram import Update, ForceReply
import telegram
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext

import sqlite3
import time
import json
import shlex
import pickle

from lib import globvars
try:
    globvars.config_file = sys.argv[1]
except:
    globvars.config_file = './config.json'

from lib import lib
from lib import bot_commands

from pprint import pprint

conn = lib.conn
c = lib.c
config = lib.load_config()

# Enable logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    level=logging.INFO)

logger = logging.getLogger(__name__)

def proc_message(update: Update, context: CallbackContext) -> None:
    #chat_id = update.message.chat.id
    chat_id = update.effective_chat.id
    user = update.effective_user
    user_id = user.id
    bot = context.bot
    text = update.message.text
    verbose = False

    print(str(update))

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
        res_txt = res_txt.replace('%n', '`@' + username + '`')
        response = '*%s* == `%s`' % (res[0], res_txt)
        if verbose == True:
            response += '\n_(author: %s) (%s)' % (res[2], time.ctime(int(res[1]))) + '_'
        
        try:
            bot.send_message(chat_id=chat_id, text=response, parse_mode='Markdown')
        except:
            # FIXME
            bot.send_message(chat_id=chat_id, text='`ERROR CTM! (FIXME)`', parse_mode='Markdown')
    
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
        
        if def_txt == '':
            if hasattr(update.message, 'reply_to_message') and hasattr(update.message.reply_to_message, 'from_user'):
                if hasattr(update.message.reply_to_message.from_user, 'username'):
                    _user = update.message.reply_to_message.from_user.username
                else:
                    _user = update.message.reply_to_message.from_user.first_name

                def_txt = f'<@{_user}> {str(update.message.reply_to_message.text)}'

            #update.message.reply_text(str(update.message.reply_to_message.text))
            #bot.send_message(chat_id=chat_id, text=".", reply_to_message_id=467)
            #bot.send_message(chat_id=chat_id, text=def_txt)
            #return

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

def error(bot, update, a):
    """Log Errors caused by Updates."""
    logger.warning('Update "%s" caused error "%s"', bot, update)

def sig_handler(signum, frame):
    print("Saving config...")
    lib.save_config(config)

def main():
    lib.open_db()
    logger.info("Using config file: %s" % globvars.config_file)

    updater = Updater(token=config["telegram_token"], user_sig_handler=sig_handler)
    dp = updater.dispatcher

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

    # text message handler
    dp.add_handler(MessageHandler(Filters.all, proc_message))

    # log all errors
    #dp.add_error_handler(error)
    # Start the Bot
    updater.start_polling()
    updater.idle()


if __name__ == '__main__':
    main()