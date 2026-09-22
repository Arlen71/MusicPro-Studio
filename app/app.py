"""Loopback-only browser application. No third-party Python packages required."""
from __future__ import annotations
import concurrent.futures, copy, json, os, secrets, subprocess, sys, threading, time, uuid, webbrowser
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
from engine import *
from reports import REPORT_NAME, rows_from_plan, rows_from_text, workbook_bytes, write_report, link_value
from runtime_support import VERSION, data_directory, InstanceLock, existing_address, console_python
from resources import render_budget, ResourceGovernor
from batch import BatchRecovery, issue_csv
from failures import raise_record
from playlist import REPORT_NAME as PLAYLIST_REPORT_NAME, text_from_plan as playlist_text

DATA=data_directory(ROOT); DATA.mkdir(parents=True,exist_ok=True)
TOKEN=secrets.token_urlsafe(32)
# The page names the launcher and the encoder the person actually has.
PLATFORM=(dict(os='macos',package='Mustaqil macOS paketi',launcher='MusicPro.command',
               gpu_label='GPU · Apple media engine',
               gpu_note='Apple apparat kodlovchisi (VideoToolbox) amalda tekshiriladi. Alohida drayver kerak emas.')
          if sys.platform=='darwin' else
          dict(os='windows',package='Mustaqil Windows paketi',launcher='MusicPro.exe',
               gpu_label='GPU · videokarta',
               gpu_note='Videokarta kodlovchisi amalda tekshiriladi. Mos videokarta drayveri kerak.')
          if os.name=='nt' else
          dict(os='other',package='Mustaqil paket',launcher='app/bootstrap.py',
               gpu_label='GPU · tezlatgich',
               gpu_note='GPU kodlovchisi amalda tekshiriladi.'))
LOCK=threading.RLock(); STOP=threading.Event(); EXITING=threading.Event(); BUSY=False
STATE={'status':'idle','message':'Yangi loyiha tayyorlang.','jobs':[],'logs':[]}
STATEFILE=DATA/'session.json'
if STATEFILE.exists():
    try:
        STATE=json.loads(STATEFILE.read_text(encoding='utf-8'))
        if STATE['status'] in ('planning','running','stopping'):
            STATE['status']='paused'; STATE['message']='Oldingi ish uzilgan. Davom ettirish mumkin.'
            for j in STATE.get('jobs',[]):
                if j['status']=='running': j['status']='pending'; j['progress']=0
    except (ValueError,KeyError): pass

def save():
    tmp=STATEFILE.with_suffix('.tmp')
    try:
        tmp.write_text(json.dumps(STATE,ensure_ascii=False,indent=2),encoding='utf-8')
        for attempt in range(3):
            try: os.replace(tmp,STATEFILE); break
            except PermissionError:
                if attempt==2: raise
                time.sleep(.03)
        STATE.pop('persistence_warning',None)
    except OSError as e:
        # A UI/session write must not abort an otherwise healthy media render.
        STATE['persistence_warning']='Navbat holati diskka saqlanmadi: '+str(e)

def log(message):
    with LOCK:
        STATE['message']=message; STATE.setdefault('logs',[]).append({'time':time.strftime('%H:%M:%S'),'message':message})
        STATE['logs']=STATE['logs'][-120:]; save()

def snapshot():
    with LOCK:
        d=copy.deepcopy({k:v for k,v in STATE.items() if k not in ('catalog','analysis','blocked')})
        for j in d.get('jobs',[]):
            p=j.pop('plan',None)
            if p:
                j['duration']=p['music']['duration']; j['segments']=len(p['segments'])
                j['licenses']=[{'name':s['asset']['name'],'start':s['start']/p['fps'],'end':(s['start']+s['frames'])/p['fps']} for s in p['segments'] if s['kind']=='license']
                j['report_rows']=rows_from_plan(p,j.get('video_url',''))
                j['report_ready']=(Path(j['dest'])/REPORT_NAME).is_file()
                j['strong_accents']=len(p.get('strong_frames',[])); j['effect_count']=p.get('effect_count',0)
                j['music_count']=len(p.get('tracks',[])) or 1
                j['playlist_text']=playlist_text(p)
                j['playlist_ready']=bool(p.get('tracks')) and (Path(j['dest'])/PLAYLIST_REPORT_NAME).is_file()
            else:
                j.update(duration=0,segments=0,licenses=[],report_rows=[],report_ready=False,strong_accents=0,effect_count=0)
                j.update(music_count=0,playlist_text='',playlist_ready=False)
        d['busy']=BUSY
        return d

