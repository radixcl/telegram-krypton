import shlex
import json
import time
import logging
from telegram import Update, ForceReply
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext

logger = logging.getLogger(__name__)

# Don't load config at import time - do it when commands are called
# This prevents globvars.config_file from being None before main() sets it

def get_chat_members(bot, chat_id, limit=None):
    """
    Get members of a chat using Telegram Bot API.
    
    Args:
        bot: Telegram Bot instance
        chat_id: Chat ID
        limit: Maximum number of members to retrieve (None = default)
    
    Returns:
        List of dicts with user info
    """
    members = []
    offset = None
    
    while True:
        try:
            if offset:
                params = {'chat_id': chat_id, 'limit': limit, 'offset': offset}
            else:
                params = {'chat_id': chat_id, 'limit': limit}
            
            result = bot.get_chat_members(chat_id, **params)
            
            for member in result:
                user_info = {
                    'id': member.user.id,
                    'username': member.user.username or 'No username',
                    'first_name': member.user.first_name or '',
                    'last_name': member.user.last_name or '',
                    'full_name': (member.user.first_name or '') + (
                        ' ' + (member.user.last_name or '') if member.user.last_name else ''
                    ).strip(),
                    'is_admin': member.status == 'administrator',
                    'is_member': member.status in ('member', 'administrator'),
                    'is_outside': member.status == 'kicked',
                    'is_bot': member.user.is_bot
                }
                members.append(user_info)
            
            if not result or len(members) >= limit:
                break
            offset = members[-1]['id']
            
        except Exception as e:
            logger.error(f"Error getting chat members: {e}")
            break
    
    return members

