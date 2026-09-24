# Tools the AI can call (OpenAI-style tool calling).
# Each tool: fn(args, config, ctx) -> str.  ctx = {'chat_id':..., 'user':...} of the asker.
# Everything a tool returns is untrusted text for the model, never instructions.

import ast
import ipaddress
import json
import logging
import operator
import re
import socket
import time
from html import unescape
from urllib.parse import urljoin, urlparse

import requests

from lib import lib

logger = logging.getLogger(__name__)

TOOLS = {}  # name -> (schema, fn)


def tool(description, params, required):
    def deco(fn):
        schema = {"type": "function", "function": {
            "name": fn.__name__, "description": description,
            "parameters": {"type": "object", "properties": params, "required": required}}}
        TOOLS[fn.__name__] = (schema, fn)
        return fn
    return deco


def active_schemas(config, ctx):
    """Tools that can work with this config/context."""
    skip = set()
    if not config.get('tavily_api_key'):
        skip.add('web_search')
    if not (ctx or {}).get('chat_id'):
        skip.add('set_reminder')
    return [schema for name, (schema, _) in TOOLS.items() if name not in skip]


def run_tool(call, config, ctx):
    """Execute one tool call from the model; errors go back to the model as text."""
    try:
        name = call['function']['name']
        if name not in TOOLS:
            return f"Unknown tool: {name}"
        args = json.loads(call['function']['arguments'] or '{}')
        logger.info("AI tool %s: %s", name, args)
        return str(TOOLS[name][1](args, config, ctx or {}))
    except Exception as e:
        logger.warning("AI tool call failed: %s", e)
        return f"Tool error: {e}"


# --- web ----------------------------------------------------------------------

@tool("Search the web for current information. Returns titles, URLs and snippets.",
      {"query": {"type": "string"}}, ["query"])
def web_search(args, config, ctx):
    # Tavily: plain REST, works on PyPy
    r = requests.post("https://api.tavily.com/search", timeout=20,
                      headers={"Authorization": f"Bearer {config['tavily_api_key']}"},
                      json={"query": args['query'], "max_results": 5})
    r.raise_for_status()
    return "\n".join(f"{x['title']} - {x['url']}\n{x['content']}" for x in r.json()['results']) or "No results."


def _check_public(url):
    """Reject non-http(s) URLs and hosts resolving to private/loopback/link-local addresses."""
    p = urlparse(url)
    if p.scheme not in ('http', 'https') or not p.hostname:
        raise ValueError("only http(s) URLs are allowed")
    for info in socket.getaddrinfo(p.hostname, p.port or 443, type=socket.SOCK_STREAM):
        if not ipaddress.ip_address(info[4][0]).is_global:
            raise ValueError("private address blocked")


@tool("Fetch a web page and return its text (first 4000 characters).",
      {"url": {"type": "string"}}, ["url"])
def fetch_url(args, config, ctx):
    url = args['url']
    for _ in range(4):  # follow redirects by hand so every hop is checked
        # ponytail: DNS is resolved twice (check, then connect); pin the IP if rebinding matters
        _check_public(url)
        r = requests.get(url, timeout=10, stream=True, allow_redirects=False,
                         headers={"User-Agent": "Mozilla/5.0 (telegram-bot)"})
        if not r.is_redirect:
            break
        url = urljoin(url, r.headers.get('Location', ''))
        r.close()
    else:
        raise ValueError("too many redirects")
    try:
        r.raise_for_status()
        ctype = r.headers.get('Content-Type', '').lower()
        if not ctype.startswith(('text/', 'application/xhtml', 'application/json')):
            return f"Unsupported content type: {ctype}"
        raw = r.raw.read(200_000, decode_content=True)
    finally:
        r.close()
    text = raw.decode(r.encoding if 'charset' in ctype else 'utf-8', errors='replace')
    if 'html' in ctype:
        text = re.sub(r'(?is)<(script|style|noscript).*?</\1>', ' ', text)
        text = re.sub(r'(?s)<[^>]+>', ' ', text)
    return re.sub(r'\s+', ' ', unescape(text)).strip()[:4000] or "Empty page."


INSTAGRAM_PATH = re.compile(r'^/(?:[\w.]+/)?(p|reel|reels|tv)/([\w-]+)')
INSTAGRAM_CDN = ('.fbcdn.net', '.cdninstagram.com')
MAX_MEDIA_BYTES = 45_000_000  # Telegram bots can upload up to 50 MB


@tool("Show the image/video of an instagram.com post or reel in the chat. The bot downloads it and "
      "sends it itself; afterwards just add a short comment, without links.",
      {"url": {"type": "string"}}, ["url"])