def build(config):
    global BUSY
    recovery=None
    try:
        c=validate(config); log('Fayllar tekshirilmoqda. Muammoli manbalar avtomatik o‘tkaziladi…')
        out=Path(c['output']); out.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryFile(dir=out): pass
        with LOCK:
            STATE['batch']=time.strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:6]
        recovery=BatchRecovery(c,STATE,LOCK,STOP,save,log); recovery.load_catalog()
        gpu=None
        if c['device'] in ('gpu','mixed'):
            try: gpu=encoder('gpu')
            except UserError as e:
                recovery.issue('device',{'path':'GPU','name':'GPU kodlovchi'},str(e),action='CPU orqali tayyorlanadi')
        jobs=[]
        for i in range(c['total']):
            device='auto' if c['device']=='mixed' and gpu else 'gpu' if c['device']=='gpu' and gpu else 'cpu'
            jobs.append(dict(id=i+1,music='Manba tanlanmoqda',status='pending',progress=0,device=device,
                             encoder=gpu if device=='gpu' else None if device=='auto' else 'libx264',dest=str(out/f'{STATE["batch"]}_{i+1:04}'),error=''))
        with LOCK: STATE['jobs']=jobs; save()
        for job in jobs:
            if STOP.is_set(): raise Cancelled()
            log(f'Reja tuzilmoqda: {job["id"]}/{len(jobs)}')
            try: recovery.prepare(job)
            except UserError as e:
                with LOCK: job.update(status='error',error=str(e)); save()
                recovery.issue('render',{'path':job['dest'],'name':f'{job["id"]}-video'},str(e),job,'Reja tuzilmadi; boshqa natijalar davom etadi')
        with LOCK:
            STATE.update(status='ready' if any(j.get('plan') for j in jobs) else 'error',config=c,
                         summary={**{field:len(recovery.available(role)) for role,field in [('clip','clips'),('license','licenses'),('music','music')]},'videos':len(jobs),'gpu':gpu})
            save()
        log('Rejalar tayyor. Montaj boshlanganidan keyin muammoli manbalar tasdiqsiz almashtiriladi.' if STATE['status']=='ready' else 'Yaroqli manbalar bilan reja tuzilmadi. Tafsilotlar muammolar ro‘yxatida.')
    except Cancelled:
        with LOCK: STATE['status']='paused'
        log('Reja tuzish to‘xtatildi. Tayyor rejalarni davom ettirish mumkin.')
    except Exception as e:
        with LOCK: STATE['status']='error'
        log(str(e))
    finally:
        if recovery: recovery.save_issues()
        with LOCK: BUSY=False

def render_isolated(j,c,progress):
    request=DATA/('worker_'+str(j['id'])+'_'+uuid.uuid4().hex+'.json')
    stopfile=request.with_suffix('.stop');progressfile=request.with_suffix('.progress')
    resultfile=request.with_suffix('.result')
    stopfile.unlink(missing_ok=True);progressfile.unlink(missing_ok=True)
    request.write_text(json.dumps(dict(plan=j['plan'],config=c,dest=j['dest'],encoder=j['encoder']),ensure_ascii=False),encoding='utf-8')
    try:
        with tempfile.TemporaryFile() as log_file:
            flags=CREATE_FLAGS
            command=[console_python(),'-X','utf8','-B',str(ROOT/'worker.py'),str(request)]
            if c.get('resources','auto')=='auto':
                if os.name=='nt': flags|=subprocess.BELOW_NORMAL_PRIORITY_CLASS
                # preexec_fn is unsafe in this threaded server; nice(1) is not.
                elif sys.platform=='darwin': command=['/usr/bin/nice','-n','5']+command
            proc=subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=log_file,stderr=log_file,creationflags=flags,env={**os.environ,'PYTHONIOENCODING':'utf-8'})
            while proc.poll() is None:
                if STOP.is_set():stopfile.touch()
                try:
                    if progressfile.exists():progress(float(progressfile.read_text(encoding='ascii')))
                except (ValueError,OSError):pass
                time.sleep(.15)
            if proc.returncode==42:raise Cancelled()
            if proc.returncode:
                try: result=json.loads(resultfile.read_text(encoding='utf-8'))
                except (OSError,ValueError): result=None
                if result: raise_record(result)
                log_file.seek(0);raise UserError(log_file.read().decode('utf-8',errors='replace')[-5000:])
            progress(1)
    finally:
        for path in (request,stopfile,progressfile,resultfile,progressfile.with_suffix('.tmp'),resultfile.with_suffix('.tmp')):
            try:path.unlink(missing_ok=True)
            except OSError:pass