def proc_command(update: Update, context: CallbackContext) -> None:
    # Import modules and load config when command is called
    from lib import globvars
    from lib import lib

    # Use globvars.config which is loaded by bot.py
    config = globvars.config
    if config is None:
        config = lib.load_config()
        globvars.config = config

    bot = context.bot
    chat_id = update.effective_chat.id
    chat_title = update.effective_chat.title
    chat_type = update.effective_chat.type
    text = update.effective_message.text
    if update.message.from_user.username is not None:
        username = update.message.from_user.username
    else:
        username = "%s %s" % (update.message.from_user.first_name, update.message.from_user.last_name)

    logger.debug(f"DEBUG proc_command: chat_id={chat_id}, chat_type={chat_type}, username={username}")
    
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

    elif command == '/listgroups' and lib.is_admin(username) and chat_type == 'private':
        """List all groups where the bot is active"""
        try:
            # Get all tracked groups from globvars.groups_name_track
            groups = globvars.groups_name_track
            
            if not groups:
                bot.send_message(chat_id=chat_id, text='No groups found. The bot is not active in any groups yet.')
                return
            
            # Format response
            response = '<b>📁 Groups where Krypton is active:</b>\n\n'
            response += f'<b>Total:</b> <code>{len(groups)}</code> groups\n\n'
            response += '<b>List:</b>\n'
            
            # Sort by chat_id for consistency
            sorted_groups = sorted(groups.items(), key=lambda x: int(x[0]))
            
            for i, (chat_id, chat_title) in enumerate(sorted_groups, 1):
                response += f'{i}. <code>{chat_id}</code> - <b>{chat_title}</b>\n'
            
            # Add info about tracking
            response += '\n<b>Note:</b> This list shows groups that have been tracked since the bot started.'
            
            bot.send_message(chat_id=chat_id, text=response, parse_mode='HTML')
            
        except Exception as ex:
            logger.error(f"Error getting listgroups: {ex}")
            bot.send_message(chat_id=chat_id, text=f'Error: {str(ex)}')
        return

    elif command == '/listmembers' and lib.is_admin(username) and chat_type == 'private':
        if not params:
            bot.send_message(chat_id=chat_id, text='Usage: /listmembers <group_name>')
            return
        
        group_name = params[0]
        
        try:
            original_chat_id_for_response = chat_id
            logger.debug(f"DEBUG /listmembers: original_chat_id={original_chat_id_for_response}, group_name={group_name}")
            # Search for chat by title using globvars.groups_name_track
            chats = []
            for tracked_chat_id, tracked_chat_title in globvars.groups_name_track.items():
                if group_name.lower() in tracked_chat_title.lower():
                    chats.append({
                        'chat_id': tracked_chat_id,
                        'chat_title': tracked_chat_title
                    })
            
            if not chats:
                bot.send_message(chat_id=original_chat_id_for_response, text=f'No chats found with name <b>{group_name}</b>')
                return
            
            if len(chats) > 1:
                bot.send_message(chat_id=original_chat_id_for_response, text=f'Found {len(chats)} matching chats:\n\n')
                for i, c in enumerate(chats, 1):
                    bot.send_message(chat_id=original_chat_id_for_response, text=f'{i}. <b>{c["chat_id"]}</b>: {c["chat_title"]}')
                bot.send_message(chat_id=original_chat_id_for_response, text='\nPlease specify the exact chat_id or use one of the numbers above.')
                return
            
            target_chat_id = chats[0]['chat_id']
            target_chat_title = chats[0]['chat_title']

            # Get members
            members = get_chat_members(bot, target_chat_id)

            # Format response using HTML mode (emojis work better with HTML)
            response = f'<b>Members of {target_chat_title}</b>\n'
            response += f'<b>Total:</b> {len(members)} members\n\n'
            
            # Separate by type
            admins = [m for m in members if m['is_admin'] and not m['is_bot'] and not m['is_outside']]
            members_only = [m for m in members if m['is_member'] and not m['is_admin'] and not m['is_bot'] and not m['is_outside']]
            kicked = [m for m in members if m['is_outside'] and not m['is_bot']]
            
            if admins:
                response += f'<b>Admins ({len(admins)}):</b>\n'
                for m in admins[:20]:  # Limit to 20 for brevity
                    name = m['full_name'].replace('_', ' ')
                    username = m['username']
                    response += f'  <code>{username}</code> (<b>{name}</b>)\n'
                if len(admins) > 20:
                    response += f'  ... and {len(admins) - 20} more\n'
                response += '\n'
            
            if members_only:
                response += f'<b>Members ({len(members_only)}):</b>\n'
                for m in members_only[:20]:
                    name = m['full_name'].replace('_', ' ')
                    username = m['username']
                    response += f'  <code>{username}</code> (<b>{name}</b>)\n'
                if len(members_only) > 20:
                    response += f'  ... and {len(members_only) - 20} more\n'
                response += '\n'
            
            if kicked:
                response += f'<b>Kicked ({len(kicked)}):</b>\n'
                for m in kicked[:10]:
                    name = m['full_name'].replace('_', ' ')
                    username = m['username']
                    response += f'  <code>{username}</code> (<b>{name}</b>)\n'
                if len(kicked) > 10:
                    response += f'  ... and {len(kicked) - 10} more\n'
                response += '\n'
            
            # Add bots if any
            bots = [m for m in members if m['is_bot']]
            if bots:
                response += f'<b>Bots ({len(bots)}):</b>\n'
                for m in bots[:10]:
                    name = m['full_name'].replace('_', ' ')
                    username = m['username']
                    response += f'  <code>{username}</code> (<b>{name}</b>)\n'
                if len(bots) > 10:
                    response += f'  ... and {len(bots) - 10} more\n'
                response += '\n'
            
            # Send in chunks if too long
            if len(response) > 4000:
                # Send first part
                bot.send_message(chat_id=chat_id, text=response[:4097], parse_mode='HTML')
                # Send second part
                bot.send_message(chat_id=chat_id, text=response[4097:], parse_mode='HTML')
            else:
                bot.send_message(chat_id=chat_id, text=response, parse_mode='HTML')
            
        except Exception as ex:
            logger.error(f"Error getting listmembers: {ex}")
            bot.send_message(chat_id=chat_id, text=f'Error: {str(ex)}')
        return


