import html
import json
import logging
import re
import time

from lib import chatgpt, globvars, lib

logger = logging.getLogger(__name__)

COMMANDS = {}  # name -> telegram handler, filled by @command and registered in bot.main()
COMMAND_POLICIES = {}  # name -> (admin-only, private-chat-only)

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
        COMMAND_POLICIES[name] = (admin, private)
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

@command('setcfg', private=True)
def setcfg(update, context, params):
    """Set one config value using JSON: /setcfg key <JSON value>."""
    text = update.effective_message.text
    match = re.match(r'^/setcfg(?:@\S+)?\s+(\S+)\s+(.+)$', text, re.S)
    if not match:
        lib.send(update, context, 'Uso: /setcfg clave valor_JSON')
        return

    key, raw_value = match.groups()
    try:
        value = json.loads(raw_value)
    except ValueError:
        lib.send(update, context, 'Valor JSON inválido. Ejemplos: true, 30, "texto", ["a", "b"]')
        return

    if key in globvars.config and type(value) is not type(globvars.config[key]):
        lib.send(update, context, 'El valor debe mantener el tipo actual de %s.' % key)
        return

    previous = globvars.config.get(key, None)
    had_key = key in globvars.config
    globvars.config[key] = value
    try:
        lib.save_config(globvars.config)
    except Exception:
        if had_key:
            globvars.config[key] = previous
        else:
            del globvars.config[key]
        logger.exception('Could not save config key %s', key)
        lib.send(update, context, 'No se pudo guardar la configuración.')
        return

    lib.send(update, context, 'Configuración guardada: %s.' % key)

_chatgpt_login = {}  # pending two-step OAuth login (verifier/state/expiry)

@command('loginchatgpt', private=True)
def loginchatgpt(update, context, params):
    """Two steps: /loginchatgpt gives the URL, then paste the callback URL."""
    if not params:
        url, verifier, state = chatgpt.start_login()
        _chatgpt_login.update(verifier=verifier, state=state, expires=time.time() + 900)
        safe = html.escape(url)
        lib.send(update, context,
                 '<b>Login de ChatGPT</b>\n\n'
                 '1. Abre esta URL y entra con tu cuenta ChatGPT:\n'
                 '<a href="%s">%s</a>\n\n'
                 '2. Al terminar, el navegador irá a <code>localhost:1455</code> y dará error de '
                 'conexión (es normal). Copia la URL completa de la barra de direcciones.\n\n'
                 '3. Envíala aquí:\n<code>/loginchatgpt URL_completa</code>\n\n'
                 'Caduca en 15 minutos.' % (safe, safe), 'HTML')
        return
    if not _chatgpt_login or time.time() > _chatgpt_login.get('expires', 0):
        lib.send(update, context, 'No hay login pendiente (o caducó). Empieza con /loginchatgpt.')
        return
    ok, message = chatgpt.complete_login(globvars.config, params[0],
                                         _chatgpt_login['verifier'], _chatgpt_login['state'])
    if ok:
        _chatgpt_login.clear()
    lib.send(update, context, html.escape(message), 'HTML')

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
    """Show admin command help, or details for one command."""
    if params:
        param = ' '.join(params)
        text = get_command_help(param) or (
            f"<b>❌ Comando no encontrado:</b> <code>{html.escape(param)}</code>\n\n"
            "<b>📚 Usa</b> <code>/help</code> <b>para ver todos los comandos disponibles.</b>")
    else:
        text = HELP_TEXT
    lib.send(update, context, text, 'HTML')


COMMAND_HELP = {
    'addadmin': ('Añade administradores del bot.', '/addadmin @usuario [...]', 'Actualiza la lista; úsalo en privado.'),
    'addlearner': ('Da permiso para usar los comandos de aprendizaje.', '/addlearner @usuario [...]', 'Los administradores también tienen este permiso.'),
    'deop': ('Retira los permisos de administración de grupo a un usuario.', '/deop @usuario', 'El usuario debe estar identificado en el seguimiento del bot.'),
    'deladmin': ('Retira administradores del bot.', '/deladmin @usuario [...]', 'Actualiza la lista; úsalo en privado.'),
    'dellearner': ('Retira el permiso de aprendiz.', '/dellearner @usuario [...]', ''),
    'getadmins': ('Muestra la lista de administradores del bot.', '/getadmins', 'Solo en privado.'),
    'getcfg': ('Muestra la configuración con los secretos ocultos.', '/getcfg', 'Solo en privado.'),
    'getchatid': ('Muestra el ID del chat actual.', '/getchatid', 'Disponible para todos.'),
    'getlearners': ('Muestra la lista de aprendices.', '/getlearners', 'Solo en privado.'),
    'getuserid': ('Busca el ID de un usuario conocido por su nombre de usuario.', '/getuserid @usuario', 'El usuario debe haber sido visto por el bot.'),
    'globvars': ('Muestra variables de estado del bot; oculta las claves secretas de configuración.', '/globvars', 'Solo en privado.'),
    'help': ('Muestra los comandos o la ayuda detallada de uno.', '/help [comando]', 'Solo en privado. Ejemplo: /help setcfg.'),
    'kick': ('Expulsa (banea) a un usuario del grupo.', '/kick @usuario [duración_segundos]', 'Sin duración, el baneo es temporal y se libera inmediatamente. El usuario debe haber sido visto por el bot.'),
    'listgroups': ('Lista los grupos registrados por el bot desde que se inició.', '/listgroups', 'Solo en privado.'),
    'listmembers': ('Lista miembros conocidos de un grupo.', '/listmembers <nombre_o_chat_id>', 'Solo en privado. El bot no puede enumerar miembros que nunca ha observado.'),
    'loginchatgpt': ('Vincula una suscripción ChatGPT mediante inicio de sesión OAuth.', '/loginchatgpt [URL_de_callback]', 'Solo en privado. Primero solicita la URL y después envía la URL completa de callback.'),
    'op': ('Promueve a un usuario con permisos de administración de grupo.', '/op @usuario', 'El usuario debe estar identificado por el bot y este debe tener permisos suficientes.'),
    'reloadcfg': ('Recarga la configuración desde el archivo.', '/reloadcfg', ''),
    'savecfg': ('Guarda en disco la configuración actual.', '/savecfg', ''),
    'setcfg': ('Cambia una opción de configuración usando un valor JSON y la guarda.', '/setcfg <clave> <valor_JSON>', 'Solo en privado. Ejemplos: /setcfg ai_enabled true · /setcfg ai_context_size 30 · /setcfg ai_model_id "proveedor/modelo".'),
}

