# ChatGPT subscription provider.
# Login once with "python3 bot.py --login-chatgpt" (OAuth, same flow Codex CLI uses),
# then set ai_provider="chatgpt" and ai_model_id="gpt-5.1".
# Requests go to the ChatGPT backend (Responses API), not api.openai.com.

import base64
import hashlib
import json
import logging
import os
import re
import secrets
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

import requests

from lib import ai_tools, globvars

logger = logging.getLogger(__name__)

AUTH_URL = 'https://auth.openai.com/oauth/authorize'
TOKEN_URL = 'https://auth.openai.com/oauth/token'
API_URL = 'https://chatgpt.com/backend-api/codex/responses'
CLIENT_ID = 'app_EMoamEEZ73f0CkXaXp7hrann'  # Codex CLI's public OAuth client
REDIRECT_URI = 'http://localhost:1455/auth/callback'
SCOPE = 'openid profile email offline_access'

PREVIEW_ASK = re.compile(r'preview|vista previa|previsualiz', re.I)
LINK = re.compile(r'https?://\S+')


# --- tokens -------------------------------------------------------------------

def _auth_file(config):
    """Token file: ai_chatgpt_auth_file (relative to the config) or chatgpt_auth.json next to it."""
    base = os.path.dirname(os.path.abspath(globvars.config_file or 'config.json'))
    path = (config or {}).get('ai_chatgpt_auth_file') or 'chatgpt_auth.json'
    return path if os.path.isabs(path) else os.path.join(base, path)


def load_tokens(config):
    try:
        with open(_auth_file(config)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def save_tokens(config, tokens):
    path = _auth_file(config)
    tmp = path + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(tokens, f, indent=2)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def _claims(token):
    try:
        payload = token.split('.')[1]
        payload += '=' * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload))
    except Exception:
        return {}


def _account_id(tokens):
    for key in ('id_token', 'access_token'):
        auth = _claims(tokens.get(key) or '').get('https://api.openai.com/auth') or {}
        if auth.get('chatgpt_account_id'):
            return auth['chatgpt_account_id']
    return tokens.get('account_id')


def _expired(tokens):
    exp = tokens.get('expires_at')
    if exp is None:
        exp = _claims(tokens.get('access_token') or '').get('exp')
    return exp is not None and int(exp) - 60 < time.time()


def _token_record(data):
    record = {
        'access_token': data.get('access_token'),
        'refresh_token': data.get('refresh_token'),
        'id_token': data.get('id_token'),
        'expires_at': int(time.time()) + int(data.get('expires_in') or 3600),
    }
    record['account_id'] = _account_id(record)
    return record


def _refresh(config, tokens):
    try:
        response = requests.post(TOKEN_URL, json={
            'client_id': CLIENT_ID, 'grant_type': 'refresh_token',
            'refresh_token': tokens.get('refresh_token'), 'scope': SCOPE}, timeout=30)
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        logger.error("ChatGPT token refresh failed: %s", e)
        return None
    merged = dict(tokens)
    merged.update({k: v for k, v in _token_record(data).items() if v})
    merged['refresh_token'] = data.get('refresh_token') or tokens.get('refresh_token')
    try:
        save_tokens(config, merged)
    except OSError as e:  # keep using the in-memory token even if the disk write fails
        logger.warning("Could not save refreshed ChatGPT tokens: %s", e)
    return merged


def _tokens(config, force=False):
    tokens = load_tokens(config)
    if not tokens:
        logger.error("ChatGPT is not logged in. Run: python3 bot.py --login-chatgpt")
        return None
    if force or _expired(tokens):
        tokens = _refresh(config, tokens)
    return tokens


# --- login --------------------------------------------------------------------

def _exchange(code, verifier):
    try:
        response = requests.post(TOKEN_URL, json={
            'client_id': CLIENT_ID, 'grant_type': 'authorization_code', 'code': code,
            'redirect_uri': REDIRECT_URI, 'code_verifier': verifier}, timeout=30)
        response.raise_for_status()
        return _token_record(response.json())
    except Exception as e:
        logger.error("ChatGPT token exchange failed: %s", e)
        return None