def proc_help(update: Update, context: CallbackContext) -> None:
    """Send help message to admin in private chat."""
    from lib import globvars
    from lib import lib

    # Only work in private chats
    chat_type = update.effective_chat.type
    if chat_type != 'private':
        return

    bot = context.bot
    chat_id = update.effective_chat.id

    # Get username
    username = None
    if update.message.from_user.username is not None:
        username = update.message.from_user.username
    else:
        username = "%s %s" % (update.message.from_user.first_name, update.message.from_user.last_name)

    # Check if user is admin
    if not lib.is_admin(username):
        return

    # Load config
    config = globvars.config
    if config is None:
        config = lib.load_config()
        globvars.config = config

    # Parse command and optional parameter
    text = update.effective_message.text or ''
    parts = text.split(maxsplit=1)
    command = parts[0].lower()
    param = parts[1].strip() if len(parts) > 1 else None

    # If a command name is provided, show specific help
    if param:
        help_text = get_command_help(param)
        if help_text:
            bot.send_message(chat_id=chat_id, text=help_text, parse_mode='HTML')
        else:
            bot.send_message(chat_id=chat_id, text=f"<b>❌ Comando no encontrado:</b> <code>{param}</code>\n\n<b>📚 Usa</b> <code>/help</code> <b>para ver todos los comandos disponibles.</b>", parse_mode='HTML')
        return

    # Show general help
    help_text = """<b>📚 Krypton Bot - Comandos Disponibles</b>

<b>Comandos de Administración:</b>
  <code>/reloadcfg</code> - Recargar configuración
  <code>/savecfg</code> - Guardar configuración actual
  <code>/addadmin</code> - Añadir administrador
  <code>/deladmin</code> - Eliminar administrador
  <code>/addlearner</code> - Añadir aprendiz
  <code>/dellearner</code> - Eliminar aprendiz
  <code>/kick</code> - Expulsar usuario del grupo
  <code>/op</code> - Promover a administrador del grupo
  <code>/deop</code> - Quitar administración del grupo

<b>Comandos de Información:</b>
  <code>/getcfg</code> - Obtener configuración actual
  <code>/getadmins</code> - Listar administradores
  <code>/getlearners</code> - Listar aprendices
  <code>/globvars</code> - Ver variables globales
  <code>/getuserid</code> - Obtener ID de usuario
  <code>/getchatid</code> - Obtener ID del chat
  <code>/listgroups</code> - Listar grupos activos
  <code>/listmembers</code> - Listar miembros de un grupo
  <code>/help</code> - Mostrar esta ayuda

<b>💡 Tip:</b> Usa <code>/help &lt;comando&gt;</code> para ver ayuda específica de un comando.
"""

    bot.send_message(chat_id=chat_id, text=help_text, parse_mode='HTML')