KB_COMMAND_HELP = {
    '??': ('Consulta una definición de la base de conocimiento.', '?? <clave>', 'Añade -a antes de la clave para incluir autor y fecha: ?? -a <clave>. Disponible para todos.'),
    '!learn': ('Añade una definición; también puede aprender el mensaje al que respondes.', '!learn [-l] [-f] <clave> [definición]', '-l bloquea la entrada y -f permite a administradores reemplazar una existente. Usuarios aprendices o administradores.'),
    '!forget': ('Elimina una definición.', '!forget [-f] <clave>', '-f permite a administradores eliminar entradas bloqueadas. Usuarios aprendices o administradores.'),
    '!lock': ('Bloquea una definición para que no pueda borrarse sin -f.', '!lock <clave>', 'Solo administradores.'),
    '!unlock': ('Desbloquea una definición.', '!unlock <clave>', 'Solo administradores.'),
    '!listkeys': ('Busca claves de la base de conocimiento.', '!listkeys <patrón>', 'El comodín * coincide con cualquier texto. Disponible para todos.'),
    '!find': ('Busca texto dentro de las definiciones.', '!find <texto>', 'El comodín * coincide con cualquier texto. Disponible para todos.'),
}
KB_COMMAND_ACCESS = {
    '??': 'Disponible para todos',
    '!learn': 'Aprendices y administradores',
    '!forget': 'Aprendices y administradores',
    '!lock': 'Solo administradores',
    '!unlock': 'Solo administradores',
    '!listkeys': 'Disponible para todos',
    '!find': 'Disponible para todos',
}


def _command_policy(name):
    admin, private = COMMAND_POLICIES.get(name, (False, False))
    access = 'Solo administradores' if admin else 'Disponible para todos'
    if private:
        access += '; solo en privado'
    return access


def _help_entry(name, description, usage, notes='', access=None):
    lines = [f'<b>{html.escape(name)}</b> — {html.escape(description)}',
             f'<b>Uso:</b> <code>{html.escape(usage)}</code>']
    if access:
        lines.append(f'<b>Acceso:</b> {html.escape(access)}')
    if notes:
        lines.append(html.escape(notes))
    return '\n'.join(lines)


def _build_help_text():
    lines = ['<b>📚 Ayuda de Krypton para administradores</b>',
             'Usa <code>/help comando</code> para ver detalles y ejemplos.']
    for title, names in (
            ('Administración', sorted(COMMANDS)),
            ('Base de conocimiento', sorted(KB_COMMAND_HELP))):
        lines.extend(['', f'<b>{title}</b>'])
        for name in names:
            details = COMMAND_HELP.get(name)
            if details:
                description = details[0]
            else:
                description = 'Ayuda general de comandos.'
            lines.append(f'<code>/{name}</code> — {html.escape(description)}' if name in COMMANDS
                         else f'<code>{html.escape(name)}</code> — {html.escape(description)}')
    return '\n'.join(lines)


HELP_TEXT = _build_help_text()


def get_command_help(command_name: str) -> str:
    """Return detailed help for a registered bot or knowledge-base command."""
    command_name = command_name.lower().strip().split('@', 1)[0]
    if command_name.startswith('/'):
        command_name = command_name[1:]

    if command_name in KB_COMMAND_HELP:
        description, usage, notes = KB_COMMAND_HELP[command_name]
        return _help_entry(command_name, description, usage, notes,
                           KB_COMMAND_ACCESS[command_name])

    details = COMMAND_HELP.get(command_name)
    if not details or command_name not in COMMANDS:
        return None
    description, usage, notes = details
    return _help_entry('/' + command_name, description, usage, notes,
                       _command_policy(command_name))
