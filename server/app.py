#!/usr/bin/env python3
"""Wrist AI hub: admin settings + AutoDL chat proxy under /wristai."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import time
from pathlib import Path
from typing import Any, AsyncIterator, Callable

import httpx
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from starlette.middleware.base import BaseHTTPMiddleware


def markdown_to_plain(text: str) -> str:
    """Strip common Markdown for watch / plain clients."""
    if not text:
        return ""
    s = text.replace("\r\n", "\n")
    s = re.sub(r"```[^\n]*\n([\s\S]*?)```", r"\1", s)
    s = re.sub(r"`([^`]+)`", r"\1", s)
    s = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", s)
    s = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", s)
    s = re.sub(r"^#{1,6}\s*", "", s, flags=re.M)
    s = re.sub(r"^\s{0,3}([-*+]|\d+\.)\s+", "", s, flags=re.M)
    s = re.sub(r"^\s{0,3}>\s?", "", s, flags=re.M)
    s = re.sub(r"(\*\*|__)(.+?)\1", r"\2", s)
    s = re.sub(r"(\*|_)([^*_\n]+?)\1", r"\2", s)
    s = re.sub(r"~~(.+?)~~", r"\1", s)
    s = re.sub(r"^\s*([-*_]\s*){3,}\s*$", "", s, flags=re.M)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
CONFIG_PATH = DATA / "config.json"

SITE_PASSWORD = os.environ.get("WRISTAI_PASSWORD", "")
if not SITE_PASSWORD:
    # Dev fallback only; production must set WRISTAI_PASSWORD
    SITE_PASSWORD = "change-me"
COOKIE_NAME = "wristai_session"
COOKIE_MAX_AGE = 60 * 60 * 24 * 30

DEFAULT_CONFIG: dict[str, Any] = {
    "autodl_api_key": "",
    "autodl_base_url": "https://www.autodl.art/api/v1",
    "model": "DeepSeek-V4-Flash",
    "system_prompt": (
        "你是腕上 AI 助手，回答简洁，优先适合手表小屏阅读。"
        "可聊天，也可讲解高中题目；解题先给结论，再给简短步骤。"
    ),
    "max_tokens": 1600,
    "temperature": 0.7,
    "device_key": "",
    "updated_at": 0,
}

def _pick_text(*candidates: Any) -> str:
    for c in candidates:
        if isinstance(c, str) and c:
            return c
        if isinstance(c, list):
            parts: list[str] = []
            for item in c:
                if isinstance(item, str) and item:
                    parts.append(item)
                elif isinstance(item, dict):
                    t = item.get("text") or item.get("content") or ""
                    if isinstance(t, str) and t:
                        parts.append(t)
            if parts:
                return "".join(parts)
    return ""


def _delta_text(delta: dict[str, Any] | None) -> str:
    if not isinstance(delta, dict):
        return ""
    # Prefer visible answer over reasoning when both exist.
    primary = _pick_text(delta.get("content"), delta.get("text"), delta.get("output_text"))
    if primary:
        return primary
    return _pick_text(
        delta.get("reasoning_content"),
        delta.get("reasoning"),
        delta.get("thinking"),
    )


def _message_text(message: dict[str, Any] | None) -> str:
    if not isinstance(message, dict):
        return ""
    primary = _pick_text(message.get("content"), message.get("text"), message.get("output_text"))
    if primary:
        return primary
    return _pick_text(
        message.get("reasoning_content"),
        message.get("reasoning"),
        message.get("thinking"),
    )


def _choice_finish_reason(choice: dict[str, Any] | None) -> str:
    if not isinstance(choice, dict):
        return ""
    return str(choice.get("finish_reason") or choice.get("finishReason") or "").strip()

DATA.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Wrist AI Hub", docs_url=None, openapi_url=None, redoc_url=None)


def _session_token() -> str:
    return hashlib.sha256(f"wristai|{SITE_PASSWORD}".encode("utf-8")).hexdigest()


def _load_config() -> dict[str, Any]:
    cfg = dict(DEFAULT_CONFIG)
    if CONFIG_PATH.exists():
        try:
            raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                cfg.update(raw)
        except Exception:
            pass
    if not cfg.get("device_key"):
        cfg["device_key"] = secrets.token_urlsafe(24)
        _save_config(cfg)
    return cfg


def _save_config(cfg: dict[str, Any]) -> None:
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def _mask_key(key: str) -> str:
    key = key or ""
    if not key:
        return ""
    if len(key) <= 10:
        return "****"
    return f"{key[:4]}…{key[-4:]}"


def _is_admin(request: Request) -> bool:
    cookie = request.cookies.get(COOKIE_NAME, "")
    return bool(cookie and hmac.compare_digest(cookie, _session_token()))


def _device_authorized(request: Request, cfg: dict[str, Any]) -> bool:
    if _is_admin(request):
        return True
    key = (
        request.headers.get("X-WristAI-Key")
        or request.headers.get("X-Device-Key")
        or request.query_params.get("key")
        or ""
    )
    device_key = cfg.get("device_key") or ""
    return bool(key and device_key and hmac.compare_digest(key, device_key))


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        path = request.url.path
        if not path.startswith("/wristai"):
            return await call_next(request)

        public = {
            "/wristai/login",
            "/wristai/api/login",
            "/wristai/api/health",
        }
        if path in public or path.rstrip("/") in public:
            return await call_next(request)

        # Device APIs: device_key or admin session
        if path.startswith("/wristai/api/chat") or path.startswith("/wristai/api/bootstrap"):
            cfg = _load_config()
            if _device_authorized(request, cfg):
                return await call_next(request)
            return JSONResponse({"ok": False, "error": "unauthorized"}, status_code=401)

        if _is_admin(request):
            return await call_next(request)

        if path.startswith("/wristai/api/"):
            return JSONResponse({"ok": False, "error": "unauthorized"}, status_code=401)
        return RedirectResponse(url="/wristai/login", status_code=302)


app.add_middleware(AuthMiddleware)


LOGIN_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>腕上 AI · 登录</title>
<style>
:root{--bg:#0f1419;--card:#1a222c;--text:#e8eef4;--muted:#8b9aab;--accent:#3d9cf0;--line:#2a3542}
*{box-sizing:border-box}body{margin:0;min-height:100vh;font-family:"Segoe UI",system-ui,sans-serif;background:radial-gradient(1200px 600px at 10% -10%,#1b3a55,transparent),var(--bg);color:var(--text);display:grid;place-items:center;padding:24px}
.card{width:min(420px,100%);background:var(--card);border:1px solid var(--line);border-radius:16px;padding:28px}
h1{margin:0 0 8px;font-size:1.35rem}p{margin:0 0 20px;color:var(--muted);font-size:.95rem}
label{display:block;margin:0 0 8px;color:var(--muted);font-size:.85rem}
input{width:100%;padding:12px 14px;border-radius:10px;border:1px solid var(--line);background:#121820;color:var(--text);font-size:1rem}
button{margin-top:16px;width:100%;padding:12px;border:0;border-radius:10px;background:var(--accent);color:#fff;font-weight:600;cursor:pointer}
.err{color:#ff8b8b;margin-top:12px;min-height:1.2em;font-size:.9rem}
</style>
</head>
<body>
<form class="card" id="f">
  <h1>腕上 AI</h1>
  <p>管理 AutoDL 令牌，并测试手表聊天代理。</p>
  <label>管理密码</label>
  <input id="pw" type="password" autocomplete="current-password" required/>
  <button type="submit">进入</button>
  <div class="err" id="err"></div>
</form>
<script>
f.onsubmit=async(e)=>{
  e.preventDefault();err.textContent='';
  const r=await fetch('/wristai/api/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({password:pw.value})});
  const j=await r.json().catch(()=>({}));
  if(!r.ok||!j.ok){err.textContent=j.error||'登录失败';return}
  location.href='/wristai/';
};
</script>
</body>
</html>"""


