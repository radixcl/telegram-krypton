import shlex
import json
import time
from lib import globvars
from lib import lib

config = lib.load_config()

def proc_command(bot, update):
    global config
    chat_id = update.message.chat.id
    chat_title = update.message.chat.title
    chat_type = update.message.chat.type
    text = update.message.text
    if update.message.from_user.username is not None:
        username = update.message.from_user.username
    else:
        username = "%s %s" % (update.message.from_user.first_name, update.message.from_user.last_name)
    
    try:
        command = shlex.split(text)[0]
        params = shlex.split(text)[1:]
    except ValueError:
        command = text.split()[0]
        params = text.split()[1:]
    
    #print("command", command)
    #print("params", params)

    if command == '/reloadcfg' and lib.is_admin(username):
        config = lib.load_config()
        response = 'reloadcfg: done!'
        bot.send_message(chat_id=chat_id, text=response)
        return

    elif command == '/savecfg' and lib.is_admin(username):
        ex = None
        try:
            lib.save_config(config)
            response = 'savecfg: done!'
        except Exception as ex:
            response = 'savecfg: FAILED!'

        bot.send_message(chat_id=chat_id, text=response)
        if chat_type == 'private' and ex is not None:
            bot.send_message(chat_id=chat_id, text=ex)
        
        return

    elif command == '/getuserid' and lib.is_admin(username):
        try:
            username = params[0]
        except:
            bot.send_message(chat_id=chat_id, text='Missing parameter', parse_mode='Markdown')
            return
        
        if username[0] == '@': username = username[1:]
        resp = 'ID for %s is: %s' % (username, globvars.users_track.get(username, 'Unknown!'))
        bot.send_message(chat_id=chat_id, text=resp, parse_mode='Markdown')
        return

    elif command == '/getcfg' and lib.is_admin(username) and chat_type == 'private':
        response = json.dumps(config, indent=2)
        response = ("```json\n%s```" % response)
        bot.send_message(chat_id=chat_id, text=response, parse_mode='Markdown')
        return

    elif command == '/getadmins' and lib.is_admin(username) and chat_type == 'private':
        response = config.get('admins')
        response = ("```python\n%s```" % response)
        bot.send_message(chat_id=chat_id, text=response, parse_mode='Markdown')
        return

    elif command == '/addadmin' and lib.is_admin(username) and chat_type == 'private':
        admins = config.get('admins', [])
        for i in params:
            if i[0] == '@': i = i[1:]   # remove @ from the username
            admins.append(i)
        config["admins"] = admins
        response = "Done."
        bot.send_message(chat_id=chat_id, text=response, parse_mode='Markdown')
        return

    elif command == '/deladmin' and lib.is_admin(username) and chat_type == 'private':
        admins = config.get('admins', [])
        response = ''
        for i in params:
            if i[0] == '@': i = i[1:]   # remove @ from the username
            try:
                admins.remove(i)
            except ValueError:
                response += "Admin *%s* not found.\n" % i
                continue
        config["admins"] = admins
        response += "Done."
        bot.send_message(chat_id=chat_id, text=response, parse_mode='Markdown')

    elif command == '/getlearners' and lib.is_admin(username) and chat_type == 'private':
        response = config.get('learners')
        response = ("```python\n%s```" % response)
        bot.send_message(chat_id=chat_id, text=response, parse_mode='Markdown')
        return

    elif command == '/addlearner' and lib.is_admin(username):
        learners = config.get('learners', [])
        for i in params:
            if i[0] == '@': i = i[1:]   # remove @ from the username
            learners.append(i)
        config["learners"] = learners
        response = "Done."
        bot.send_message(chat_id=chat_id, text=response, parse_mode='Markdown')
        return

    elif command == '/dellearner' and lib.is_admin(username):
        learners = config.get('learners', [])
        response = ''
        for i in params:
            if i[0] == '@': i = i[1:]   # remove @ from the username
            try:
                learners.remove(i)
            except ValueError:
                response += "Learner *%s* not found.\n" % i
                continue
        config["learners"] = learners
        response += "Done."
        bot.send_message(chat_id=chat_id, text=response, parse_mode='Markdown')
        return

    elif command == '/globvars' and lib.is_admin(username) and chat_type == 'private':
        response = [(item, getattr(globvars, item)) for item in dir(globvars) if not item.startswith("__")]
        print(response)
        response = json.dumps(response, indent=2, default=lambda o: str(o))
        response = ("```json\n%s```" % response)
        bot.send_message(chat_id=chat_id, text=response, parse_mode='Markdown')
        return
    
    elif command == '/kick' and lib.is_admin(username):
        try:
            username = params[0]
        except:
            bot.send_message(chat_id=chat_id, text='Missing parameter')
            return
        
        # ban time
        try:
            ban_time = int(params[1])
            ban_time = int(time.time()) + ban_time
        except:
            ban_time = int(time.time())
        
        if username[0] == '@': username = username[1:]
        user_id = globvars.users_track.get(username, None)

        if user_id is None:
            bot.send_message(chat_id=chat_id, text='Unable to find user id for %s' % username)
            return
        try:
            bot.kick_chat_member(chat_id, user_id, None, ban_time)
            #bot.send_message(chat_id=chat_id, text='Ban time for %s: %s' % (username, ban_time), parse_mode='Markdown')
        except Exception as ex:
            bot.send_message(chat_id=chat_id, text=str(ex), parse_mode='Markdown')
        return

    elif (command == '/op' or command == '/deop') and lib.is_admin(username):
        try:
            username = params[0]
        except:
            bot.send_message(chat_id=chat_id, text='Missing parameter', parse_mode='Markdown')
            return

        if username[0] == '@': username = username[1:]
        user_id = globvars.users_track.get(username, None)

        if user_id is None:
            bot.send_message(chat_id=chat_id, text='Unable to find user id for %s' % username, parse_mode='Markdown')
            return

        try:
            if command == '/deop':
                bot.promote_chat_member(chat_id, user_id,
                    can_change_info=False,
                    #can_post_messages=True,
                    #can_edit_messages=False,
                    #can_delete_messages=False,
                    can_invite_users=False,
                    can_restrict_members=False,
                    can_pin_messages=False,
                    can_promote_members=False
                    )
            elif command == '/op':
                bot.promote_chat_member(chat_id, user_id,
                    can_change_info=True,
                    #can_post_messages=True,
                    #can_edit_messages=False,
                    #can_delete_messages=False,
                    can_invite_users=True,
                    can_restrict_members=True,
                    can_pin_messages=True,
                    can_promote_members=False
                )
        except Exception as ex:
            bot.send_message(chat_id=chat_id, text=str(ex), parse_mode='Markdown')
        return
