"""Stockroom Copilot - Streamlit UI, styled to match the final mockup.

Needs Streamlit 1.39 or newer (st.container(key=...) adds a CSS class that the
theme below relies on) and the three files: app.py and .streamlit/config.toml.

Run:  streamlit run app.py
Env:  API_BASE_URL (default http://127.0.0.1:8000/api)
"""
import html
import markdown
import math
import os
import uuid
from datetime import datetime
import subprocess
import sys
import time
import requests
import streamlit as st

def ensure_backend_running():
    """Start the FastAPI/FastMCP backend in the background if it's not already running."""
    try:
        # Quick health check on local port 8000
        res = requests.get("http://127.0.0.1:8000/api/mcp-status", timeout=1)
        if res.status_code == 200:
            return
    except Exception:
        pass  # Server is not running yet

    # Launch backend as a subprocess
    backend_env = os.environ.copy()
    subprocess.Popen(
        [sys.executable, "-m", "backend.app.api"],
        env=backend_env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Give backend 3 seconds to boot up and initialize SQLite DB
    time.sleep(3)

# Trigger launcher before Streamlit UI elements render
ensure_backend_running()

st.set_page_config(
    page_title='Stockroom Copilot | Carltren Supply',
    page_icon='\U0001F4E6',
    layout='wide',
    initial_sidebar_state='collapsed',
)

API_BASE_URL = os.environ.get('API_BASE_URL', 'http://127.0.0.1:8000/api').rstrip('/')

GREETING = 'Hi, I am your stockroom copilot. Ask what is about to run out, or ask me to draft purchase orders.'

SUGGESTIONS = [
    'What will stock out before my suppliers can deliver?',
    'Draft orders for the four worst ones.',
    'What is waiting for my approval?',
]

# ---------------------------------------------------------------------------
# Theme
# ---------------------------------------------------------------------------
THEME_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:wght@500;700&family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500&display=swap');

:root {
  --ink: #15181E; --muted: #5E6470; --line: #E2DDD3; --ground: #F2EFE9;
  --orange: #E8590C; --red: #D92D20; --red-text: #B42318; --red-tint: #FEE4E2;
  --amber: #F59E0B; --amber-text: #92400E; --amber-tint: #FEF0C7;
  --teal: #0F766E; --teal-tint: #D5F0EC; --slate: #94A3B8; --slate-text: #475569;
}

.stApp { background: var(--ground); color: var(--ink); font-family: 'IBM Plex Sans', sans-serif; }
header[data-testid='stHeader'], #MainMenu, footer { display: none !important; }
.block-container { max-width: 1440px; padding: 24px 32px 48px; }

.d { font-family: 'Bricolage Grotesque', sans-serif; }
.lbl { font: 500 12px/1.2 'IBM Plex Mono', monospace; letter-spacing: .06em; text-transform: uppercase; color: var(--muted); }

/* Header */
.hdr { display: flex; flex-wrap: wrap; gap: 16px; align-items: center; justify-content: space-between; margin-bottom: 20px; }
.hdr-left { display: flex; align-items: center; gap: 14px; }
.logo { width: 44px; height: 44px; border-radius: 12px; background: var(--orange); display: flex; align-items: center; justify-content: center; }
.title { font-family: 'Bricolage Grotesque', sans-serif; font-size: 24px; font-weight: 700; line-height: 1.1; }
.sub { font-size: 13px; color: var(--muted); margin-top: 2px; }
.pills { display: flex; flex-wrap: wrap; gap: 10px; }
.pill { font: 400 12px 'IBM Plex Mono', monospace; padding: 8px 14px; border-radius: 999px; background: #fff; border: 1px solid var(--line); display: flex; align-items: center; gap: 8px; }
.dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }

/* KPI cards */
.kpi { background: #fff; border: 1px solid var(--line); border-radius: 14px; padding: 20px; height: 100%; box-sizing: border-box; }
.kpi-num { font-family: 'Bricolage Grotesque', sans-serif; font-size: 40px; font-weight: 700; line-height: 1; margin-top: 10px; }
.kpi-num small { font-size: 16px; font-weight: 500; }
.kpi-sub { font-size: 13px; color: var(--muted); margin-top: 8px; }

/* White cards: every st.container(key='card_...') */
div[class*='st-key-card_'] { background: #fff; border: 1px solid var(--line); border-radius: 14px; padding: 20px; }
.card-head { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 12px; margin-bottom: 4px; }
.card-t { font-family: 'Bricolage Grotesque', sans-serif; font-size: 19px; font-weight: 700; }
.card-s { font-size: 13px; color: var(--muted); margin-top: 2px; }
.legend { display: flex; flex-wrap: wrap; gap: 16px; font-size: 12px; color: var(--muted); align-items: center; }
.sw { width: 12px; height: 12px; border-radius: 3px; display: inline-block; margin-right: 6px; vertical-align: -1px; }
.tickkey { width: 2px; height: 14px; background: var(--ink); display: inline-block; margin-right: 6px; vertical-align: -3px; }

/* Runway */
.rw { display: flex; align-items: center; gap: 12px; margin-bottom: 14px; }
.rw-name { flex: 0 0 200px; font-size: 14px; }
.rw-track { position: relative; flex: 1; height: 14px; background: var(--ground); border-radius: 7px; }
.rw-bar { height: 100%; border-radius: 7px; }
.rw-tick { position: absolute; top: -4px; width: 2px; height: 22px; background: var(--ink); }
.rw-val { flex: 0 0 84px; text-align: right; font: 400 13px 'IBM Plex Mono', monospace; }

/* Health */
.hbar { display: flex; height: 28px; border-radius: 8px; overflow: hidden; gap: 2px; }
.hstats { display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 12px; margin-top: 16px; }
.hnum { font-family: 'Bricolage Grotesque', sans-serif; font-size: 26px; font-weight: 700; line-height: 1.2; }

/* Manifest */
.th { font: 500 12px 'IBM Plex Mono', monospace; letter-spacing: .06em; text-transform: uppercase; color: var(--muted); }
.cell { font-size: 14px; }
.cell-m { font: 400 13px 'IBM Plex Mono', monospace; }
.tag { font-size: 12px; padding: 4px 10px; border-radius: 999px; display: inline-block; white-space: nowrap; }
div[class*='st-key-card_manifest'] [data-testid='stMarkdownContainer'] p { margin: 0; }
div[class*='st-key-card_manifest'] [data-testid='stHorizontalBlock'] { border-bottom: 1px solid #EFEBE3; padding: 4px 0; }
div[class*='st-key-card_manifest'] .stButton > button {
  min-height: 44px; border: 1px solid var(--ink); background: #fff; color: var(--ink);
  border-radius: 8px; font-weight: 500;
}
div[class*='st-key-card_manifest'] .stButton > button:hover { background: var(--ground); border-color: var(--ink); color: var(--ink); }
[data-testid='stExpander'] { border: 1px solid var(--line); border-radius: 8px; background: #fff; }

/* Dark copilot panel: st.container(key='copilot') */
.st-key-copilot { background: #15181E; border-radius: 16px; padding: 20px; color: #F5F2EC; }
.st-key-copilot [data-testid='stMarkdownContainer'], .st-key-copilot [data-testid='stMarkdownContainer'] p { color: #F5F2EC; margin: 0; }
.st-key-copilot [data-testid='stToolbar'] { display: none; }
.st-key-chatlog { background: transparent; border: 0; }
.cp-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-bottom: 4px; }
.ring { width: 30px; height: 30px; border-radius: 50%; border: 4px solid #FB923C; box-sizing: border-box; }
.cp-title { font-family: 'Bricolage Grotesque', sans-serif; font-size: 18px; font-weight: 700; }
.cp-sub { font-size: 12px; color: #A8ADB8; }
.cp-badge { font: 400 11px 'IBM Plex Mono', monospace; padding: 5px 10px; border-radius: 999px; background: #2A2F3A; color: #FDBA74; }
.b-user { margin-left: auto; width: fit-content; max-width: 88%; background: #2A2F3A; border-radius: 14px; padding: 10px 14px; font-size: 14px; line-height: 1.5; margin-bottom: 10px; }
.b-bot { max-width: 92%; border: 1px solid #3A4150; border-radius: 14px; padding: 10px 14px; font-size: 14px; line-height: 1.5; margin-bottom: 10px; }
.chips { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 6px; }
.chip { font: 400 12px 'IBM Plex Mono', monospace; padding: 4px 10px; border-radius: 8px; background: #2A2F3A; color: #FDBA74; }
.pend { background: #1F242E; border: 1px solid #3A4150; border-radius: 12px; padding: 14px; }
.pend-h { font-size: 15px; font-weight: 500; }
.pend-s { font: 400 12px 'IBM Plex Mono', monospace; color: #A8ADB8; margin-top: 4px; }
.act-lbl { font: 500 12px 'IBM Plex Mono', monospace; letter-spacing: .06em; text-transform: uppercase; color: #A8ADB8; border-top: 1px solid #2F3541; padding-top: 12px; margin-top: 4px; }
.act { font: 400 12px/1.9 'IBM Plex Mono', monospace; color: #34D399; font-weight: bold;}

.st-key-copilot .stButton > button {
  min-height: 44px; background: #1F242E; color: #F5F2EC; border: 1px solid #3A4150;
  border-radius: 10px; font-weight: 500; width: 100%; text-align: left;
}
.st-key-copilot .stButton > button:hover { border-color: #FB923C; color: #FDBA74; }
.st-key-copilot .stButton > button[kind='primary'],
.st-key-copilot .stButton > button[data-testid='stBaseButton-primary'] {
  background: #E8590C; color: #15181E; border-color: #E8590C; text-align: center;
}
.st-key-copilot [data-testid='stChatInput'] { background: #1F242E; border: 1px solid #3A4150; border-radius: 10px; }
.st-key-copilot [data-testid='stChatInput'] textarea { color: #F5F2EC; }
.st-key-copilot [data-testid='stChatInput'] textarea::placeholder { color: #A8ADB8; }
.st-key-copilot [data-testid='stChatInput'] > div { background: #1F242E; }
</style>
"""
st.markdown(THEME_CSS, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------
def fetch_api(endpoint, timeout=8):
    """GET returning parsed JSON, or None when the API is unreachable or errors."""
    try:
        res = requests.get(API_BASE_URL + '/' + endpoint, timeout=timeout)
        if res.status_code == 200:
            return res.json()
    except (requests.RequestException, ValueError):
        pass
    return None


def post_api(endpoint, data=None, timeout=15):
    """POST returning a structured dictionary for JSON and empty-body responses."""
    try:
        res = requests.post(API_BASE_URL + '/' + endpoint, json=data or {}, timeout=timeout)
        try:
            body = res.json()
        except ValueError:
            body = {}
        if res.ok:
            if isinstance(body, dict):
                return body or {'status': 'success', 'message': 'Request completed.'}
            return {'status': 'success', 'message': 'Request completed.', 'data': body}
        detail = body.get('detail') or body.get('message') if isinstance(body, dict) else None
        return {
            'ok': False,
            'status': 'error',
            'http_status': res.status_code,
            'error': detail or ('Request failed (HTTP ' + str(res.status_code) + ').'),
        }
    except requests.RequestException:
        return {'ok': False, 'status': 'error', 'error': 'Could not reach the server.'}


def is_success_response(response):
    return (
        isinstance(response, dict)
        and response.get('status') != 'error'
        and (response.get('status') == 'success' or 'message' in response)
    )


with st.sidebar:
    if st.button('🔄 Reset Demo Data', key='reset_demo_data'):
        with st.spinner('Restoring demo data...'):
            reset_result = post_api('demo/reset', timeout=120)
        if reset_result.get('ok') or is_success_response(reset_result):
            st.session_state.clear()
            st.rerun()
        else:
            st.error('Could not reset demo data: ' + str(reset_result.get('error')))


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------
def esc(value):
    return html.escape('' if value is None else str(value))


def to_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def money_compact(value):
    v = to_float(value)
    if v >= 1_000_000:
        return '$' + format(v / 1_000_000, '.2f') + 'M'
    if v >= 1_000:
        return '$' + format(v / 1_000, '.0f') + 'K'
    return '$' + format(v, ',.0f')


def kpi_html(label, value_html, sub, red=False):
    color = " style='color:#B42318'" if red else ''
    return ("<div class='kpi'><div class='lbl'>" + label + "</div><div class='kpi-num'" + color + '>'
            + value_html + "</div><div class='kpi-sub'>" + sub + '</div></div>')


def card_head(title, subtitle, legend_html=''):
    return ("<div class='card-head'><div><div class='card-t'>" + title + "</div><div class='card-s'>"
            + subtitle + '</div></div>' + legend_html + '</div>')


def runway_html(items):
    covers = [to_float(i.get('days_of_cover')) for i in items]
    leads = [to_float(i.get('lead_time_days')) for i in items]
    scale = math.ceil(max([8.0] + covers + leads))
    rows = []
    for item, cover, lead in zip(items, covers, leads):
        color = '#D92D20' if cover < lead else '#F59E0B'
        width = min(cover / scale * 100, 100)
        tick = min(lead / scale * 100, 100)
        rows.append(
            "<div class='rw'><div class='rw-name'>" + esc(item.get('name')) + "</div>"
            "<div class='rw-track'><div class='rw-bar' style='width:" + format(width, '.1f') + '%;background:' + color + "'></div>"
            "<div class='rw-tick' style='left:" + format(tick, '.1f') + "%'></div></div>"
            "<div class='rw-val'>" + format(cover, 'g') + 'd / ' + format(lead, 'g') + 'd</div></div>'
        )
    return ''.join(rows)


RUNWAY_LEGEND = (
    "<div class='legend'>"
    "<span><span class='sw' style='background:#D92D20'></span>Runs out before delivery</span>"
    "<span><span class='sw' style='background:#F59E0B'></span>Tight</span>"
    "<span><span class='tickkey'></span>Lead time</span></div>"
)


def health_html(health):
    spec = [
        ('critical', '#D92D20', '#B42318', 'Critical'),
        ('warning', '#F59E0B', '#92400E', 'Warning'),
        ('healthy', '#0F766E', '#0F766E', 'Healthy'),
        ('overstocked', '#94A3B8', '#475569', 'Overstocked'),
    ]
    counts = [int(to_float(health.get(key))) for key, _, _, _ in spec]
    total = sum(counts) or 1
    bar = ''.join(
        "<div style='width:" + format(c / total * 100, '.2f') + '%;background:' + fill + "'></div>"
        for c, (_, fill, _, _) in zip(counts, spec)
    )
    stats = ''.join(
        "<div><div class='hnum' style='color:" + text + "'>" + str(c) + "</div><div class='lbl'>" + label + '</div></div>'
        for c, (_, _, text, label) in zip(counts, spec)
    )
    return "<div class='hbar'>" + bar + "</div><div class='hstats'>" + stats + '</div>', total


def status_tag(status):
    styles = {
        'pending_review': ('#FEE4E2', '#B42318', 'Pending review'),
        'approved': ('#D5F0EC', '#0F766E', 'Approved'),
        'rejected': ('#E2E8F0', '#475569', 'Rejected'),
    }
    bg, fg, label = styles.get(status, ('#E2E8F0', '#475569', str(status).replace('_', ' ').title()))
    return "<span class='tag' style='background:" + bg + ';color:' + fg + "'>" + label + '</span>'


def chips_html(tools):
    chips = ''.join(
        "<span class='chip'>" + esc(t.get('tool') or t.get('name') or 'tool') + '() '
        + esc(t.get('status') or 'completed') + '</span>'
        for t in tools
        if isinstance(t, dict)
    )
    return "<div class='chips'>" + chips + '</div>' if chips else ''



# Replace bubble_html in frontend/app.py with this function

def bubble_html(msg: dict) -> str:
    role = msg.get("role", "assistant")
    content = msg.get("content", "")
    html_content = markdown.markdown(html.escape(str(content)), extensions=['tables'])
    tools_html = chips_html(msg.get("tools") or [])
    if role == "user":
        return f"<div class='b-user'><b>You:</b> {html_content}</div>"
    mode_labels = {
        'fallback': 'Local fallback',
        'gemini': 'Gemini',
        'gemini+template': 'Gemini + verified template',
        'router': 'Quick reply',
        'guardrail': 'Guardrail',
        'error': 'Error',
    }
    mode = msg.get('mode')
    mode_label = mode_labels.get(mode, mode)
    if mode_label and msg.get('model'):
        mode_label += ' (' + str(msg['model']) + ')'
    mode_html = (
        "<div class='chips'><span class='chip'>" + esc(mode_label) + '</span></div>'
        if mode_label else ''
    )
    return f"<div class='b-bot'>{mode_html}{tools_html}<b>Copilot:</b><br/>{html_content}</div>"


def queue_prompt(text):
    st.session_state['queued'] = text


def approve_one(po_number):
    res = post_api('orders/' + po_number + '/approve')
    if is_success_response(res):
        st.toast('Approved ' + po_number, icon='✅')
        return True
    st.error('Could not approve ' + po_number + ': '
             + str(res.get('error', res.get('message', 'Unknown error.'))))
    return False


# ---------------------------------------------------------------------------
# Load data
# ---------------------------------------------------------------------------
st.session_state.setdefault('messages', [])
st.session_state.setdefault('session_id', uuid.uuid4().hex)

stats_response = fetch_api('dashboard/stats')
stats = stats_response if isinstance(stats_response, dict) else None
mcp = fetch_api('mcp-status')  # optional endpoint; the badge degrades gracefully without it

if mcp is not None and isinstance(mcp, dict):
    if mcp.get('connected'):
        mcp_pill = ('#0F766E', 'MCP server connected, ' + str(len(mcp.get('tools') or [])) + ' tools')
    else:
        mcp_pill = ('#D92D20', 'MCP server unreachable')
else:
    mcp_pill = ('#94A3B8', 'MCP server, 5 tools')

if stats is not None:
    data_pill = ('#0F766E', 'Data refreshed ' + datetime.now().strftime('%H:%M:%S'))
else:
    data_pill = ('#D92D20', 'API unreachable')

st.markdown(
    "<div class='hdr'><div class='hdr-left'><div class='logo'>"
    "<svg width='24' height='24' viewBox='0 0 24 24' fill='none' stroke='#15181E' stroke-width='2' "
    "stroke-linejoin='round' aria-hidden='true'><path d='M3 8l9-5 9 5-9 5-9-5z'/><path d='M3 8v8l9 5 9-5V8'/>"
    "<path d='M12 13v8'/></svg></div><div><div class='title'>Stockroom Copilot</div>"
    "<div class='sub'>Carltren Supply, hardware and building supplies</div></div></div>"
    "<div class='pills'>"
    "<div class='pill'><span class='dot' style='background:" + mcp_pill[0] + "'></span>" + esc(mcp_pill[1]) + '</div>'
    "<div class='pill'><span class='dot' style='background:" + data_pill[0] + "'></span>" + esc(data_pill[1]) + '</div>'
    '</div></div>',
    unsafe_allow_html=True,
)

if stats is None:
    st.error(
        'Cannot reach the API at ' + API_BASE_URL + '. If the server is on a free plan it may be waking up, '
        'which can take about a minute. Reload this page to try again.'
    )
    st.stop()

runway_response = fetch_api('dashboard/runway')
runway = [row for row in runway_response if isinstance(row, dict)] if isinstance(runway_response, list) else []
health_response = fetch_api('dashboard/health')
health = health_response if isinstance(health_response, dict) else {}
manifest_data = fetch_api('dashboard/manifest')
manifest_response = manifest_data if isinstance(manifest_data, list) else None
manifest = (
    [row for row in manifest_response if isinstance(row, dict)]
    if manifest_response is not None
    else []
)
activities_response = fetch_api('dashboard/activity')
activities = (
    [row for row in activities_response if isinstance(row, dict)]
    if isinstance(activities_response, list)
    else []
)

risk = stats.get('stockout_risk') or {}
pos = stats.get('open_purchase_orders') or {}
health_block, total_skus = health_html(health)

# ---------------------------------------------------------------------------
# KPI strip
# ---------------------------------------------------------------------------
k1, k2, k3, k4 = st.columns(4, gap='medium')
with k1:
    st.markdown(kpi_html(
        'Stockout risk', str(risk.get('critical_count', 0)) + ' <small>SKUs</small>',
        str(risk.get('critical_pct', 0)) + '% of catalog, cover below lead time', red=True), unsafe_allow_html=True)
with k2:
    st.markdown(kpi_html(
        'Inventory value', money_compact(stats.get('inventory_value')),
        str(total_skus) + ' SKUs in the catalog'), unsafe_allow_html=True)
with k3:
    st.markdown(kpi_html(
        'Open purchase orders', str(pos.get('count', 0)),
        '$' + format(to_float(pos.get('total_value')), ',.0f') + ' awaiting your approval'), unsafe_allow_html=True)
with k4:
    st.markdown(kpi_html(
        'Average days of cover', format(to_float(stats.get('avg_days_of_cover')), '.1f'),
        'Target range is 20 to 30 days'), unsafe_allow_html=True)

st.write('')

# ---------------------------------------------------------------------------
# Main row
# ---------------------------------------------------------------------------
# col_left, col_right = st.columns([1.7, 1.0], gap='large')
col_left, col_right = st.columns([1.3, 1.0], gap="medium")

with col_left:
    with st.container(key='card_runway'):
        st.markdown(card_head('Stockout runway', 'Days of cover against supplier lead time', RUNWAY_LEGEND)
                    + "<div style='height:14px'></div>", unsafe_allow_html=True)
        if runway:
            st.markdown(runway_html(runway), unsafe_allow_html=True)
        else:
            st.markdown("<div class='card-s'>No at-risk items right now.</div>", unsafe_allow_html=True)

    with st.container(key='card_health'):
        st.markdown(card_head('Inventory health', str(total_skus) + ' SKUs in the catalog')
                    + "<div style='height:12px'></div>" + health_block, unsafe_allow_html=True)

    with st.container(key='card_manifest'):
        st.markdown(card_head('Replenishment manifest', 'Drafted by the copilot, approved by you')
                    + "<div style='height:10px'></div>", unsafe_allow_html=True)
        widths = [1.1, 2.4, 1.8, 0.8, 0.8, 0.8, 1.5, 1.2]
        if manifest_response is None:
            st.error('Could not load purchase orders. Please refresh the dashboard.')
        elif not manifest:
            st.info(
                "🎉 **All pending purchase orders have been approved!**\n\n"
                "To draft additional orders for remaining at-risk items, ask Copilot in the chat panel: "
                "*'Draft orders for remaining critical SKUs'*."
            )
        else:
            head = st.columns(widths, vertical_alignment='center')
            for col, label in zip(head, ['SKU', 'Product', 'Supplier', 'On hand', 'Cover', 'PO qty', 'Status', '']):
                col.markdown("<div class='th'>" + label + '</div>', unsafe_allow_html=True)

            for row in manifest[:8]:
                po = str(row.get('po_number'))
                status = row.get('status') or 'pending_review'
                cover = row.get('days_of_cover')
                lead = row.get('lead_time_days')
                at_risk = lead is None or to_float(cover) < to_float(lead)
                cover_style = " style='color:#B42318'" if at_risk else ''
                cols = st.columns(widths, vertical_alignment='center')
                cols[0].markdown("<div class='cell-m'>" + esc(row.get('sku')) + '</div>', unsafe_allow_html=True)
                cols[1].markdown("<div class='cell'>" + esc(row.get('product') or row.get('name')) + '</div>',
                                 unsafe_allow_html=True)
                cols[2].markdown("<div class='cell'>" + esc(row.get('supplier')) + '</div>', unsafe_allow_html=True)
                cols[3].markdown("<div class='cell-m'>" + esc(row.get('on_hand') or 0) + '</div>', unsafe_allow_html=True)
                cols[4].markdown("<div class='cell-m'" + cover_style + '>' + format(to_float(cover), 'g') + 'd</div>',
                                 unsafe_allow_html=True)
                cols[5].markdown("<div class='cell-m'>" + esc(row.get('po_qty')) + '</div>', unsafe_allow_html=True)
                cols[6].markdown(status_tag(status), unsafe_allow_html=True)
                with cols[7]:
                    if status == 'pending_review':
                        if st.button('Approve', key='approve_' + po):
                            if approve_one(po):
                                st.rerun()

                with st.expander('Details for ' + po):
                    st.write('Order total: $' + format(to_float(row.get('total_cost')), ',.2f')
                             + '  |  Reorder quantity: ' + str(row.get('po_qty')) + ' units')
                    pdf_key = 'pdf_' + po
                    if pdf_key in st.session_state:
                        st.download_button('Download PDF', data=st.session_state[pdf_key],
                                           file_name=po + '.pdf', mime='application/pdf', key='dl_' + po)
                    elif st.button('Prepare PDF', key='prep_' + po):
                        try:
                            pdf_res = requests.get(API_BASE_URL + '/orders/' + po + '/pdf', timeout=15)
                            if pdf_res.status_code == 200:
                                st.session_state[pdf_key] = pdf_res.content
                                st.rerun()
                            else:
                                st.caption('PDF is not available for this order.')
                        except requests.RequestException:
                            st.caption('PDF preview unavailable.')

with col_right:
    with st.container(key='copilot'):
        st.markdown(
            "<div class='cp-head'><div style='display:flex;align-items:center;gap:12px'><div class='ring'></div>"
            "<div><div class='cp-title'>Copilot</div><div class='cp-sub'>Alexa+ simulation</div></div></div>"
            "<div class='cp-badge'>Gemini + MCP</div></div>",
            unsafe_allow_html=True,
        )

        messages = st.session_state['messages']

        with st.container(height=520, border=False, key='chatlog'):
                    if not messages:
                        st.markdown("<div class='b-bot'>" + esc(GREETING) + '</div>', unsafe_allow_html=True)
                    for msg in messages:
                        st.markdown(bubble_html(msg), unsafe_allow_html=True)

        if not messages:
            for i, text in enumerate(SUGGESTIONS):
                st.button(text, key='suggest_' + str(i), on_click=queue_prompt, args=(text,))

        pending_rows = [r for r in manifest if (r.get('status') or 'pending_review') == 'pending_review']
        if int(to_float(pos.get('count'))) > 0 and pending_rows:
            numbers = sorted(str(r.get('po_number')) for r in pending_rows)
            span = numbers[0] if len(numbers) == 1 else numbers[0] + ' to ' + numbers[-1]
            st.markdown(
                "<div class='pend'><div class='pend-h'>" + str(pos.get('count')) + " purchase orders waiting</div>"
                "<div class='pend-s'>" + esc(span) + ', $' + format(to_float(pos.get('total_value')), ',.0f')
                + '</div></div>',
                unsafe_allow_html=True,
            )
            if st.button('Approve all', key='approve_all', type='primary'):
                done = 0
                failures = []
                for r in pending_rows:
                    po_number = str(r.get('po_number'))
                    res = post_api('orders/' + po_number + '/approve')
                    if is_success_response(res):
                        done += 1
                    else:
                        failures.append(po_number)
                if done:
                    st.toast('Approved ' + str(done) + ' purchase orders', icon='✅')
                if failures:
                    st.error('Could not approve: ' + ', '.join(failures))
                if done:
                    st.rerun()

        typed = st.chat_input('Ask about stock, orders, or lead times')
        query = typed or st.session_state.pop('queued', None)
        if query:
            messages.append({'role': 'user', 'content': query})
            history = [{'role': m['role'], 'content': m['content']} for m in messages[:-1]]
            with st.spinner('Checking the stockroom...'):
                resp = post_api('chat', {'message': query, 'history': history,
                                         'session_id': st.session_state['session_id']}, timeout=90)
            if 'reply' in resp:
                messages.append({'role': 'assistant', 'content': resp.get('reply') or 'Done.',
                                 'tools': resp.get('tool_calls') or [], 'mode': resp.get('mode'),
                                 'model': resp.get('model'),
                                 'fallback_reason': resp.get('fallback_reason')})
            else:
                messages.append({'role': 'assistant', 'tools': [],
                                 'content': str(resp.get('error') or 'The copilot could not answer. Try again.')})
            st.rerun()

        st.markdown("<div class='act-lbl'>Activity</div>", unsafe_allow_html=True)
        if activities:
            lines = ''.join(
                '<div>' + esc(a.get('time')) + '  ' + esc(a.get('summary')) + '</div>' for a in activities[:5]
            )
            st.markdown("<div class='act'>" + lines + '</div>', unsafe_allow_html=True)
        else:
            st.markdown("<div class='act'>No activity yet.</div>", unsafe_allow_html=True)