HOME_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>腕上 AI · 控制台</title>
<style>
:root{--bg:#0f1419;--card:#1a222c;--text:#e8eef4;--muted:#8b9aab;--accent:#3d9cf0;--ok:#3ecf8e;--line:#2a3542;--warn:#f0b429}
*{box-sizing:border-box}body{margin:0;font-family:"Segoe UI",system-ui,sans-serif;background:radial-gradient(1000px 500px at 80% -20%,#243b55,transparent),var(--bg);color:var(--text)}
header{display:flex;justify-content:space-between;align-items:center;padding:18px 22px;border-bottom:1px solid var(--line)}
header h1{margin:0;font-size:1.15rem}header .sub{color:var(--muted);font-size:.85rem}
main{display:grid;gap:16px;padding:18px;max-width:1100px;margin:0 auto;grid-template-columns:1.1fr .9fr}
@media(max-width:860px){main{grid-template-columns:1fr}}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:18px}
h2{margin:0 0 12px;font-size:1rem}
label{display:block;margin:12px 0 6px;color:var(--muted);font-size:.82rem}
input,select,textarea{width:100%;padding:10px 12px;border-radius:10px;border:1px solid var(--line);background:#121820;color:var(--text);font:inherit}
textarea{min-height:90px;resize:vertical}
.row{display:flex;gap:10px;flex-wrap:wrap;margin-top:14px}
button{padding:10px 14px;border:0;border-radius:10px;background:var(--accent);color:#fff;font-weight:600;cursor:pointer}
button.secondary{background:#2a3542}button.danger{background:#8b3a3a}
.msg{margin-top:10px;color:var(--muted);font-size:.88rem;min-height:1.2em}
.msg.ok{color:var(--ok)}.msg.err{color:#ff8b8b}
.chat{display:flex;flex-direction:column;height:min(70vh,620px)}
.log{flex:1;overflow:auto;border:1px solid var(--line);border-radius:10px;padding:12px;background:#121820;font-size:.92rem}
.bubble{margin:0 0 10px;padding:10px 12px;border-radius:10px;max-width:95%;word-break:break-word;line-height:1.55}
.bubble.user{background:#24384d;margin-left:auto;white-space:pre-wrap}
.bubble.assistant{background:#222a33}
.bubble.assistant :first-child{margin-top:0}.bubble.assistant :last-child{margin-bottom:0}
.bubble.assistant p{margin:.45em 0}
.bubble.assistant h1,.bubble.assistant h2,.bubble.assistant h3{margin:.7em 0 .35em;font-size:1.05em;line-height:1.3}
.bubble.assistant ul,.bubble.assistant ol{margin:.4em 0;padding-left:1.3em}
.bubble.assistant li{margin:.15em 0}
.bubble.assistant blockquote{margin:.5em 0;padding:.35em .7em;border-left:3px solid #3d9cf0;color:#b7c6d6;background:#1a222c}
.bubble.assistant pre{margin:.5em 0;padding:8px 10px;overflow:auto;border-radius:8px;background:#0d1218;border:1px solid var(--line)}
.bubble.assistant code{font-family:Consolas,"Courier New",monospace;font-size:.9em;color:#c9e3ff;background:#0d1218;padding:.1em .35em;border-radius:5px}
.bubble.assistant pre code{padding:0;background:transparent}
.bubble.assistant a{color:#7ec2ff}
.bubble.assistant table{border-collapse:collapse;margin:.5em 0;font-size:.9em;display:block;overflow:auto}
.bubble.assistant th,.bubble.assistant td{border:1px solid var(--line);padding:4px 8px}
.bubble.assistant hr{border:0;border-top:1px solid var(--line);margin:.7em 0}
.composer{display:flex;gap:8px;margin-top:10px}
.composer input{flex:1}
.kv{font-size:.85rem;color:var(--muted);line-height:1.6}
code{color:#c9e3ff;background:#121820;padding:1px 6px;border-radius:6px}
.pill{display:inline-block;padding:2px 8px;border-radius:999px;background:#24384d;color:#9fd0ff;font-size:.78rem}
</style>
</head>
<body>
<header>
  <div>
    <h1>腕上 AI 控制台</h1>
    <div class="sub">AutoDL 令牌只保存在服务器；手表走代理，不直接拿 API Key</div>
  </div>
  <div class="row" style="margin:0">
    <button class="secondary" id="logout">退出</button>
  </div>
</header>
<main>
  <section class="card">
    <h2>API 配置 <span class="pill" id="statusPill">未检测</span></h2>
    <label>AutoDL Base URL</label>
    <input id="baseUrl"/>
    <label>模型名（与 AutoDL 页面一致）</label>
    <input id="model" placeholder="DeepSeek-V4-Flash"/>
    <label>AutoDL API 令牌</label>
    <input id="apiKey" type="password" placeholder="留空表示不修改已保存的令牌" autocomplete="off"/>
    <div class="kv" id="keyHint"></div>
    <label>系统提示词</label>
    <textarea id="systemPrompt"></textarea>
    <div class="row">
      <div style="flex:1;min-width:120px">
        <label>max_tokens</label>
        <input id="maxTokens" type="number" min="64" max="8192"/>
      </div>
      <div style="flex:1;min-width:120px">
        <label>temperature</label>
        <input id="temperature" type="number" min="0" max="2" step="0.1"/>
      </div>
    </div>
    <label>手表设备密钥（App 请求头 X-WristAI-Key）</label>
    <input id="deviceKey" readonly/>
    <div class="row">
      <button id="save">保存配置</button>
      <button class="secondary" id="rotateKey">更换设备密钥</button>
      <button class="secondary" id="ping">测试连通</button>
    </div>
    <div class="msg" id="cfgMsg"></div>
    <div class="kv" style="margin-top:12px">
      手表聊天接口：<code>POST https://antony.fan/wristai/api/chat</code><br/>
      启动信息：<code>GET https://antony.fan/wristai/api/bootstrap</code>
    </div>
  </section>

  <section class="card chat">
    <h2>网页试聊（Markdown 渲染）</h2>
    <div class="log" id="log"></div>
    <div class="composer">
      <input id="q" placeholder="例如：二次函数顶点公式？"/>
      <button id="send">发送</button>
    </div>
    <div class="msg" id="chatMsg"></div>
  </section>
</main>
<script>
const $=id=>document.getElementById(id);
function setMsg(el,text,cls=''){el.textContent=text||'';el.className='msg'+(cls?' '+cls:'')}
function esc(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')}
function inlineMd(s){
  s=esc(s);
  s=s.replace(/`([^`]+)`/g,'<code>$1</code>');
  s=s.replace(/\\*\\*([^*]+)\\*\\*/g,'<strong>$1</strong>');
  s=s.replace(/__([^_]+)__/g,'<strong>$1</strong>');
  s=s.replace(/\\*([^*]+)\\*/g,'<em>$1</em>');
  s=s.replace(/_([^_]+)_/g,'<em>$1</em>');
  s=s.replace(/~~([^~]+)~~/g,'<del>$1</del>');
  s=s.replace(/\\[([^\\]]+)\\]\\((https?:[^)\\s]+)\\)/g,'<a href="$2" target="_blank" rel="noopener">$1</a>');
  return s;
}
function renderMd(src){
  if(!src) return '';
  const lines=String(src).replace(/\\r\\n/g,'\\n').split('\\n');
  const out=[]; let i=0; let inUl=false,inOl=false,inBq=false;
  const closeLists=()=>{if(inUl){out.push('</ul>');inUl=false} if(inOl){out.push('</ol>');inOl=false}};
  const closeBq=()=>{if(inBq){out.push('</blockquote>');inBq=false}};
  while(i<lines.length){
    const line=lines[i];
    const fence=line.match(/^```(.*)$/);
    if(fence){
      closeLists(); closeBq();
      const lang=esc(fence[1]||''); const code=[]; i++;
      while(i<lines.length && !lines[i].startsWith('```')){code.push(lines[i]); i++}
      if(i<lines.length) i++;
      out.push('<pre><code class="lang-'+lang+'">'+esc(code.join('\\n'))+'</code></pre>');
      continue;
    }
    if(/^\\s*([-_*]\\s*){3,}$/.test(line)){closeLists();closeBq();out.push('<hr/>');i++;continue}
    const h=line.match(/^(#{1,3})\\s+(.+)$/);
    if(h){closeLists();closeBq();out.push('<h'+h[1].length+'>'+inlineMd(h[2])+'</h'+h[1].length+'>');i++;continue}
    const bq=line.match(/^>\\s?(.*)$/);
    if(bq){closeLists(); if(!inBq){out.push('<blockquote>');inBq=true} out.push('<p>'+inlineMd(bq[1])+'</p>');i++;continue}
    else closeBq();
    const ul=line.match(/^\\s*[-*+]\\s+(.+)$/);
    if(ul){closeBq(); if(inOl){out.push('</ol>');inOl=false} if(!inUl){out.push('<ul>');inUl=true} out.push('<li>'+inlineMd(ul[1])+'</li>');i++;continue}
    const ol=line.match(/^\\s*\\d+\\.\\s+(.+)$/);
    if(ol){closeBq(); if(inUl){out.push('</ul>');inUl=false} if(!inOl){out.push('<ol>');inOl=true} out.push('<li>'+inlineMd(ol[1])+'</li>');i++;continue}
    if(!line.trim()){closeLists();closeBq();i++;continue}
    closeLists(); closeBq();
    out.push('<p>'+inlineMd(line)+'</p>'); i++;
  }
  closeLists(); closeBq();
  return out.join('');
}
function addBubble(role,text){
  const d=document.createElement('div');
  d.className='bubble '+role;
  if(role==='assistant') d.innerHTML=renderMd(text);
  else d.textContent=text;
  log.appendChild(d); log.scrollTop=log.scrollHeight;
  return d;
}
function setAssistant(bubble,text){
  bubble.innerHTML=renderMd(text||'');
  log.scrollTop=log.scrollHeight;
}
async function loadCfg(){
  const r=await fetch('/wristai/api/config');
  const j=await r.json();
  if(!r.ok){setMsg(cfgMsg,j.error||'读取失败','err');return}
  baseUrl.value=j.autodl_base_url||'';
  model.value=j.model||'';
  systemPrompt.value=j.system_prompt||'';
  maxTokens.value=j.max_tokens??1600;
  temperature.value=j.temperature??0.7;
  deviceKey.value=j.device_key||'';
  keyHint.textContent=j.api_key_set?('已保存令牌：'+j.api_key_masked):'尚未配置 AutoDL 令牌';
  statusPill.textContent=j.api_key_set?'已配置令牌':'未配置令牌';
}
save.onclick=async()=>{
  setMsg(cfgMsg,'保存中…');
  const body={
    autodl_base_url:baseUrl.value.trim(),
    model:model.value.trim(),
    system_prompt:systemPrompt.value,
    max_tokens:Number(maxTokens.value||1600),
    temperature:Number(temperature.value||0.7),
    autodl_api_key:apiKey.value.trim()
  };
  const r=await fetch('/wristai/api/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const j=await r.json().catch(()=>({}));
  if(!r.ok||!j.ok){setMsg(cfgMsg,j.error||'保存失败','err');return}
  apiKey.value='';
  setMsg(cfgMsg,'已保存','ok');
  loadCfg();
};
rotateKey.onclick=async()=>{
  if(!confirm('更换后，旧手表密钥会失效，确定？'))return;
  const r=await fetch('/wristai/api/config/rotate-device-key',{method:'POST'});
  const j=await r.json().catch(()=>({}));
  if(!r.ok||!j.ok){setMsg(cfgMsg,j.error||'失败','err');return}
  deviceKey.value=j.device_key||'';
  setMsg(cfgMsg,'设备密钥已更换','ok');
};
ping.onclick=async()=>{
  setMsg(cfgMsg,'测试中…');
  const r=await fetch('/wristai/api/ping',{method:'POST'});
  const j=await r.json().catch(()=>({}));
  if(!r.ok||!j.ok){setMsg(cfgMsg,j.error||'连通失败','err');return}
  setMsg(cfgMsg,'连通成功：'+ (j.preview||''),'ok');
};
function pickDeltaText(obj){
  const ch=(obj&&obj.choices&&obj.choices[0])||{};
  const d=ch.delta||{};
  const m=ch.message||{};
  const primary=d.content||d.text||d.output_text||m.content||m.text||'';
  if(primary) return String(primary);
  const fallback=d.reasoning_content||d.reasoning||d.thinking||m.reasoning_content||m.reasoning||obj.content||'';
  return fallback?String(fallback):'';
}
function consumeSseBuffer(buf,onObj){
  const parts=buf.split('\\n');
  const rest=parts.pop()||'';
  for(const line of parts){
    const s=line.trim(); if(!s||!s.startsWith('data:')) continue;
    const payload=s.slice(5).trim(); if(!payload||payload==='[DONE]') continue;
    try{ onObj(JSON.parse(payload)); }catch{}
  }
  return rest;
}
send.onclick=async()=>{
  const text=q.value.trim(); if(!text)return;
  q.value=''; addBubble('user',text);
  const bubble=addBubble('assistant','…');
  setMsg(chatMsg,'生成中…');
  try{
    const r=await fetch('/wristai/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({messages:[{role:'user',content:text}],stream:true})});
    if(!r.ok){
      const j=await r.json().catch(()=>({}));
      bubble.textContent=j.error||('HTTP '+r.status);
      setMsg(chatMsg,'失败','err');return;
    }
    const reader=r.body.getReader(); const dec=new TextDecoder();
    let acc='',buf='',finish='',truncated=false;
    setAssistant(bubble,'');
    const onObj=(obj)=>{
      if(obj.error){ throw new Error(typeof obj.error==='string'?obj.error:JSON.stringify(obj.error)); }
      const piece=pickDeltaText(obj);
      if(piece){acc+=piece;setAssistant(bubble,acc)}
      const fr=obj.choices?.[0]?.finish_reason||obj.choices?.[0]?.finishReason||'';
      if(fr) finish=String(fr);
      if(obj.truncated||fr==='length') truncated=true;
      if(obj.notice){ acc+=(acc?'\\n\\n':'')+String(obj.notice); setAssistant(bubble,acc); }
    };
    while(true){
      const {value,done}=await reader.read();
      if(done){
        buf+=dec.decode();
        buf=consumeSseBuffer(buf+(buf.endsWith('\\n')?'':'\\n'), onObj);
        break;
      }
      buf+=dec.decode(value,{stream:true});
      buf=consumeSseBuffer(buf, onObj);
    }
    if(!acc) bubble.textContent='(空回复)';
    else {
      if(truncated||finish==='length'){
        if(!/截断|token/i.test(acc)) acc+='\\n\\n〔回复可能因 max_tokens 被截断〕';
        setAssistant(bubble,acc);
        setMsg(chatMsg,'完成（可能被截断）','err');
      } else {
        setAssistant(bubble,acc);
        setMsg(chatMsg,'完成','ok');
      }
      return;
    }
    setMsg(chatMsg, truncated||finish==='length'?'完成（可能被截断）':'完成', truncated||finish==='length'?'err':'ok');
  }catch(e){bubble.textContent=String(e);setMsg(chatMsg,'失败','err')}
};
q.addEventListener('keydown',e=>{if(e.key==='Enter')send.click()});
logout.onclick=async()=>{await fetch('/wristai/api/logout',{method:'POST'});location.href='/wristai/login'};
loadCfg();
</script>
</body>
</html>"""


@app.get("/wristai/login", response_class=HTMLResponse)
def login_page() -> HTMLResponse:
    return HTMLResponse(LOGIN_HTML)


@app.post("/wristai/api/login")
async def api_login(request: Request) -> JSONResponse:
    try:
        body = await request.json()
    except Exception:
        body = {}
    password = str(body.get("password") or "")
    if not password or not hmac.compare_digest(password, SITE_PASSWORD):
        return JSONResponse({"ok": False, "error": "密码错误"}, status_code=401)
    resp = JSONResponse({"ok": True})
    resp.set_cookie(
        COOKIE_NAME,
        _session_token(),
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        path="/wristai",
    )
    return resp


@app.post("/wristai/api/logout")
async def api_logout() -> JSONResponse:
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(COOKIE_NAME, path="/wristai")
    return resp


@app.get("/wristai", response_class=HTMLResponse)
@app.get("/wristai/", response_class=HTMLResponse)
def home() -> HTMLResponse:
    return HTMLResponse(HOME_HTML)


@app.get("/wristai/api/health")
def health() -> dict[str, Any]:
    cfg = _load_config()
    return {
        "ok": True,
        "service": "wristai",
        "model": cfg.get("model"),
        "api_key_set": bool(cfg.get("autodl_api_key")),
    }


@app.get("/wristai/api/config")
def get_config() -> dict[str, Any]:
    cfg = _load_config()
    key = cfg.get("autodl_api_key") or ""
    return {
        "ok": True,
        "autodl_base_url": cfg.get("autodl_base_url") or DEFAULT_CONFIG["autodl_base_url"],
        "model": cfg.get("model") or DEFAULT_CONFIG["model"],
        "system_prompt": cfg.get("system_prompt") or "",
        "max_tokens": int(cfg.get("max_tokens") or DEFAULT_CONFIG["max_tokens"]),
        "temperature": float(cfg.get("temperature") or 0.7),
        "device_key": cfg.get("device_key") or "",
        "api_key_set": bool(key),
        "api_key_masked": _mask_key(key),
        "updated_at": cfg.get("updated_at") or 0,
    }


@app.post("/wristai/api/config")
async def set_config(request: Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="invalid json") from exc

    cfg = _load_config()
    if "autodl_base_url" in body and str(body.get("autodl_base_url") or "").strip():
        cfg["autodl_base_url"] = str(body["autodl_base_url"]).strip().rstrip("/")
    if "model" in body and str(body.get("model") or "").strip():
        cfg["model"] = str(body["model"]).strip()
    if "system_prompt" in body:
        cfg["system_prompt"] = str(body.get("system_prompt") or "")
    if "max_tokens" in body:
        cfg["max_tokens"] = max(64, min(8192, int(body.get("max_tokens") or DEFAULT_CONFIG["max_tokens"])))
    if "temperature" in body:
        cfg["temperature"] = max(0.0, min(2.0, float(body.get("temperature") or 0.7)))
    new_key = str(body.get("autodl_api_key") or "").strip()
    if new_key:
        cfg["autodl_api_key"] = new_key
    cfg["updated_at"] = int(time.time())
    _save_config(cfg)
    return {"ok": True}


@app.post("/wristai/api/config/rotate-device-key")
def rotate_device_key() -> dict[str, Any]:
    cfg = _load_config()
    cfg["device_key"] = secrets.token_urlsafe(24)
    cfg["updated_at"] = int(time.time())
    _save_config(cfg)
    return {"ok": True, "device_key": cfg["device_key"]}


@app.get("/wristai/api/bootstrap")
def bootstrap(request: Request) -> dict[str, Any]:
    """Watch startup info. Never returns AutoDL API key."""
    cfg = _load_config()
    return {
        "ok": True,
        "service": "wristai",
        "chat_url": "https://antony.fan/wristai/api/chat",
        "model": cfg.get("model"),
        "max_tokens": int(cfg.get("max_tokens") or DEFAULT_CONFIG["max_tokens"]),
        "api_key_set": bool(cfg.get("autodl_api_key")),
        "formats": ["markdown", "plain"],
        "hint": "Header X-WristAI-Key required. Watch: POST chat with {\"format\":\"plain\"}.",
    }


def _build_messages(cfg: dict[str, Any], body: dict[str, Any]) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    system_prompt = str(cfg.get("system_prompt") or "").strip()
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})

    raw_messages = body.get("messages")
    if isinstance(raw_messages, list) and raw_messages:
        for m in raw_messages:
            if not isinstance(m, dict):
                continue
            role = str(m.get("role") or "").strip()
            content = str(m.get("content") or "").strip()
            if role in {"user", "assistant", "system"} and content:
                messages.append({"role": role, "content": content})
    else:
        prompt = str(body.get("prompt") or body.get("message") or "").strip()
        if prompt:
            messages.append({"role": "user", "content": prompt})

    if not any(m["role"] == "user" for m in messages):
        raise HTTPException(status_code=400, detail="messages/prompt required")
    return messages


async def _autodl_payload(cfg: dict[str, Any], body: dict[str, Any], stream: bool) -> dict[str, Any]:
    key = (cfg.get("autodl_api_key") or "").strip()
    if not key:
        raise HTTPException(status_code=400, detail="AutoDL API key not configured")
    model = (cfg.get("model") or "").strip()
    if not model:
        raise HTTPException(status_code=400, detail="model not configured")
    max_tokens = int(body.get("max_tokens") or cfg.get("max_tokens") or DEFAULT_CONFIG["max_tokens"])
    temperature = float(body.get("temperature") if body.get("temperature") is not None else cfg.get("temperature") or 0.7)
    payload: dict[str, Any] = {
        "model": model,
        "messages": _build_messages(cfg, body),
        "max_tokens": max(64, min(8192, max_tokens)),
        "temperature": max(0.0, min(2.0, temperature)),
        "stream": stream,
        "_key": key,
        "_base": (cfg.get("autodl_base_url") or DEFAULT_CONFIG["autodl_base_url"]).rstrip("/"),
    }
    # DeepSeek-style thinking models often put tokens in reasoning_* with empty content.
    if "deepseek" in model.lower() or "think" in model.lower():
        payload["enable_thinking"] = False
        payload["thinking"] = {"type": "disabled"}
    return payload


def _strip_thinking_flags(payload: dict[str, Any]) -> dict[str, Any]:
    out = dict(payload)
    out.pop("enable_thinking", None)
    out.pop("thinking", None)
    return out


def _normalize_sse_line(line: str) -> tuple[str | None, str, str]:
    """Parse one SSE data line; return (normalized_line_or_None, text_piece, finish_reason)."""
    s = line.strip()
    if not s.startswith("data:"):
        return (line if line.endswith("\n") else line + "\n", "", "")
    payload = s[5:].strip()
    if not payload:
        return None, "", ""
    if payload == "[DONE]":
        return "data: [DONE]\n\n", "", "done"
    try:
        obj = json.loads(payload)
    except Exception:
        # Pass through non-JSON data lines unchanged.
        return f"data: {payload}\n\n", "", ""

    if obj.get("error"):
        return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n", "", "error"

    choices = obj.get("choices")
    if not isinstance(choices, list) or not choices:
        return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n", "", ""

    choice0 = choices[0] if isinstance(choices[0], dict) else {}
    delta = choice0.get("delta") if isinstance(choice0.get("delta"), dict) else {}
    message = choice0.get("message") if isinstance(choice0.get("message"), dict) else {}
    finish = _choice_finish_reason(choice0)

    text = _delta_text(delta)
    if not text:
        text = _message_text(message)

    # Rewrite so clients always read choices[0].delta.content
    out_choice: dict[str, Any] = {"index": choice0.get("index", 0), "delta": {"content": text or ""}}
    if finish:
        out_choice["finish_reason"] = finish
    out = {
        "id": obj.get("id"),
        "object": obj.get("object") or "chat.completion.chunk",
        "model": obj.get("model"),
        "choices": [out_choice],
    }
    if finish == "length":
        out["truncated"] = True
        out["notice"] = "〔回复可能因 max_tokens 被截断〕"
    return f"data: {json.dumps(out, ensure_ascii=False)}\n\n", text or "", finish


async def _iter_normalized_sse(upstream: httpx.Response) -> AsyncIterator[bytes]:
    buf = ""
    saw_text = False
    finish = ""
    async for chunk in upstream.aiter_text():
        if not chunk:
            continue
        buf += chunk
        while True:
            split_at = buf.find("\n")
            if split_at < 0:
                break
            line, buf = buf[: split_at + 1], buf[split_at + 1 :]
            if not line.strip():
                continue
            normalized, text, fr = _normalize_sse_line(line)
            if fr and fr not in {"done"}:
                finish = fr
            if text:
                saw_text = True
            if normalized:
                yield normalized.encode("utf-8")

    # Flush leftover buffer (final SSE event without trailing newline)
    if buf.strip():
        normalized, text, fr = _normalize_sse_line(buf if buf.endswith("\n") else buf + "\n")
        if fr and fr not in {"done"}:
            finish = fr
        if text:
            saw_text = True
        if normalized:
            yield normalized.encode("utf-8")

    if finish == "length":
        notice = {
            "truncated": True,
            "notice": "〔回复可能因 max_tokens 被截断〕",
            "choices": [{"index": 0, "delta": {"content": ""}, "finish_reason": "length"}],
        }
        yield f"data: {json.dumps(notice, ensure_ascii=False)}\n\n".encode("utf-8")
    elif not saw_text:
        empty = {
            "choices": [{"index": 0, "delta": {"content": ""}, "finish_reason": finish or "stop"}],
            "notice": "(空回复)",
        }
        yield f"data: {json.dumps(empty, ensure_ascii=False)}\n\n".encode("utf-8")

    yield b"data: [DONE]\n\n"


async def _post_autodl_json(
    client: httpx.AsyncClient,
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
) -> httpx.Response:
    r = await client.post(url, headers=headers, json=payload)
    # Some gateways reject unknown thinking flags; retry once without them.
    if r.status_code >= 400 and ("enable_thinking" in payload or "thinking" in payload):
        r2 = await client.post(url, headers=headers, json=_strip_thinking_flags(payload))
        if r2.status_code < 400 or r2.status_code != r.status_code:
            return r2
    return r


@app.post("/wristai/api/ping")
async def ping_autodl() -> dict[str, Any]:
    cfg = _load_config()
    payload = await _autodl_payload(
        cfg,
        {"messages": [{"role": "user", "content": "只回复两个字：可用"}]},
        stream=False,
    )
    key = payload.pop("_key")
    base = payload.pop("_base")
    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await _post_autodl_json(
            client,
            f"{base}/chat/completions",
            {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            payload,
        )
    if r.status_code >= 400:
        return JSONResponse(
            {"ok": False, "error": f"AutoDL HTTP {r.status_code}: {r.text[:300]}"},
            status_code=502,
        )
    data = r.json()
    choice0 = ((data.get("choices") or [{}])[0]) if isinstance(data, dict) else {}
    text = _message_text(choice0.get("message") if isinstance(choice0, dict) else None).strip()
    return {"ok": True, "preview": text[:80] or "(空回复)"}


@app.post("/wristai/api/chat")
async def chat(request: Request) -> Response:
    try:
        body = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="invalid json") from exc

    cfg = _load_config()
    stream = bool(body.get("stream", True))
    # markdown | plain  （手表建议 plain；网页控制台用 markdown 原文自行渲染）
    fmt = str(body.get("format") or request.headers.get("X-WristAI-Format") or "markdown").strip().lower()
    if fmt not in {"markdown", "plain", "md", "text"}:
        fmt = "markdown"
    want_plain = fmt in {"plain", "text"}

    # plain 流式：先收完整再转纯文本，避免半截 markdown 刷屏
    upstream_stream = stream and not want_plain
    payload = await _autodl_payload(cfg, body, stream=upstream_stream)
    key = payload.pop("_key")
    base = payload.pop("_base")
    url = f"{base}/chat/completions"
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}

    if not upstream_stream:
        async with httpx.AsyncClient(timeout=120.0) as client:
            r = await _post_autodl_json(client, url, headers, payload)
        if r.status_code >= 400:
            return JSONResponse(
                {"ok": False, "error": f"AutoDL HTTP {r.status_code}: {r.text[:400]}"},
                status_code=502,
            )
        data = r.json()
        choice0 = ((data.get("choices") or [{}])[0]) if isinstance(data, dict) else {}
        if not isinstance(choice0, dict):
            choice0 = {}
        text = _message_text(choice0.get("message") if isinstance(choice0.get("message"), dict) else None)
        if not text:
            # Some providers put text on the choice itself
            text = _pick_text(choice0.get("text"), choice0.get("content"))
        finish = _choice_finish_reason(choice0)
        plain = markdown_to_plain(text)
        if stream and want_plain:
            # 手表可按 SSE 收一条完整 plain
            async def plain_stream() -> AsyncIterator[bytes]:
                chunk = {
                    "choices": [{"delta": {"content": plain}, "index": 0, "finish_reason": finish or "stop"}],
                    "format": "plain",
                }
                if finish == "length":
                    chunk["truncated"] = True
                    chunk["notice"] = "〔回复可能因 max_tokens 被截断〕"
                yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n".encode()
                yield b"data: [DONE]\n\n"

            return StreamingResponse(plain_stream(), media_type="text/event-stream")

        result: dict[str, Any] = {
            "ok": True,
            "model": payload["model"],
            "format": "plain" if want_plain else "markdown",
            "content": plain if want_plain else text,
            "content_markdown": text,
            "content_plain": plain,
            "finish_reason": finish or "stop",
            "raw": data,
        }
        if finish == "length":
            result["truncated"] = True
            result["notice"] = "〔回复可能因 max_tokens 被截断〕"
        if not text:
            result["content"] = "(空回复)"
            result["content_markdown"] = "(空回复)"
            result["content_plain"] = "(空回复)"
        return result

    async def event_stream() -> AsyncIterator[bytes]:
        try:
            async with httpx.AsyncClient(timeout=None) as client:
                req_payload = payload
                async with client.stream("POST", url, headers=headers, json=req_payload) as r:
                    if r.status_code >= 400 and ("enable_thinking" in req_payload or "thinking" in req_payload):
                        err1 = (await r.aread()).decode("utf-8", errors="replace")[:200]
                        req_payload = _strip_thinking_flags(payload)
                        async with client.stream("POST", url, headers=headers, json=req_payload) as r2:
                            if r2.status_code >= 400:
                                err = (await r2.aread()).decode("utf-8", errors="replace")[:400]
                                yield f"data: {json.dumps({'error': f'AutoDL HTTP {r2.status_code}: {err} (also tried without thinking flags after: {err1})'}, ensure_ascii=False)}\n\n".encode()
                                yield b"data: [DONE]\n\n"
                                return
                            async for out in _iter_normalized_sse(r2):
                                yield out
                        return
                    if r.status_code >= 400:
                        err = (await r.aread()).decode("utf-8", errors="replace")[:400]
                        yield f"data: {json.dumps({'error': f'AutoDL HTTP {r.status_code}: {err}'}, ensure_ascii=False)}\n\n".encode()
                        yield b"data: [DONE]\n\n"
                        return
                    async for out in _iter_normalized_sse(r):
                        yield out
        except Exception as exc:
            yield f"data: {json.dumps({'error': str(exc)}, ensure_ascii=False)}\n\n".encode()
            yield b"data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# Compatibility form endpoints (optional)
@app.post("/wristai/api/login/form")
async def login_form(password: str = Form(...)) -> JSONResponse:
    if not hmac.compare_digest(password, SITE_PASSWORD):
        return JSONResponse({"ok": False, "error": "密码错误"}, status_code=401)
    resp = JSONResponse({"ok": True})
    resp.set_cookie(
        COOKIE_NAME,
        _session_token(),
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        path="/wristai",
    )
    return resp
