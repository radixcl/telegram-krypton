import html
import json
import logging
import time

from lib import globvars, lib

logger = logging.getLogger(__name__)

COMMANDS = {}  # name -> telegram handler, filled by @command and registered in bot.main()

def command(name, private=False, admin=True):
    """Register /name. Silently ignored unless the caller is a bot admin
    (admin=True) and, if private=True, the chat is private.
    The function receives (update, context, params)."""
    def deco(fn):
        def handler(update, context):
            user = update.message.from_user
            if admin and not lib.is_admin(user.username or str(user.id)):
                return
            if private and update.effective_chat.type != 'private':
                return
            fn(update, context, lib.parse_args(update.effective_message.text))
        COMMANDS[name] = handler
        return fn
    return deco

def get_chat_members(bot, chat_id, tracked_ids=()):
    """
    Get members of a chat. The Bot API cannot list all members, so this asks
    for the admins plus every id we have tracked, and resolves each one.

    Returns:
        List of dicts with user info (users who already left are skipped)
    """
    try:
        ids = {a.user.id for a in bot.get_chat_administrators(chat_id)}
    except Exception as e:
        logger.error(f"Error getting chat administrators: {e}")
        ids = set()
    ids |= set(tracked_ids)

    members = []
    for uid in ids:
        try:
            member = bot.get_chat_member(chat_id, uid)
        except Exception as e:
            logger.debug(f"get_chat_member {uid} failed: {e}")
            continue
        if member.status == 'left':
            continue
        user = member.user
        members.append({
            'id': user.id,
            'username': user.username or 'No username',
            'full_name': ' '.join(p for p in (user.first_name, user.last_name) if p),
            'is_admin': member.status in ('administrator', 'creator'),
            'is_member': member.status in ('member', 'administrator', 'creator', 'restricted'),
            'is_outside': member.status == 'kicked',
            'is_bot': user.is_bot
        })
    return members

def redact_config(config):
    """Copy of config with secrets masked, safe to print in a chat."""
    return {k: ('***' if k in ('telegram_token', 'ai_api_key') else v) for k, v in config.items()}


def _target_id(update, context, params):
    """user id of the first param (@username) from users_track, or None after replying."""
    if not params:
        lib.send(update, context, 'Missing parameter')
        return None
    name = params[0].lstrip('@')
    user_id = globvars.users_track.get(name)
    if user_id is None:
        lib.send(update, context, 'Unable to find user id for %s' % name)
    return user_id

@command('reloadcfg')
def reloadcfg(update, context, params):
    lib.load_config()
    lib.send(update, context, 'reloadcfg: done!')

@command('savecfg')
def savecfg(update, context, params):
    err = None
    try:
        lib.save_config(globvars.config)
    except Exception as ex:
        err = ex
    lib.send(update, context, 'savecfg: FAILED!' if err else 'savecfg: done!')
    if err and update.effective_chat.type == 'private':
        lib.send(update, context, str(err))

@command('getchatid', admin=False)
def getchatid(update, context, params):
    lib.send(update, context, 'Chat ID: %s' % update.effective_chat.id)

@command('getuserid')
def getuserid(update, context, params):
    if not params:
        lib.send(update, context, 'Missing parameter')
        return
    name = params[0].lstrip('@')
    lib.send(update, context, 'ID for %s is: %s' % (name, globvars.users_track.get(name, 'Unknown!')))

@command('getcfg', private=True)
def getcfg(update, context, params):
    lib.send(update, context, '```json\n%s```' % json.dumps(redact_config(globvars.config), indent=2), 'Markdown')

@command('globvars', private=True)
def show_globvars(update, context, params):
    items = {k: getattr(globvars, k) for k in dir(globvars) if not k.startswith('__')}
    if items.get('config'):
        items['config'] = redact_config(items['config'])
    lib.send(update, context, '```json\n%s```' % json.dumps(items, indent=2, default=str), 'Markdown')

def _show(key):
    def cmd(update, context, params):
        lib.send(update, context, '```python\n%s```' % globvars.config.get(key), 'Markdown')
    return cmd

def _add(key):
    def cmd(update, context, params):
        globvars.config.setdefault(key, []).extend(p.lstrip('@') for p in params)
        lib.send(update, context, 'Done.')
    return cmd

def _del(key, label):
    def cmd(update, context, params):
        names = globvars.config.setdefault(key, [])
        response = ''
        for p in params:
            try:
                names.remove(p.lstrip('@'))
            except ValueError:
                response += '%s *%s* not found.\n' % (label, p.lstrip('@'))
        lib.send(update, context, response + 'Done.', 'Markdown')
    return cmd

command('getadmins', private=True)(_show('admins'))
command('getlearners', private=True)(_show('learners'))
command('addadmin', private=True)(_add('admins'))
command('deladmin', private=True)(_del('admins', 'Admin'))
command('addlearner')(_add('learners'))
command('dellearner')(_del('learners', 'Learner'))

