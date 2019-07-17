#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Krypton telegram bot
# - Matias Fernandez <matias.fernandez@gmail.com>
#

import sys
import logging
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters
import sqlite3
import time
import json
import shlex

from lib import globvars
try:
    globvars.config_file = sys.argv[1]
except:
    globvars.config_file = './config.json'

from lib import lib

conn = lib.conn
c = lib.c
config = lib.config

# Enable logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    level=logging.INFO)

logger = logging.getLogger(__name__)

def proc_message(bot, update):
    chat_id = update.message.chat_id
    text = update.message.text
    verbose = False
    if update.message.from_user.username is not None:
        username = update.message.from_user.username
    else:
        username = "%s %s" % (update.message.from_user.first_name, update.message.from_user.last_name)

    # parse "?? definition" queries
    if text[:2] == '??':
        data = shlex.split(text)
        if len(data) < 2:
            bot.send_message(chat_id=chat_id, text="Expected key, found NUL.")
            return

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
        bot.send_message(chat_id=chat_id, text=response, parse_mode='Markdown')
    
    # parse "!learn key value" requests
    elif text[:6] == '!learn':
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
    elif text[:7] == '!forget':
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
    elif text[:5] == '!lock':
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
    elif text[:7] == '!unlock':
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
    elif text[:9] == '!listkeys':
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
    elif text[:5] == '!find':
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


def main():
    lib.open_db()
    logger.info("Using config file: %s" % globvars.config_file)

    updater = Updater(config["telegram_token"])
    dp = updater.dispatcher

    # on different commands - answer in Telegram
    #dp.add_handler(CommandHandler("start", start))
    # on noncommand i.e message - echo the message on Telegram
    dp.add_handler(MessageHandler(Filters.text, proc_message))
    # log all errors
    dp.add_error_handler(error)
    # Start the Bot
    updater.start_polling()
    updater.idle()


if __name__ == '__main__':
    main()