def run_batch():
    global BUSY
    governor=None; recovery=None
    try:
        c=validate(STATE['config']); jobs=STATE['jobs']
        recovery=BatchRecovery(c,STATE,LOCK,STOP,save,log)
        if not recovery.catalog: recovery.load_catalog()
        gpu=STATE.get('summary',{}).get('gpu') if c['device'] in ('gpu','mixed') else None
        # Older paused sessions may not have saved the encoder summary yet.
        if c['device'] in ('gpu','mixed') and 'gpu' not in STATE.get('summary',{}):
            try: gpu=encoder('gpu')
            except UserError as e:
                recovery.issue('device',{'path':'GPU','name':'GPU kodlovchi'},str(e),action='CPU orqali tayyorlanadi')
        encoders={'cpu':'libx264'}
        if gpu:
            encoders={'cpu':'libx264','gpu':gpu} if c['device']=='mixed' else {'gpu':gpu}
        pending=deque(j for j in jobs if j['status']!='done')
        budget=render_budget(c,encoders)
        devices=list(encoders)
        if not budget['parallel_lanes'] or len(pending)<2:
            # One safe lane on low-memory machines; prefer the available GPU.
            devices=['gpu' if gpu else 'cpu']
            budget=render_budget(c,devices)
        with LOCK:
            STATE['resource_budget']=budget; STATE['status']='running'; STATE['scheduling']='shared'; save()
        governor=ResourceGovernor(c['resources'],log); governor.start()
        for device,limits in budget['lanes'].items():
            log(f'{device.upper()}: {limits["segment_workers"]} parallel segment.')
        log('Montaj boshlandi. Umumiy navbat: bo‘shagan qurilma navbatdagi videoni oladi. Tiklash avtomatik.')
        def lane(device):
            lane_encoder=encoders[device]; limits=budget['lanes'][device]
            while True:
                # Claim exactly once, independently of mutable job.device. A
                # GPU-to-CPU retry keeps ownership of the same claimed job.
                with LOCK:
                    if STOP.is_set() or not pending: return
                    j=pending.popleft()
                    j.update(device=device,encoder=lane_encoder,status='running',progress=0,error=''); save()
                try:
                    def progress(v):
                        with LOCK: j['progress']=round(v,4)
                    recovery.run_job(j,lambda job,conf:render_isolated(job,conf,progress),
                                     {**c,'_render_budget':limits})
                    recovery.completed(j)
                    with LOCK: j.update(status='done',progress=1,error=''); save()
                    log(f'Tayyor: {j["id"]} — {j["music"]}')
                except Cancelled:
                    with LOCK: j.update(status='pending',progress=0); save()
                except Exception as e:
                    with LOCK: j.update(status='error',error=str(e)); save()
                    recovery.issue('render',{'path':j['dest'],'name':f'{j["id"]}-video'},str(e),j,'Tayyorlanmadi; boshqa natijalar davom etadi')
                if device=='gpu' and j['encoder']=='libx264':
                    # A failed GPU is not retried for every remaining video.
                    # Let the existing CPU lane drain the queue, or continue
                    # serially on CPU when this was the only active lane.
                    log('GPU zaxira CPU rejimiga o‘tdi. Qolgan navbat CPU orqali davom etadi.')
                    if 'cpu' in devices: return
                    device='cpu'; lane_encoder='libx264'; limits={**limits,'segment_workers':1}
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(devices)) as pool:
            futures=[pool.submit(lane,d) for d in devices]
            for f in futures: f.result()
        done=sum(j['status']=='done' for j in jobs)
        with LOCK:
            STATE['status']='paused' if STOP.is_set() else ('completed_issues' if STATE.get('issues') else 'completed') if done==len(jobs) else 'error'
            save()
        log(f'Tayyor: {done}/{len(jobs)}. Muammolar: {len(STATE.get("issues",[]))}. '+
            ('Jarayon foydalanuvchi tomonidan to‘xtatildi.' if STOP.is_set() else 'Tafsilotlar muammolar ro‘yxatida.'))
    except Exception as e:
        with LOCK: STATE['status']='error'
        log(str(e))
    finally:
        if recovery: recovery.save_issues()
        if governor: governor.close()
        with LOCK: BUSY=False

