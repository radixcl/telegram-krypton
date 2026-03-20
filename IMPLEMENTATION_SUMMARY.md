# Implementación: Comando /listmembers

## Resumen

Se agregó un nuevo comando `/listmembers <nombre_del_grupo>` al bot de Telegram que permite obtener la lista actual de miembros de un grupo usando la API de Telegram Bot API.

## Archivos Modificados

### 1. lib/bot_commands.py
- **Agregado**: Función `get_chat_members(bot, chat_id, limit=None)`
  - Obtiene miembros de un chat usando la API de Telegram
  - Retorna lista de dicts con información detallada de cada miembro
  - Maneja paginación automática
  - Maneja errores de la API

- **Agregado**: Comando `/listmembers` en `proc_command()`
  - Busca grupos por título (insensible a mayúsculas/minúsculas)
  - Maneja múltiples resultados mostrando opciones
  - Categoriza miembros en: Admins, Members, Kicked, Bots
  - Muestra hasta 20 admins/members y 10 bots/kicked
  - Respuesta formatada con Markdown y emojis
  - Paginación automática para mensajes > 4000 caracteres

### 2. bot.py
- **Agregado**: Registro del nuevo comando
  ```python
  dp.add_handler(CommandHandler("listmembers", bot_commands.proc_command))
  ```

### 3. README.md
- **Recreado**: Documentación completa del bot con lista de todos los comandos

### 4. LISTMEMBERS.md (nuevo)
- Documentación detallada del nuevo comando

## Características Implementadas

1. **Búsqueda por título**: Busca grupos por nombre usando `globvars.groups_name_track`
2. **Manejo de múltiples resultados**: Si hay varios grupos con nombres similares, lista las opciones
3. **Categorización inteligente**:
   - 👑 Admins: Miembros con permisos de administrador
   - 👤 Members: Miembros normales
   - ⚠️ Kicked: Miembros expulsados
   - 🤖 Bots: Bots en el grupo
4. **Límites de salida**: Muestra máximo 20 por categoría para evitar mensajes muy largos
5. **Formato Markdown**: Respuesta formateada con emojis y negritas
6. **Paginación automática**: Si el mensaje excede 4000 caracteres, se envía en 2 partes

## Uso

```bash
# Listar miembros de un grupo
/listmembers nombre_del_grupo

# Si hay múltiples grupos con nombres similares
/listmembers nombre_similar
→ Muestra lista de grupos encontrados
→ Pide especificar chat_id o usar número
```

## Ejemplo de Salida

```
📋 Members of *Mi Grupo*
👥 Total: *150* members

👑 Admins (3):
  • @admin1 (*Admin User*)
  • @admin2 (*Another Admin*)
  • @admin3 (*Group Owner*)

👤 Members (145):
  • @user1 (*John Doe*)
  • @user2 (*Jane Smith*)
  ... and 143 more

🤖 Bots (2):
  • @telegram (*Telegram Bot*)
```

## Ventajas sobre el Método Anterior

| Característica | Método Anterior (Tracking Manual) | Nuevo Método (API) |
|----------------|-----------------------------------|-------------------|
| **Precisión** | Puede quedar desactualizado | Siempre actualizado |
| **Persistencia** | Se pierde al reiniciar | No requiere persistencia |
| **Tamaño de datos** | Crece indefinidamente | Solo miembros actuales |
| **Verificación** | Basado en eventos | API oficial de Telegram |
| **Información completa** | Solo user_ids | Info completa (nombre, status, etc.) |

## Testing

```bash
# Verificar sintaxis
python -m py_compile lib/bot_commands.py bot.py

# Verificar importación
python -c "from lib import bot_commands; print('OK')"
```

## Notas

- El comando requiere permisos de administrador
- Solo funciona en chats donde el bot tiene permisos para obtener miembros
- La API puede tener límites de tasa, se manejan errores automáticamente
- Los miembros sin username se muestran como "No username"