@command('kick')
def kick(update, context, params):
    user_id = _target_id(update, context, params)
    if user_id is None:
        return
    ban_until = int(time.time())
    try:
        ban_until += int(params[1])  # optional ban duration in seconds
    except (IndexError, ValueError):
        pass
    try:
        context.bot.kick_chat_member(update.effective_chat.id, user_id, until_date=ban_until)
    except Exception as ex:
        lib.send(update, context, str(ex))

def _promote(enable):
    def cmd(update, context, params):
        user_id = _target_id(update, context, params)
        if user_id is None:
            return
        try:
            context.bot.promote_chat_member(update.effective_chat.id, user_id,
                can_change_info=enable,
                can_invite_users=enable,
                can_restrict_members=enable,
                can_pin_messages=enable,
                can_promote_members=False)
        except Exception as ex:
            lib.send(update, context, str(ex))
    return cmd

command('op')(_promote(True))
command('deop')(_promote(False))

@command('listgroups', private=True)
def listgroups(update, context, params):
    groups = globvars.groups_name_track
    if not groups:
        lib.send(update, context, 'No groups found. The bot is not active in any groups yet.')
        return

    response = '<b>📁 Groups where Krypton is active:</b>\n\n'
    response += f'<b>Total:</b> <code>{len(groups)}</code> groups\n\n<b>List:</b>\n'
    for i, (group_id, group_title) in enumerate(sorted(groups.items(), key=lambda x: int(x[0])), 1):
        response += f'{i}. <code>{group_id}</code> - <b>{html.escape(group_title)}</b>\n'
    response += '\n<b>Note:</b> This list shows groups that have been tracked since the bot started.'
    lib.send(update, context, response, 'HTML')

@command('listmembers', private=True)
def listmembers(update, context, params):
    if not params:
        lib.send(update, context, 'Usage: /listmembers <group_name or chat_id>')
        return

    query = ' '.join(params)
    bot = context.bot

    try:
        # exact chat_id, or case-insensitive title match
        if query in globvars.groups_name_track:
            chats = [(query, globvars.groups_name_track[query])]
        else:
            chats = [(cid, title) for cid, title in globvars.groups_name_track.items()
                     if query.lower() in title.lower()]

        if not chats:
            lib.send(update, context, f'No chats found with name <b>{html.escape(query)}</b>', 'HTML')
            return

        if len(chats) > 1:
            lines = [f'{i}. <code>{cid}</code>: {html.escape(title)}' for i, (cid, title) in enumerate(chats, 1)]
            lib.send(update, context, f'Found {len(chats)} matching chats:\n\n' + '\n'.join(lines) +
                     '\n\nRepeat the command with the exact chat_id.', 'HTML')
            return

        target_chat_id, target_chat_title = chats[0]
        tracked = globvars.groups_member_track.get(str(target_chat_id), [])
        members = get_chat_members(bot, int(target_chat_id), tracked)

        try:
            total = bot.get_chat_member_count(int(target_chat_id))
        except Exception:
            total = len(members)

        response = f'<b>Members of {html.escape(target_chat_title)}</b>\n'
        response += f'<b>Total:</b> {total} (showing {len(members)} known to the bot)\n\n'

        groups = [
            ('Admins', [m for m in members if m['is_admin'] and not m['is_bot'] and not m['is_outside']], 20),
            ('Members', [m for m in members if m['is_member'] and not m['is_admin'] and not m['is_bot']], 20),
            ('Kicked', [m for m in members if m['is_outside'] and not m['is_bot']], 10),
            ('Bots', [m for m in members if m['is_bot']], 10),
        ]
        for title, group, limit in groups:
            if not group:
                continue
            response += f'<b>{title} ({len(group)}):</b>\n'
            for m in group[:limit]:
                response += f'  <code>{html.escape(m["username"])}</code> (<b>{html.escape(m["full_name"])}</b>)\n'
            if len(group) > limit:
                response += f'  ... and {len(group) - limit} more\n'
            response += '\n'

        # Telegram limit is 4096 chars; split on line boundaries so HTML tags aren't cut
        chunk = ''
        for line in response.splitlines(keepends=True):
            if len(chunk) + len(line) > 4000:
                lib.send(update, context, chunk, 'HTML')
                chunk = ''
            chunk += line
        if chunk:
            lib.send(update, context, chunk, 'HTML')

    except Exception as ex:
        logger.error(f"Error getting listmembers: {ex}")
        lib.send(update, context, f'Error: {ex}')

@command('help', private=True)
def help_cmd(update, context, params):
    """General help, or /help <command> for a specific one."""
    if params:
        param = ' '.join(params)
        text = get_command_help(param) or (
            f"<b>❌ Comando no encontrado:</b> <code>{html.escape(param)}</code>\n\n"
            "<b>📚 Usa</b> <code>/help</code> <b>para ver todos los comandos disponibles.</b>")
    else:
        text = HELP_TEXT
    lib.send(update, context, text, 'HTML')


HELP_TEXT = """<b>📚 Krypton Bot - Comandos Disponibles</b>

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