def instagram_preview(args, config, ctx):
    p = urlparse(args['url'].strip())
    m = INSTAGRAM_PATH.match(p.path)
    if p.scheme not in ('http', 'https') or (p.hostname or '').removeprefix('www.') != 'instagram.com' or not m:
        raise ValueError("not an instagram.com post/reel URL")
    if ctx.get('media'):
        return "A preview is already attached."
    # ponytail: scrapes Instagram's public embed page (no login, may change without notice).
    # Only the first item of a carousel; no caption.
    r = requests.get(f"https://www.instagram.com/{m.group(1)}/{m.group(2)}/embed/captioned/", timeout=15,
                     headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    # video_url sits inside JSON that is itself inside a JS string: two levels of escaping
    v = re.search(r'video_url\\":\\"(.*?)\\"', r.text)
    i = re.search(r'class="EmbeddedMediaImage"[^>]*?src="([^"]+)"', r.text)
    media_url = json.loads('"' + json.loads('"' + v.group(1) + '"') + '"') if v else unescape(i.group(1)) if i else ''
    host = urlparse(media_url).hostname or ''
    if not host.endswith(INSTAGRAM_CDN):
        raise ValueError("could not get the media (private or removed post?)")
    _check_public(media_url)
    with requests.get(media_url, timeout=30, stream=True) as d:
        d.raise_for_status()
        kind = d.headers.get('Content-Type', '').split('/')[0]
        if kind not in ('image', 'video'):
            raise ValueError("unexpected media type")
        data = d.raw.read(MAX_MEDIA_BYTES + 1, decode_content=True)
    if len(data) > MAX_MEDIA_BYTES:
        raise ValueError("media too large")
    ctx.setdefault('media', []).append((kind, data))  # sent by the AI worker with the reply
    return f"Preview ({'video' if kind == 'video' else 'image'}) attached; it will be sent with your reply."


# --- knowledge base (the "??" / "!find" data) -----------------------------------

@tool("Look up an entry in the group's knowledge base (what '?? key' shows).",
      {"key": {"type": "string"}}, ["key"])
def kb_lookup(args, config, ctx):
    res = lib.get_def(args['key'])
    if res is None:
        return "Entry not found."
    return "(a stored photo)" if res[4].startswith('.tg_reply_to:') else res[4][:1000]


@tool("Search the group's knowledge base: keys and values containing some text.",
      {"text": {"type": "string"}}, ["text"])
def kb_search(args, config, ctx):
    pattern = '*' + args['text'] + '*'
    n_keys, keys = lib.find_keys(pattern)
    n_vals, vals = lib.find_value(pattern)
    return f"Keys matching ({n_keys}): {keys}\nEntries whose text matches ({n_vals}): {vals}"


# --- calculator ---------------------------------------------------------------

_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
        ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod,
        ast.Pow: operator.pow, ast.USub: operator.neg, ast.UAdd: operator.pos}


def _calc(node):
    if isinstance(node, ast.Constant) and type(node.value) in (int, float):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        left, right = _calc(node.left), _calc(node.right)
        if isinstance(node.op, ast.Pow) and (abs(right) > 100 or abs(left) > 1e100):
            raise ValueError("power too large")
        return _OPS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_calc(node.operand))
    raise ValueError("unsupported expression (numbers and + - * / // % ** only)")


@tool("Evaluate an arithmetic expression exactly, e.g. '(12.5 + 3) * 4 / 7'. Operators: + - * / // % **.",
      {"expression": {"type": "string"}}, ["expression"])
def calculator(args, config, ctx):
    expr = args['expression']
    if len(expr) > 200:
        raise ValueError("expression too long")
    return _calc(ast.parse(expr.strip(), mode='eval').body)


# --- reminders (delivered by bot.send_due_reminders) ----------------------------

MAX_PENDING_REMINDERS = 5
MAX_REMINDER_MINUTES = 60 * 24 * 30


@tool("Set a reminder: the bot will post the text in this chat, mentioning the user, after some minutes.",
      {"minutes": {"type": "integer", "description": "minutes from now (1 to 43200)"},
       "text": {"type": "string", "description": "what to remind, max 200 chars"}},
      ["minutes", "text"])
def set_reminder(args, config, ctx):
    minutes = int(args['minutes'])
    if not 1 <= minutes <= MAX_REMINDER_MINUTES:
        raise ValueError(f"minutes must be between 1 and {MAX_REMINDER_MINUTES}")
    if lib.count_reminders(ctx['chat_id'], ctx.get('user')) >= MAX_PENDING_REMINDERS:
        return f"Too many pending reminders (max {MAX_PENDING_REMINDERS})."
    lib.add_reminder(ctx['chat_id'], ctx.get('user'), int(time.time()) + minutes * 60, args['text'][:200])
    return f"Reminder set for {minutes} minute(s) from now."
