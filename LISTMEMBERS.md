# Comando /listmembers

## Descripción

Obtiene la lista actual de miembros de un grupo específico usando la API de Telegram Bot API.

## Sintaxis

```
/listmembers <nombre_del_grupo>
```

## Ejemplos

```
/listmembers mi_grupo
/listmembers mi grupo de trabajo
```

## Salida

El comando devuelve una lista detallada de miembros organizada en las siguientes categorías:

- 👑 **Admins**: Miembros con permisos de administrador
- 👤 **Members**: Miembros normales
- ⚠️ **Kicked**: Miembros expulsados/baneados
- 🤖 **Bots**: Bots en el grupo

## Características

- **Búsqueda por título**: Busca el grupo por su nombre
- **Múltiples resultados**: Si encuentra varios grupos con nombres similares, lista las opciones
- **Límite de salida**: Muestra hasta 20 admins/members y 10 bots/kicked por categoría
- **Formato Markdown**: Respuesta formateada con emojis y negritas
- **Paginación automática**: Si la respuesta excede 4000 caracteres, se envía en 2 partes

## Requerimientos

El comando solo funciona para usuarios con permisos de administrador.

## Notas

- Los miembros sin username se muestran como "No username"
- Los nombres con guiones bajos (_) se reemplazan por espacios para mejor legibilidad
- La búsqueda es insensible a mayúsculas/minúsculas
