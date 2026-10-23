"""
AI Coach chatbot routes.

Provider: Meta Model API (Muse Spark) when MODEL_API_KEY is set, otherwise the old
Gemini chatbot (if GEMINI_API_KEY is set). The Meta coach can read the logged-in
athlete's own DeepFit data through the tools in deepfit_tools.py.
"""

import html
import os
import re
import traceback
import uuid

from bson import ObjectId
from flask import Blueprint, jsonify, render_template, request, session
from werkzeug.utils import secure_filename

from db_config import get_db
from deepfit_tools import AthleteContext

chatbot_bp = Blueprint('chatbot', __name__)

UPLOAD_FOLDER = 'uploads/chatbot'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

chatbot_instances = {}
MAX_INSTANCES = 200


def _meta_key():
    return os.environ.get("MODEL_API_KEY") or os.environ.get("META_API_KEY")


def provider_name(bot=None):
    """The model that answered last (or the chain that will be tried)."""
    if bot is not None and getattr(bot, 'last_label', None):
        return bot.last_label
    import llm
    chain = [r['label'] for r in llm.routes('chat')]
    if chain:
        return chain[0] + (' (+ fallback)' if len(chain) > 1 else '')
    if os.environ.get("GEMINI_API_KEY"):
        return "Gemini"
    return "not configured"


@chatbot_bp.route('/chatbot')
def chatbot_ui():
    """Render the chatbot UI page"""
    return render_template('chatbot.html')


def _chat_key():
    """One conversation per logged-in athlete (or per anonymous browser session)."""
    if session.get('user_id'):
        return 'u:' + str(session['user_id'])
    if 'chat_anon_id' not in session:
        session['chat_anon_id'] = uuid.uuid4().hex
    return 'a:' + session['chat_anon_id']


def get_chatbot(key):
    if key not in chatbot_instances:
        if len(chatbot_instances) >= MAX_INSTANCES:
            chatbot_instances.pop(next(iter(chatbot_instances)))
        import llm
        if llm.configured():
            from meta_chatbot import MetaChatbot
            chatbot_instances[key] = MetaChatbot()
        elif os.environ.get("GEMINI_API_KEY"):
            from gemini_chatbot import GeminiChatbot
            chatbot_instances[key] = GeminiChatbot(os.environ["GEMINI_API_KEY"])
        else:
            raise RuntimeError("No AI provider configured. Set MODEL_API_KEY or GROQ_API_KEY in .env")
    return chatbot_instances[key]


def _athlete_ctx():
    """Data access is always the logged-in athlete - never chosen by the model."""
    user_id = session.get('user_id')
    if not user_id:
        return None
    try:
        return AthleteContext(get_db(), user_id=user_id)
    except Exception:
        return None


def _ask(bot, method, *args):
    """Call the bot; Meta bot gets the athlete context, the old Gemini bot doesn't take one."""
    fn = getattr(bot, method)
    if bot.__class__.__name__ == 'MetaChatbot':
        return fn(*args, ctx=_athlete_ctx())
    return fn(*args)


def render_markdown_safe(text):
    """Very small, XSS-safe markdown -> HTML (bold, italics, bullets, numbered lists, code, line breaks)."""
    out, in_list = [], None
    for raw in (text or '').split('\n'):
        line = html.escape(raw)
        line = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', line)
        line = re.sub(r'(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])', r'<em>\1</em>', line)
        line = re.sub(r'`([^`]+)`', r'<code>\1</code>', line)
        m_ul = re.match(r'^\s*[-•*]\s+(.*)', line)
        m_ol = re.match(r'^\s*\d+[.)]\s+(.*)', line)
        m_h = re.match(r'^\s*#{1,6}\s+(.*)', line)
        kind = 'ul' if m_ul else ('ol' if m_ol else None)
        if in_list and kind != in_list:
            out.append(f'</{in_list}>')
            in_list = None
        if kind:
            if not in_list:
                out.append(f'<{kind} style="margin:4px 0 4px 18px;padding:0">')
                in_list = kind
            out.append(f'<li>{(m_ul or m_ol).group(1)}</li>')
        elif m_h:
            out.append(f'<strong>{m_h.group(1)}</strong><br>')
        elif line.strip():
            out.append(line + '<br>')
        else:
            out.append('<br>')
    if in_list:
        out.append(f'</{in_list}>')
    result = ''.join(out)
    return re.sub(r'(<br>)+$', '', result)


def _reply(text, bot=None):
    return jsonify({'response': text, 'response_html': render_markdown_safe(text), 'provider': provider_name(bot)})


@chatbot_bp.route('/api/chatbot/status')
def chatbot_status():
    import llm
    name = None
    if session.get('user_id'):
        try:
            u = get_db().users.find_one({'_id': ObjectId(session['user_id'])})
            name = (u or {}).get('name')
        except Exception:
            name = None
    return jsonify({'provider': provider_name(chatbot_instances.get(_chat_key())), 'logged_in': bool(session.get('user_id')),
                    'name': (name or '').split(' ')[0] or None, 'chain': [r['label'] for r in llm.routes('chat')]})


@chatbot_bp.route('/api/chatbot/message', methods=['POST'])
def send_message():
    try:
        data = request.get_json(silent=True) or {}
        message = (data.get('message') or '').strip()
        if not message:
            return jsonify({'error': 'Message is required'}), 400
        if len(message) > 4000:
            message = message[:4000]
        bot = get_chatbot(_chat_key())
        return _reply(_ask(bot, 'send_message', message), bot)
    except Exception as e:
        print(f"Error in send_message: {e}")
        print(traceback.format_exc())
        return jsonify({'error': f'Failed to get response: {str(e)}'}), 500


@chatbot_bp.route('/api/chatbot/image', methods=['POST'])
def send_image():
    try:
        if 'image' not in request.files:
            return jsonify({'error': 'No image provided'}), 400
        image = request.files['image']
        if image.filename == '':
            return jsonify({'error': 'Empty filename'}), 400
        message = request.form.get('message', 'What is in this image?')
        image_data = image.read()
        if len(image_data) > 10 * 1024 * 1024:
            return jsonify({'error': 'Image too large (max 10 MB)'}), 400
        bot = get_chatbot(_chat_key())
        return _reply(_ask(bot, 'send_message_with_image', message, image_data), bot)
    except Exception as e:
        print(f"Error in send_image: {e}")
        print(traceback.format_exc())
        return jsonify({'error': f'Failed to analyze image: {str(e)}'}), 500


@chatbot_bp.route('/api/chatbot/file', methods=['POST'])
def send_file():
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file provided'}), 400
        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'Empty filename'}), 400
        message = request.form.get('message', 'Analyze this file')
        filename = f"{uuid.uuid4().hex}_{secure_filename(file.filename)}"
        filepath = os.path.join(UPLOAD_FOLDER, filename)
        file.save(filepath)
        try:
            bot = get_chatbot(_chat_key())
            response = _ask(bot, 'analyze_file', message, filepath)
        finally:
            try:
                os.remove(filepath)
            except OSError:
                pass
        return _reply(response, bot)
    except Exception as e:
        print(f"Error in send_file: {e}")
        print(traceback.format_exc())
        return jsonify({'error': f'Failed to analyze file: {str(e)}'}), 500


@chatbot_bp.route('/api/chatbot/reset', methods=['POST'])
def reset_chat():
    try:
        chatbot_instances.pop(_chat_key(), None)
        return jsonify({'status': 'success', 'message': 'Chat history cleared'})
    except Exception as e:
        print(f"Error in reset_chat: {e}")
        return jsonify({'error': str(e)}), 500