def start_task(fn,*args):
    global BUSY
    with LOCK:
        if EXITING.is_set(): raise UserError('Dastur yopilmoqda.')
        if BUSY: raise UserError('Jarayon ishlamoqda. Avval uni to‘xtating.')
        BUSY=True; STOP.clear()
    threading.Thread(target=fn,args=args,daemon=True).start()

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def send(self,value,code=200,ctype='application/json; charset=utf-8'):
        data=value if isinstance(value,bytes) else json.dumps(value,ensure_ascii=False).encode()
        self.send_response(code); self.send_header('Content-Type',ctype); self.send_header('Content-Length',str(len(data)))
        self.send_header('Cache-Control','no-store'); self.send_header('X-Content-Type-Options','nosniff'); self.send_header('X-Frame-Options','DENY'); self.end_headers()
        try: self.wfile.write(data)
        except (BrokenPipeError,ConnectionResetError): pass
    def valid_host(self):
        return self.headers.get('Host') in (f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}')
    def do_GET(self):
        if not self.valid_host(): return self.send({'error':'Host rejected'},403)
        path=urlparse(self.path).path
        if path=='/api/state': return self.send(snapshot())
        if path=='/api/init': return self.send({'token':TOKEN,'config':STATE.get('config',{}),'version':VERSION,'platform':PLATFORM})
        if path=='/api/issues/export':
            with LOCK: data=issue_csv(STATE.get('issues',[]))
            return self.download(data,'MusicPro_muammolar.csv','text/csv; charset=utf-8')
        if path.startswith('/api/playlist/'):
            try:
                job_id=int(path.rsplit('/',1)[-1])
                with LOCK: j=next(j for j in STATE['jobs'] if j['id']==job_id)
                p=Path(j['dest'])/PLAYLIST_REPORT_NAME
                if j['status']!='done' or not j.get('plan',{}).get('tracks') or not p.is_file():
                    return self.send({'error':'Playlist TXT hali tayyor emas.'},404)
                return self.download(p.read_bytes(),f'Playlist_{job_id:04}.txt','text/plain; charset=utf-8')
            except (ValueError,StopIteration,OSError):return self.send({'error':'Playlist TXT topilmadi.'},404)
        if path.startswith('/api/report/'):
            try:
                job_id=int(path.rsplit('/',1)[-1])
                with LOCK: j=next(j for j in STATE['jobs'] if j['id']==job_id)
                p=Path(j['dest'])/REPORT_NAME
                if j['status']!='done' or not p.is_file(): return self.send({'error':'Hisobot hali tayyor emas.'},404)
                return self.download(p.read_bytes(),f'Litsen_{job_id:04}.xlsx')
            except (ValueError,StopIteration,OSError):return self.send({'error':'Hisobot topilmadi.'},404)
        # The one user guide lives at the bundle root, next to the launchers.
        files={'/':(ROOT/'web/studio.html','text/html; charset=utf-8'),'/style.css':(ROOT/'web/studio.css','text/css; charset=utf-8'),'/app.js':(ROOT/'web/studio.js','text/javascript; charset=utf-8'),'/help':(ROOT.parent/'BOSHLASH.html','text/html; charset=utf-8')}
        if path in files:
            f,ct=files[path]
            if not f.is_file(): return self.send({'error':f'{f.name} topilmadi. Paketni to‘liq oching.'},404)
            return self.send(f.read_bytes(),ctype=ct)
        self.send({'error':'Not found'},404)
    def do_POST(self):
        if not self.valid_host() or self.headers.get('X-MusicPro-Token')!=TOKEN: return self.send({'error':'So‘rov rad etildi. Sahifani yangilang.'},403)
        origin=self.headers.get('Origin')
        if origin and origin not in (f'http://127.0.0.1:{self.server.server_port}',f'http://localhost:{self.server.server_port}'): return self.send({'error':'Origin rejected'},403)
        try:
            if EXITING.is_set(): raise UserError('Dastur yopilmoqda.')
            size=int(self.headers.get('Content-Length',0))
            if size<0 or size>2*1024*1024: raise UserError('So‘rov juda katta. TXT fayl 2 MB dan kichik bo‘lsin.')
            body=json.loads(self.rfile.read(size) or b'{}'); path=urlparse(self.path).path
            if path=='/api/plan':
                c=validate(body)
                with LOCK:
                    if BUSY: raise UserError('Jarayon ishlamoqda.')
                    STATE.update(status='planning',jobs=[],logs=[],config=c,summary={},issues=[],blocked={},analysis={},catalog={}); save()
                    start_task(build,c)
            elif path=='/api/run':
                if not STATE.get('jobs'): raise UserError('Avval fayllarni tekshirib, reja tuzing.')
                start_task(run_batch)
            elif path=='/api/report':
                with LOCK:
                    j=next((j for j in STATE['jobs'] if j['id']==int(body['id'])),None)
                    if not j or j['status']!='done':raise UserError('Avval tanlangan video montaji tugasin.')
                    url=str(body.get('video_url',''))
                    link_value(url)
                    write_report(j['plan'],j['dest'],url)
                    j['video_url']=url;j['plan']['video_url']=url
                    (Path(j['dest'])/'reja.json').write_text(json.dumps(j['plan'],ensure_ascii=False,indent=2),encoding='utf-8')
                    save()
                return self.send({'ok':True,'rows':rows_from_plan(j['plan'],url)})
            elif path=='/api/convert':
                rows=rows_from_text(str(body.get('text','')),body.get('video_url',''))
                return self.download(workbook_bytes(rows),'Litsen_video_malumot.xlsx')
            elif path=='/api/stop':
                STOP.set()
                with LOCK:
                    if BUSY: STATE['status']='stopping'; save()
            elif path=='/api/browse':
                p=subprocess.run([console_python(),'-X','utf8','-B',str(ROOT/'folder_dialog.py')],capture_output=True,encoding='utf-8',errors='replace',creationflags=CREATE_FLAGS)
                if p.returncode: raise UserError('Papka oynasi ochilmadi. Papkaning to‘liq manzilini kiriting.')
                return self.send({'path':p.stdout.strip()})
            elif path=='/api/music-list':
                return self.send(music_choices(body.get('music','')))
            elif path=='/api/shutdown':
                with LOCK:
                    if BUSY: raise UserError('Avval montajni to‘xtating va jarayon to‘xtashini kuting.')
                    EXITING.set()
                    save()
                self.send({'ok':True})
                threading.Thread(target=self.server.shutdown,daemon=True).start()
                return
            elif path=='/api/open':
                out=STATE.get('config',{}).get('output')
                if body.get('id'):
                    j=next((j for j in STATE['jobs'] if j['id']==int(body['id'])),None)
                    if j:out=j['dest']
                if not (out and Path(out).is_dir()): raise UserError('Natija papkasi hali mavjud emas.')
                if os.name=='nt': os.startfile(out)
                elif sys.platform=='darwin': subprocess.run(['/usr/bin/open',str(out)],check=False)
                else: raise UserError('Papkani ochish bu tizimda qo‘llab-quvvatlanmaydi.')
            else: return self.send({'error':'Not found'},404)
            self.send({'ok':True})
        except (UserError,ValueError,TypeError,KeyError) as e: self.send({'error':str(e)},400)
        except Exception as e: self.send({'error':str(e)},500)

    def download(self,data,name,ctype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'):
        self.send_response(200)
        self.send_header('Content-Type',ctype)
        self.send_header('Content-Disposition',f'attachment; filename="{name}"')
        self.send_header('Content-Length',str(len(data)))
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.end_headers()
        try:self.wfile.write(data)
        except (BrokenPipeError,ConnectionResetError):pass

def main():
    instance=InstanceLock(DATA)
    if not instance.acquire():
        # A second double-click opens the existing server instead of another queue.
        if '--no-browser' not in sys.argv:
            address=existing_address(DATA)
            if address: webbrowser.open(address)
        print('MusicPro is already running.',flush=True)
        return
    server=None
    for port in range(8765,8785):
        try: server=ThreadingHTTPServer(('127.0.0.1',port),Handler); break
        except OSError: pass
    if server is None:
        instance.close()
        raise UserError('8765–8784 portlar band.')
    address=f'http://127.0.0.1:{server.server_port}'
    (DATA/'instance.json').write_text(json.dumps({'address':address,'pid':os.getpid()}),encoding='utf-8')
    print(f'MusicPro: {address}',flush=True)
    if '--no-browser' not in sys.argv: threading.Timer(.7,lambda:webbrowser.open(address)).start()
    try: server.serve_forever()
    except KeyboardInterrupt:
        STOP.set()
    finally:
        STOP.set(); server.server_close()
        deadline=time.monotonic()+10
        while BUSY and time.monotonic()<deadline:time.sleep(.1)
        (DATA/'instance.json').unlink(missing_ok=True)
        instance.close()

if __name__=='__main__': main()
