# Mejora: Todas las respuestas del bot se guardan en el historial de chat

## Resumen

Se ha implementado un sistema centralizado que asegura que **TODAS las respuestas del bot** se incluyan automáticamente en el historial de chat para mejorar el contexto de la IA.

## Problema Previo

Antes de esta mejora, solo las respuestas de la IA se guardaban en el historial de chat. Esto significaba que:

- ❌ El comando `??` no se guardaba → La IA no sabía qué definiciones había buscado el usuario
- ❌ Los comandos `!learn`, `!forget`, `!lock`, `!unlock` no se guardaban → La IA no conocía el vocabulario del chat
- ❌ Los mensajes de error no se guardaban → La IA no sabía qué fallaba
- ❌ Solo el historial de mensajes de usuario + IA responses

## Solución Implementada

### 1. Función Wrapper Centralizada

Se creó `send_message_with_history()` en `bot.py` que encapsula la lógica de:
1. Guardar el mensaje en `chat_history`
2. Enviar el mensaje a Telegram

```python
def send_message_with_history(chat_id, text, parse_mode='Markdown', author='You'):
    """
    Wrapper para enviar mensajes y registrarlos automáticamente en el historial de chat.
    Esto asegura que TODAS las respuestas del bot se incluyan en el contexto de IA.
    """
    # Agregar respuesta del bot al historial ANTES de enviar
    msg_record = {
        'author': author,
        'text': text,
        'timestamp': time.time()
    }
    globvars.chat_history[chat_id_str].append(msg_record)
    
    # Enviar mensaje a Telegram
    bot.send_message(chat_id=chat_id, text=text, parse_mode=parse_mode)
    
    return text
```

### 2. Modificaciones en `bot.py`

**Sección `??` (consulta de definiciones):**
```python
# Antes:
bot.send_message(chat_id=chat_id, text=response, parse_mode=answer_mode)
# Después:
send_message_with_history(chat_id, response, parse_mode=answer_mode, author=username)
```

**Sección `!learn`:**
```python
# Antes:
response = 'Learned *%s*.' % key
bot.send_message(chat_id=chat_id, text=response, parse_mode='Markdown')
# Después:
send_message_with_history(chat_id, response, parse_mode='Markdown', author=username)
```

**Sección `!forget`, `!lock`, `!unlock`, `!listkeys`, `!find`:**
```python
# Antes:
response = 'Removed *%s*.' % key
bot.send_message(chat_id=chat_id, text=response, parse_mode='Markdown')
# Después:
send_message_with_history(chat_id, response, parse_mode='Markdown', author=username)
```

### 3. Modificaciones en `ai_worker.py`

El worker de IA ya guardaba las respuestas, pero se actualizó para:
- Evitar duplicados cuando `send_message_with_history` también lo hace
- Añadir parámetro `already_saved` para controlar el comportamiento

```python
# Antes:
self._save_bot_response(chat_id, text, message_id)
# Después:
self._save_bot_response(chat_id, text, message_id, already_saved=False)
```

## Beneficios

### 1. Contexto Mejorado para IA

Ahora la IA tiene acceso a un historial completo que incluye:
- ✅ Mensajes de usuario
- ✅ Respuestas de `??` (definiciones consultadas)
- ✅ Respuestas de `!learn` (términos aprendidos)
- ✅ Respuestas de `!forget` (términos eliminados)
- ✅ Respuestas de `!lock` / `!unlock` (bloqueo/desbloqueo de términos)
- ✅ Respuestas de `!listkeys` / `!find` (búsquedas realizadas)
- ✅ Respuestas de IA
- ✅ Mensajes de error y confirmaciones

### 2. Estructura del Historial

El historial ahora contiene entries como:

```python
chat_history['123456'] = deque(maxlen=50)  # Últimos 50 mensajes

# Ejemplo de contenido:
[
    {'author': 'usuario1', 'text': '?? python', 'timestamp': 1234567890.0},
    {'author': 'You', 'text': 'python == lenguaje de programación', 'timestamp': 1234567891.0},
    {'author': 'usuario1', 'text': '!learn reactjs frontend', 'timestamp': 1234567892.0},
    {'author': 'You', 'text': 'Learned reactjs.', 'timestamp': 1234567893.0},
    {'author': 'usuario1', 'text': '@bot explain react', 'timestamp': 1234567894.0},
    {'author': 'You', 'text': 'React is... (AI response)', 'timestamp': 1234567895.0}
]
```

### 3. Rastreo de Contexto

La IA ahora puede:
- **Saber qué definiciones ha buscado el usuario** → Responder con información relevante
- **Conocer el vocabulario del chat** → Usar términos aprendidos en respuestas
- **Entender el estado del chat** → Saber qué fue bloqueado/eliminado
- **Mejorar respuestas contextualmente** → Basar respuestas en búsquedas previas

## Ejemplo de Flujo

```
Usuario: ?? python
↓
Bot: python == lenguaje de programación (guardado en historial)
↓
Usuario: @bot explain react
↓
Bot (AI): React is a JavaScript library for building user interfaces. 
         (guardado en historial, con contexto de búsquedas previas)
```

Ahora la IA sabe que el usuario busca información técnica y puede adaptar su respuesta.

## Archivos Modificados

| Archivo | Cambios |
|---------|---------|
| `bot.py` | Agrega `send_message_with_history()` y reemplaza todas las llamadas `bot.send_message` en los comandos de usuario |
| `lib/ai_worker.py` | Actualiza `_save_bot_response()` para evitar duplicados |
| `lib/globvars.py` | Sin cambios (ya tenía `chat_history`) |

## Verificación

```bash
# Verificar sintaxis
python3 -m py_compile bot.py lib/ai_worker.py

# Ejecutar y verificar que funcione
python3 bot.py --verbose
```

## Notas de Implementación

1. **Orden de guardado**: El mensaje se guarda en el historial ANTES de enviarlo a Telegram
2. **Author field**: 
   - Respuestas del bot: `author='You'`
   - Respuestas de error: `author=username` (para identificar quién lo pidió)
3. **Deque maxlen**: Se respeta la configuración `ai_context_size` del config.json
4. **Backwards compatible**: No afecta el comportamiento existente, solo mejora el contexto

## Próximas Mejoras Posibles

- [ ] Agregar timestamp más detallado (fecha/hora legible)
- [ ] Mantener historial persistente (guardar en disco)
- [ ] Filtrado avanzado de historial para IA
- [ ] Opción para excluir ciertos comandos del historial