def login(config):
    """Interactive OAuth login; saves the tokens and returns True on success."""
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
    state = secrets.token_urlsafe(16)
    url = AUTH_URL + '?' + urlencode({
        'response_type': 'code', 'client_id': CLIENT_ID, 'redirect_uri': REDIRECT_URI,
        'scope': SCOPE, 'code_challenge': challenge, 'code_challenge_method': 'S256',
        'state': state, 'id_token_add_organizations': 'true',
        'codex_cli_simplified_flow': 'true'})

    result = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if urlparse(self.path).path != '/auth/callback':
                self.send_response(404)
                self.end_headers()
                return
            query = parse_qs(urlparse(self.path).query)
            if 'code' in query:
                result.update(code=query['code'][0], state=(query.get('state') or [''])[0])
                self.send_response(200)
                body = b'Login complete. You can close this tab.'
            else:
                self.send_response(400)
                body = b'Missing code.'
            self.send_header('Content-Type', 'text/plain')
            self.end_headers()
            self.wfile.write(body)
            threading.Thread(target=self.server.shutdown, daemon=True).start()

        def log_message(self, *args):
            pass

    try:
        server = HTTPServer(('127.0.0.1', 1455), Handler)
    except OSError as e:
        logger.error("Cannot listen on localhost:1455 (%s). Close Codex or another login and retry.", e)
        return False
    threading.Thread(target=server.serve_forever, daemon=True).start()

    print('\nOpen this URL and sign in with your ChatGPT account:\n\n%s\n' % url)
    print('If the bot runs on a server, run this on a machine that can reach localhost:1455')
    print('or forward it: ssh -L 1455:localhost:1455 user@server\n')
    try:
        webbrowser.open(url)
    except Exception:
        pass

    deadline = time.time() + 300
    while not result and time.time() < deadline:
        time.sleep(0.5)
    server.shutdown()
    if not result:
        logger.error("ChatGPT login timed out.")
        return False
    if result.get('state') != state:
        logger.error("ChatGPT login failed: state mismatch.")
        return False
    tokens = _exchange(result['code'], verifier)
    if not tokens:
        return False
    save_tokens(config, tokens)
    print('Logged in. Tokens saved to %s' % _auth_file(config))
    return True


# --- Responses API ------------------------------------------------------------

def _headers(tokens):
    headers = {
        'Authorization': 'Bearer ' + (tokens.get('access_token') or ''),
        'Content-Type': 'application/json',
        'Accept': 'text/event-stream',
        'OpenAI-Beta': 'responses=experimental',
        'originator': 'codex_cli_rs',
    }
    if tokens.get('account_id'):
        headers['chatgpt-account-id'] = tokens['account_id']
    return headers


def _input(context_messages, query, images):
    items = []
    for msg in context_messages or []:
        role = 'assistant' if msg.get('author') == 'You' else 'user'
        text = msg.get('text') or ''
        if role == 'user':
            text = "%s: %s" % (msg.get('author'), text)
        items.append({'type': 'message', 'role': role, 'content': [
            {'type': 'output_text' if role == 'assistant' else 'input_text', 'text': text}]})
    content = [{'type': 'input_text', 'text': query or ''}]
    content += [{'type': 'input_image', 'image_url': url} for url in images or []]
    items.append({'type': 'message', 'role': 'user', 'content': content})
    return items


def _payload(config, model, instructions, items, schemas):
    payload = {
        'model': model,
        'instructions': instructions,
        'input': items,
        'stream': True,
        'store': False,
        'max_output_tokens': int(config.get('ai_max_output_tokens', 2048)),
        'reasoning': {'effort': config.get('ai_chatgpt_reasoning_effort', 'low')},
    }
    if schemas:
        payload['tools'] = [{
            'type': 'function',
            'name': schema['function']['name'],
            'description': schema['function'].get('description', ''),
            'parameters': schema['function'].get('parameters', {'type': 'object', 'properties': {}}),
        } for schema in schemas]
    return payload


def _parse_sse(response):
    """Collect streamed text deltas and output items (messages + function calls)."""
    text, done_text, items, final = [], [], [], None
    for raw in response.iter_lines(decode_unicode=True):
        if not raw:
            continue
        line = raw if isinstance(raw, str) else raw.decode('utf-8', 'replace')
        if not line.startswith('data:'):
            continue
        data = line[5:].strip()
        if not data or data == '[DONE]':
            continue
        try:
            event = json.loads(data)
        except ValueError:
            continue
        kind = event.get('type', '')
        if kind == 'response.output_text.delta':
            text.append(event.get('delta') or '')
        elif kind == 'response.output_text.done':
            done_text.append(event.get('text') or '')
        elif kind == 'response.output_item.done' and event.get('item'):
            items.append(event['item'])
        elif kind == 'response.completed':
            final = event.get('response') or {}
        elif kind in ('response.failed', 'error'):
            logger.error("ChatGPT stream error: %s", json.dumps(event)[:300])
            return None
    output = (final or {}).get('output') or items
    if not ''.join(text):
        text = done_text
    if not ''.join(text):
        for item in output:
            if item.get('type') == 'message':
                for part in item.get('content') or []:
                    if part.get('type') == 'output_text':
                        text.append(part.get('text') or '')
    return {'text': ''.join(text), 'items': output}