def get_command_help(command_name: str) -> str:
    """Get help text for a specific command."""
    command_help = {
        '/reloadcfg': """<b>🔄 /reloadcfg</b>

<b>Descripción:</b> Recarga la configuración desde el archivo.

<b>Uso:</b> <code>/reloadcfg</code>

<b>Permisos:</b> Solo administradores

<b>Ejemplo:</b> <code>/reloadcfg</code>""",

        '/savecfg': """<b>💾 /savecfg</b>

<b>Descripción:</b> Guarda la configuración actual a disco.

<b>Uso:</b> <code>/savecfg</code>

<b>Permisos:</b> Solo administradores

<b>Ejemplo:</b> <code>/savecfg</code>""",

        '/addadmin': """<b>👑 /addadmin</b>

<b>Descripción:</b> Añade un usuario como administrador del bot.

<b>Uso:</b> <code>/addadmin @username</code>

<b>Permisos:</b> Solo administradores

<b>Ejemplo:</b> <code>/addadmin radix</code>""",

        '/deladmin': """<b>❌ /deladmin</b>

<b>Descripción:</b> Elimina un usuario como administrador del bot.

<b>Uso:</b> <code>/deladmin @username</code>

<b>Permisos:</b> Solo administradores

<b>Ejemplo:</b> <code>/deladmin radix</code>""",

        '/addlearner': """<b>📖 /addlearner</b>

<b>Descripción:</b> Añade un usuario como aprendiz (puede usar !learn).

<b>Uso:</b> <code>/addlearner @username</code>

<b>Permisos:</b> Solo administradores

<b>Ejemplo:</b> <code>/addlearner paoloandreotti</code>""",

        '/dellearner': """<b>📛 /dellearner</b>

<b>Descripción:</b> Elimina un usuario como aprendiz.

<b>Uso:</b> <code>/dellearner @username</code>

<b>Permisos:</b> Solo administradores

<b>Ejemplo:</b> <code>/dellearner paoloandreotti</code>""",

        '/kick': """<b>🚫 /kick</b>

<b>Descripción:</b> Expulsa a un usuario del grupo.

<b>Uso:</b> <code>/kick @username</code>

<b>Permisos:</b> Solo administradores

<b>Ejemplo:</b> <code>/kick troll_user</code>""",

        '/op': """<b>⬆️ /op</b>

<b>Descripción:</b> Promueve a un usuario a administrador del grupo.

<b>Uso:</b> <code>/op @username</code>

<b>Permisos:</b> Solo administradores

<b>Ejemplo:</b> <code>/op moderador</code>""",

        '/deop': """<b>⬇️ /deop</b>

<b>Descripción:</b> Remueve la administración de un usuario del grupo.

<b>Uso:</b> <code>/deop @username</code>

<b>Permisos:</b> Solo administradores

<b>Ejemplo:</b> <code>/deop exmod</code>""",

        '/getcfg': """<b>📋 /getcfg</b>

<b>Descripción:</b> Muestra la configuración actual del bot.

<b>Uso:</b> <code>/getcfg</code>

<b>Permisos:</b> Solo administradores

<b>Ejemplo:</b> <code>/getcfg</code>""",

        '/getadmins': """<b>👥 /getadmins</b>

<b>Descripción:</b> Lista los administradores del bot.

<b>Uso:</b> <code>/getadmins</code>

<b>Permisos:</b> Solo administradores

<b>Ejemplo:</b> <code>/getadmins</code>""",

        '/getlearners': """<b>📚 /getlearners</b>

<b>Descripción:</b> Lista los aprendices del bot.

<b>Uso:</b> <code>/getlearners</code>

<b>Permisos:</b> Solo administradores

<b>Ejemplo:</b> <code>/getlearners</code>""",

        '/globvars': """<b>🔧 /globvars</b>

<b>Descripción:</b> Muestra las variables globales del bot.

<b>Uso:</b> <code>/globvars</code>

<b>Permisos:</b> Solo administradores

<b>Ejemplo:</b> <code>/globvars</code>""",

        '/getuserid': """<b>🆔 /getuserid</b>

<b>Descripción:</b> Obtiene el ID de Telegram de un usuario.

<b>Uso:</b> <code>/getuserid @username</code>

<b>Permisos:</b> Solo administradores

<b>Ejemplo:</b> <code>/getuserid radix</code>""",

        '/getchatid': """<b>🏠 /getchatid</b>

<b>Descripción:</b> Obtiene el ID del chat actual.

<b>Uso:</b> <code>/getchatid</code>

<b>Permisos:</b> Todos los usuarios

<b>Ejemplo:</b> <code>/getchatid</code>""",

        '/listgroups': """<b>📁 /listgroups</b>

<b>Descripción:</b> Lista todos los grupos donde el bot está activo.

<b>Uso:</b> <code>/listgroups</code>

<b>Permisos:</b> Solo administradores

<b>Ejemplo:</b> <code>/listgroups</code>""",

        '/listmembers': """<b>👥 /listmembers</b>

<b>Descripción:</b> Lista los miembros de un grupo.

<b>Uso:</b> <code>/listmembers &lt;nombre_grupo&gt;</code>

<b>Permisos:</b> Solo administradores

<b>Ejemplo:</b> <code>/listmembers #Linux</code>""",

        '/help': """<b>📚 /help</b>

<b>Descripción:</b> Muestra ayuda general o ayuda específica de un comando.

<b>Uso:</b> <code>/help</code> o <code>/help &lt;comando&gt;</code>

<b>Permisos:</b> Solo administradores

<b>Ejemplo:</b> <code>/help</code> o <code>/help listmembers</code>"""
    }

    # Normalize command name
    command_name = command_name.lower().strip()
    if not command_name.startswith('/'):
        command_name = '/' + command_name

    return command_help.get(command_name, None)
