"""ECNU 小助手本地原型。运行: python -m app"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from datetime import datetime, timedelta
import json
import sqlite3

DB = Path.home() / '.ecnu-assistant' / 'tasks.db'
DB.parent.mkdir(exist_ok=True)

def connect():
    db = sqlite3.connect(DB)
    db.execute('CREATE TABLE IF NOT EXISTS tasks(id INTEGER PRIMARY KEY, title TEXT NOT NULL, due TEXT NOT NULL, repeat_days INTEGER NOT NULL DEFAULT 0, done INTEGER NOT NULL DEFAULT 0)')
    return db

PAGE = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>ECNU 小助手</title><style>body{margin:0;background:#f3f6fa;color:#17324d;font:16px system-ui}header{background:#174676;color:white;padding:28px max(20px,calc((100% - 960px)/2))}main{max-width:960px;margin:auto;padding:24px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:16px}.card{background:white;padding:20px;border-radius:14px;box-shadow:0 2px 12px #0001}input,select,button{font:inherit;padding:9px;margin:3px}button{background:#1965a2;color:white;border:0;border-radius:6px;cursor:pointer}button:disabled{background:#8c99a7}a{color:#17629b}li{margin:12px 0}.muted{color:#647485}</style><header><h1>ECNU 小助手</h1><p>面向华东师范大学学生 · 非学校官方应用</p></header><main><div class="grid"><section class="card"><h2>待办与定期计划</h2><form id="form"><input id="title" placeholder="要做什么" maxlength="120" required><input id="due" type="datetime-local" required><select id="repeat"><option value="0">仅一次</option><option value="1">每天</option><option value="7">每周</option></select><button>添加</button></form><ul id="tasks"></ul><button id="notify" type="button">开启浏览器通知</button><p class="muted">页面打开期间每 30 秒检查到期事项。后台提醒和 cmd 弹窗尚未接入。</p></section><section class="card"><h2>官网文件问答</h2><p>官方文件索引与带来源的 AI 问答尚未接入。</p><a href="https://www.ecnu.edu.cn/" target="_blank" rel="noopener noreferrer">访问华东师范大学官网 ↗</a></section><section class="card"><h2>学习助手</h2><p>学术问答、六级单词、课程资料与论文推荐：待接入。</p></section><section class="card"><h2>今日热点</h2><p>科技、金融、娱乐等偏好与当日新闻搜索：待接入。</p></section><section class="card"><h2>公共数据库</h2><button disabled>目标地址待确认</button></section><section class="card"><h2>校园论坛</h2><p>经验分享 · 生活分享 · 寻物启事 · 学习交流</p><p>SSO、发帖、私信及内容审核上线后开放。</p></section></div></main><script>const $=id=>document.getElementById(id);let seen=new Set();async function load(){let tasks=await(await fetch('/api/tasks')).json();$('tasks').replaceChildren(...tasks.filter(t=>!t.done).map(t=>{let li=document.createElement('li');li.textContent=t.title+' · '+new Date(t.due).toLocaleString()+(t.repeat_days?' · 每'+t.repeat_days+'天':'');let b=document.createElement('button');b.textContent='完成';b.onclick=async()=>{await fetch('/api/tasks/'+t.id,{method:'PATCH'});seen.delete(t.id);load()};li.append(' ',b);if(new Date(t.due)<=new Date()&&!seen.has(t.id)){seen.add(t.id);if(Notification.permission==='granted')new Notification('ECNU 小助手',{body:t.title})}return li}))}$('form').onsubmit=async e=>{e.preventDefault();await fetch('/api/tasks',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({title:$('title').value,due:new Date($('due').value).toISOString(),repeat_days:Number($('repeat').value)})});$('form').reset();load()};$('notify').onclick=()=>Notification.requestPermission();load();setInterval(load,30000)</script></html>'''

class Handler(BaseHTTPRequestHandler):
    def reply(self, code, body, kind='application/json'):
        raw=body.encode('utf-8'); self.send_response(code); self.send_header('Content-Type',kind+'; charset=utf-8'); self.send_header('Content-Length',str(len(raw))); self.send_header('X-Content-Type-Options','nosniff'); self.end_headers(); self.wfile.write(raw)
    def do_GET(self):
        if self.path=='/': return self.reply(200,PAGE,'text/html')
        if self.path!='/api/tasks': return self.reply(404,'{}')
        with connect() as db: rows=db.execute('SELECT id,title,due,repeat_days,done FROM tasks ORDER BY due').fetchall()
        self.reply(200,json.dumps([dict(zip(('id','title','due','repeat_days','done'),row)) for row in rows]))
    def do_POST(self):
        if self.path!='/api/tasks': return self.reply(404,'{}')
        try:
            size=int(self.headers.get('Content-Length','0'))
            if size<1 or size>4096: raise ValueError()
            item=json.loads(self.rfile.read(size)); title=item['title'].strip(); due=datetime.fromisoformat(item['due'].replace('Z','+00:00')); repeat=int(item.get('repeat_days',0))
            if not 0<len(title)<=120 or due.tzinfo is None or repeat not in (0,1,7): raise ValueError()
        except (ValueError,KeyError,TypeError): return self.reply(400,'{"error":"invalid task"}')
        with connect() as db: db.execute('INSERT INTO tasks(title,due,repeat_days) VALUES(?,?,?)',(title,due.isoformat(),repeat))
        self.reply(201,'{}')
    def do_PATCH(self):
        try:
            if not self.path.startswith('/api/tasks/'): raise ValueError()
            task_id=int(self.path.rsplit('/',1)[1]); assert task_id>0
        except (ValueError,AssertionError): return self.reply(404,'{}')
        with connect() as db:
            row=db.execute('SELECT due,repeat_days FROM tasks WHERE id=?',(task_id,)).fetchone()
            if not row: return self.reply(404,'{}')
            if row[1]: db.execute('UPDATE tasks SET due=? WHERE id=?',((datetime.fromisoformat(row[0])+timedelta(days=row[1])).isoformat(),task_id))
            else: db.execute('UPDATE tasks SET done=1 WHERE id=?',(task_id,))
        self.reply(200,'{}')

print('ECNU 小助手: http://127.0.0.1:8765')
ThreadingHTTPServer(('127.0.0.1',8765),Handler).serve_forever()