def _request(config, payload):
    retries = int(config.get('ai_retries', 2))
    timeout = (10, max(int(config.get('ai_timeout', 30)), 120))
    force_refresh = False
    for attempt in range(retries + 1):
        tokens = _tokens(config, force=force_refresh)
        force_refresh = False
        if not tokens:
            return None
        try:
            response = requests.post(API_URL, headers=_headers(tokens), json=payload,
                                     stream=True, timeout=timeout)
        except requests.exceptions.RequestException as e:
            logger.warning("ChatGPT API request failed: %s", e)
            if attempt < retries:
                time.sleep(1)
                continue
            return None
        try:
            if response.status_code == 401 and attempt == 0:
                force_refresh = True
                continue
            if response.status_code == 429 and attempt < retries:
                try:
                    wait = min(float(response.headers.get('Retry-After', 5)), 30)
                except ValueError:
                    wait = 5
                logger.warning("ChatGPT API rate limited (429), retrying in %.0fs", wait)
                time.sleep(wait)
                continue
            if response.status_code >= 400:
                logger.error("ChatGPT API error %s: %s", response.status_code, response.text[:300])
                return None
            return _parse_sse(response)
        except requests.exceptions.RequestException as e:
            logger.warning("ChatGPT stream failed: %s", e)
            if attempt < retries:
                time.sleep(1)
                continue
            return None
        finally:
            response.close()
    return None


def call_ai_api(context_messages, query, config, ctx=None, images=None, instructions=''):
    """Same contract as ai.call_ai_api, backed by the ChatGPT subscription."""
    model = config.get('ai_model_id')
    vision_model = config.get('ai_vision_model_id')
    # provider/model ids (e.g. OpenRouter) don't exist on the ChatGPT backend: fall back
    if images and vision_model and '/' not in vision_model:
        model = vision_model
    if not model:
        logger.error("ChatGPT provider needs ai_model_id")
        return None

    items = _input(context_messages, query, images)
    schemas = ai_tools.active_schemas(config, ctx) if config.get('ai_tools_enabled', False) else []
    max_rounds = int(config.get('ai_tools_max_rounds', 3))

    if schemas and ctx is not None and PREVIEW_ASK.search(query) and LINK.search(query):
        # small models echo the URL or write the call as text: don't leave it to them
        url = LINK.findall(query)[-1].rstrip(')>"\'.,')
        out = ai_tools.run_tool({'function': {'name': 'link_preview',
                                              'arguments': json.dumps({'url': url})}}, config, ctx)
        if ctx.get('media'):
            return 'ok'
        items.append({'type': 'message', 'role': 'user',
                      'content': [{'type': 'input_text', 'text': '[system] ' + out}]})
        schemas = []

    for round_ in range(max_rounds + 1):
        tools = schemas if schemas and round_ < max_rounds else []
        result = _request(config, _payload(config, model, instructions, items, tools))
        if result is None:
            return None
        calls = [item for item in result['items'] if item.get('type') == 'function_call']
        if not calls:
            text = result.get('text') or ''
            if '<tool_call>' in text:  # model wrote a call as text: don't show it
                logger.warning("AI answered with a raw tool call, dropping it")
                return None
            return text or None
        items.extend(result['items'])
        for call in calls:
            output = ai_tools.run_tool({'function': {
                'name': call.get('name', ''),
                'arguments': call.get('arguments') or '{}'}}, config, ctx)
            items.append({'type': 'function_call_output',
                          'call_id': call.get('call_id'), 'output': str(output)})
        if round_ == max_rounds - 1:  # next round has no tools
            items.append({'type': 'message', 'role': 'user', 'content': [
                {'type': 'input_text', 'text': 'No more tools available. Answer now with what you found.'}]})
    return None
