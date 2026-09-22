"""MusicPro: local deterministic planning and FFmpeg rendering. Python 3.11+."""
from __future__ import annotations
import bisect, hashlib, json, math, os, random, shutil, subprocess, sys, tempfile, threading
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from pathlib import Path
from reports import write_report
from effects import EFFECTS, PRESETS, STRENGTHS, assign_effects, effect_filters
from resources import render_budget
from failures import UserError, Cancelled, SourceError, EncoderError, check_storage_error
from audio_analysis import analyze_pcm
from playlist import SAMPLE_RATE, validate_tracks, write_playlist, validate_order_config
from output_names import video_filename

ROOT = Path(__file__).resolve().parent
VIDEO = {'.mp4','.mov','.mkv','.avi','.webm','.m4v','.mts'}
AUDIO = {'.mp3','.wav','.flac','.m4a','.aac','.ogg','.opus','.wma'}
CREATE_FLAGS = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
MAC = sys.platform == 'darwin'
# Both packaged platforms ship their own FFmpeg; only they may report it missing.
BUNDLED = os.name == 'nt' or MAC

def binary(name):
    local = ROOT / 'bin' / (name + ('.exe' if os.name == 'nt' else ''))
    if BUNDLED and (ROOT.parent/'bundle.json').is_file() and not local.is_file():
        raise UserError(f'Paket to‘liq emas: {local.name} yo‘q. MusicPro papkasini to‘liq qayta ko‘chiring yoki Setupni qayta oching.')
    found = str(local) if local.is_file() else shutil.which(name)
    if not found: raise UserError(f'{name} topilmadi. BOSHLASH.html dagi o‘rnatish qadamlarini bajaring.')
    return found

def execute(args, stop=None, timeout=3600):
    # No shell; logs go to a file so a full stderr pipe cannot deadlock rendering.
    with tempfile.TemporaryFile() as log:
        p = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=log, stderr=log, creationflags=CREATE_FLAGS)
        import time
        deadline = time.monotonic() + timeout
        while p.poll() is None:
            if stop and stop.wait(.15):
                p.terminate()
                try: p.wait(5)
                except subprocess.TimeoutExpired: p.kill(); p.wait()
                raise Cancelled()
            if not stop: time.sleep(.1)
            if time.monotonic() > deadline:
                p.kill(); p.wait(); raise UserError('Jarayon uchun ajratilgan vaqt tugadi.')
        log.seek(0); data = log.read().decode('utf-8', errors='replace')
        if p.returncode: raise UserError(data[-5000:] or f'Jarayon xato kodi: {p.returncode}')
        return data

def probe(path, kind):
    try:
        d = json.loads(execute([binary('ffprobe'),'-v','error','-show_streams','-show_format','-of','json',str(path)],timeout=60))
        s = next(s for s in d['streams'] if s['codec_type']==kind and not s.get('disposition',{}).get('attached_pic'))
        duration = float(s.get('duration') or d['format'].get('duration',0))
        if not math.isfinite(duration) or duration <= 0: raise ValueError('duration')
        rate=None
        try:
            num,den=map(float,str(s.get('avg_frame_rate') or s.get('r_frame_rate') or '0/0').split('/'))
            if den and num>0: rate=num/den
        except (TypeError,ValueError): pass
        st = path.stat()
        return dict(path=str(path.resolve()), name=path.name, duration=duration, size=st.st_size, mtime=st.st_mtime_ns,
                    frames=int(s['nb_frames']) if str(s.get('nb_frames','')).isdigit() else None,frame_rate=rate)
    except (ValueError, KeyError, StopIteration, UserError, OSError) as e:
        raise UserError(f'Faylni o‘qib bo‘lmadi: {path.name}. {e}') from e

def scan(folder, kind, on_problem=None, stop=None):
    p = Path(folder).expanduser().resolve()
    if not p.is_dir(): raise UserError(f'Papka topilmadi: {p}')
    files = sorted((f for f in p.iterdir() if f.is_file() and f.suffix.lower() in (VIDEO if kind=='video' else AUDIO)),key=lambda f:f.name.lower())
    if not files: raise UserError(f'Mos {kind} fayllari yo‘q: {p}')
    assets=[]
    for f in files:
        if stop and stop.is_set(): raise Cancelled()
        try: assets.append(probe(f,kind))
        except (UserError,OSError) as e:
            if on_problem is None: raise
            on_problem(dict(path=str(f.resolve()),name=f.name),str(e))
    return assets

def validate(raw):
    c = dict(raw)
    for k in ('clips','licenses','music','output'):
        if not isinstance(c.get(k),str) or not c[k].strip(): raise UserError(f'{k}: papkani tanlang.')
        c[k] = str(Path(c[k]).expanduser().resolve())
    if len({c[k] for k in ('clips','licenses','music','output')}) != 4: raise UserError('To‘rtta alohida papka tanlang.')
    for k, default, lo, hi in [('total',10,1,10000),('license_count',1,0,100),('fps',30,25,60),('height',1080,720,1080),('playlist_count',5,1,1000)]:
        try:
            v = float(c.get(k,default)); c[k]=int(v)
            if v != c[k] or not lo <= c[k] <= hi: raise ValueError()
        except (ValueError,TypeError,OverflowError): raise UserError(f'{k}: {lo}–{hi} oralig‘idagi butun son kerak.')
    for k,default,lo,hi in [('first_license',60,0,86400),('license_gap',15,0,86400),('cut_min',3,.5,60),('cut_max',8,.5,300),('effect_gap',2,.5,30)]:
        try:
            c[k]=float(c.get(k,default))
            if not math.isfinite(c[k]) or not lo<=c[k]<=hi: raise ValueError()
        except (ValueError,TypeError): raise UserError(f'{k}: {lo}–{hi} oralig‘idagi son kerak.')
    if c['cut_max'] < c['cut_min']: raise UserError('Maksimal kadr vaqti minimal vaqtdan kichik bo‘lmasin.')
    if c.get('effects') in ('flash','black'): c['effects']='edit'
    for k,values,default in [('device',('cpu','gpu','mixed'),'cpu'),('mode',('random','beat'),'random'),('music_mode',('single','playlist'),'single'),('quality',('economy','balanced','high'),'balanced'),('resources',('auto','medium','high'),'auto'),('effects',PRESETS,'off'),('effect_strength',tuple(STRENGTHS),'balanced')]:
        c[k]=c.get(k,default)
        if c[k] not in values: raise UserError(f'{k}: noto‘g‘ri qiymat.')
    if c['fps'] not in (25,30,60) or c['height'] not in (720,1080): raise UserError('720p/1080p va 25/30/60 FPS tanlang.')
    validate_order_config(c)
    return c

def music_choices(folder):
    if not isinstance(folder,str) or not folder.strip():
        raise UserError('Avval Musikalar papkasini tanlang.')
    path=Path(folder).expanduser().resolve()
    if not path.is_dir(): raise UserError('Musikalar papkasi topilmadi.')
    # Metadata-only list keeps the selection panel quick. Full, strict decode
    # remains part of planning/render and uses the existing unattended recovery.
    try:
        files=[dict(path=str(p.resolve()),name=p.name) for p in path.iterdir()
               if p.is_file() and p.suffix.lower() in AUDIO]
    except OSError as e:
        raise UserError('Musiqalar ro‘yxatini o‘qib bo‘lmadi: '+str(e)) from e
    return dict(folder=str(path),files=sorted(files,key=lambda a:(a['name'].casefold(),a['name'])))

def analyze_music(path, stop=None):
    """Strict full audio decode, then independent cut/strong-accent detection."""
    with tempfile.TemporaryDirectory(prefix='musicpro_audio_') as tmp:
        pcm=Path(tmp)/'audio.pcm'
        execute([binary('ffmpeg'),'-nostdin','-v','error','-xerror','-y','-err_detect','explode','-i',str(path),'-vn','-ac','2','-ar','12000','-f','s16le',str(pcm)],stop)
        if pcm.stat().st_size==0: raise UserError('Musiqada o‘qiladigan audio topilmadi.')
        result=analyze_pcm(pcm,stop)
        result['decoded_duration']=pcm.stat().st_size/48000
        return result

def detect_accents(path,stop=None):
    return analyze_music(path,stop)['cuts']

def analyze_playlist_music(path,stop=None):
    """Analyze accents and measure the exact PCM layout used by playlist renders."""
    with tempfile.TemporaryDirectory(prefix='musicpro_playlist_analysis_') as tmp:
        full=Path(tmp)/'full.pcm'; accents=Path(tmp)/'accents.pcm'
        execute([binary('ffmpeg'),'-nostdin','-v','error','-xerror','-y','-err_detect','explode',
                 '-i',str(path),'-map','0:a:0','-vn','-ac','2','-ar',str(SAMPLE_RATE),'-f','s16le',str(full),
                 '-map','0:a:0','-vn','-ac','2','-ar','12000','-f','s16le',str(accents)],stop,timeout=86400)
        count=full.stat().st_size//4
        if count<=0 or full.stat().st_size%4:
            raise UserError('Musiqada o‘qiladigan to‘liq audio topilmadi.')
        result=analyze_pcm(accents,stop)
        result.update(decoded_duration=count/SAMPLE_RATE,decoded_samples=count,sample_rate=SAMPLE_RATE)
        return result

def music_frame_count(music,fps):
    if music.get('sample_rate')==SAMPLE_RATE and 'samples' in music:
        return (music['samples']*fps+SAMPLE_RATE-1)//SAMPLE_RATE
    return math.ceil(music['duration']*fps)

def verify_input(asset,role,stop=None):
    """Diagnose only a failed render source, with CPU decode and no output file."""
    stream='a' if role=='music' else 'v'
    try:
        execute([binary('ffmpeg'),'-nostdin','-v','error','-xerror','-err_detect','explode','-threads','1',
                 '-i',asset['path'],'-map',f'0:{stream}:0','-f','null','-'],stop,
                timeout=max(60,min(900,asset.get('duration',60)*3+30)))
    except (UserError,OSError) as e:
        raise SourceError(asset,role,str(e)) from e

def choose_licenses(assets, count, rng):
    if count and not assets: raise UserError('Kamida 5 soniyali litsen video topilmadi. Litsen papkasiga uzunroq video qo‘shing.')
    result=[]
    while len(result)<count:
        cycle=assets[:]; rng.shuffle(cycle)
        result.extend(cycle[:count-len(result)])
    return result

def plan_one(clips, licenses, music, c, seed, accents=None):
    """Integer-frame schedule. Ordinary clips only repeat after exhaustion of a cycle.
    Licensed sources supply random 5–7 second excerpts at ordinary boundaries.
    Reject constraints that cannot be satisfied, rather than silently change them.
    """
    rng=random.Random(seed); fps=c['fps']; total=music_frame_count(music,fps)
    first=math.ceil(c['first_license']*fps); gap=math.ceil(c['license_gap']*fps)
    full=lambda a:max(1,math.ceil(a['duration']*fps-1e-7))
    analysis=accents if isinstance(accents,dict) else {'cuts':accents or [],'strong':[]}
    accents=sorted(set(analysis.get('cuts',[])))
    strong_frames=sorted({round(t*fps) for t in analysis.get('strong',[]) if 0<t<total/fps})
    n=c['license_count']
    licenses=[a for a in licenses if math.floor(a['duration']*fps+1e-7)>=5*fps]
    if not clips: raise UserError('Bo‘laklar topilmadi.')
    if n and first+5*fps*n+gap*(n-1)+1>total:
        raise UserError(f'“{music["name"]}”: {n} ta kamida 5 soniyali litsen, boshlanish va intervallar musiqaga sig‘maydi. Son/intervalni kamaytiring yoki uzunroq musiqa tanlang.')
    # Try random orders and positions; a deterministic earliest-placement fallback is included.
    for attempt in range(600):
        selected=choose_licenses(licenses,n,rng)
        # A final shortest-length fallback can find tight but valid schedules.
        lens=[rng.randint(5*fps,min(7*fps,math.floor(a['duration']*fps+1e-7))) if attempt<550 else 5*fps for a in selected]
        offsets=[rng.randint(0,max(0,math.floor(a['duration']*fps+1e-7)-frames))/fps for a,frames in zip(selected,lens)]
        if n and first+sum(lens)+gap*(n-1)+1>total: continue
        t=0; li=0; last_end=None; schedule=[]; bag=[]; previous=None
        slack=total-(first+sum(lens)+gap*max(0,n-1)+1)
        target=first+(rng.randrange(max(1,slack//max(1,n+1))) if attempt<450 and n else 0)
        while t<total:
            if li<n and t>=target and schedule and schedule[-1]['kind']=='clip':
                # Need one final ordinary frame; never truncate a licensed tail.
                if t+sum(lens[li:])+gap*max(0,n-li-1)+1>total: break
                a=selected[li]; frames=lens[li]
                schedule.append(dict(kind='license',asset=a,start=t,frames=frames,source_start=round(offsets[li],6)))
                t+=frames; li+=1; last_end=t
                target=last_end+gap
                if attempt<450 and li<n:
                    room=total-(target+sum(lens[li:])+gap*max(0,n-li-1)+1)
                    if room>0: target+=rng.randrange(max(1,room//(n-li+1)))
                continue
            if not bag:
                bag=clips[:]; rng.shuffle(bag)
                if len(bag)>1 and previous and bag[-1]['path']==previous:
                    bag[0],bag[-1]=bag[-1],bag[0]
            a=bag.pop(); previous=a['path']; frames=full(a); offset=0
            if c['mode']=='beat':
                upper=min(frames,max(1,round(c['cut_max']*fps)))
                lower=min(upper,max(1,round(c['cut_min']*fps)))
                candidates=[round(x*fps)-t for x in accents[bisect.bisect_left(accents,(t+lower)/fps):bisect.bisect_right(accents,(t+upper)/fps)]]
                strong_candidates=[f-t for f in strong_frames if t+lower<=f<=t+upper]
                frames=strong_candidates[0] if strong_candidates else (candidates[0] if candidates else upper)
                if not strong_candidates and not candidates:
                    # A short clean cut can make the following strong hit reachable.
                    # Otherwise a fractional license ending can keep all later hits
                    # just below cut_min forever when upper is an integer second.
                    future=next((f-t for f in strong_frames if f>t+upper),None)
                    if future is not None and lower<=future-lower<=upper:
                        frames=future-lower
                frames=max(1,min(frames,upper))
                offset=rng.uniform(0,max(0,a['duration']-frames/fps))
            frames=min(frames,total-t) # Only ordinary final footage is trimmed to the music.
            schedule.append(dict(kind='clip',asset=a,start=t,frames=frames,source_start=round(offset,6)))
            t+=frames
        if t==total and li==n:
            assign_effects(schedule,c.get('effects','off'),seed,strong_frames,fps,c.get('effect_gap',2))
            return dict(plan_version=4,music=music,seed=seed,fps=fps,total_frames=total,segments=schedule,accent_count=len(accents),strong_frames=strong_frames,
                        effect_count=sum(bool(s.get('fx_in')) for s in schedule))
    raise UserError(f'“{music["name"]}” ({music["duration"]:.1f} s): {n} ta 5–7 soniyali litsen, {c["first_license"]:g} s boshlanish va {c["license_gap"]:g} s intervalga mos reja topilmadi. Son/intervalni kamaytiring, qisqaroq bo‘laklar yoki uzunroq musiqa tanlang.')

def validate_plan(plan,c):
    if plan.get('plan_version') not in (4,5):
        raise UserError('Bu navbat oldingi versiyada tuzilgan. Kuchli urg‘ular bo‘yicha yangi reja kerak.')
    if plan.get('plan_version')==5:
        validate_tracks(plan,c)
    elif plan.get('tracks') or c.get('music_mode','single')=='playlist':
        raise UserError('Playlist rejimi uchun yangi reja tuzing.')
    fps=plan['fps']; t=0; last_license_end=None; licensed=0; segments=plan['segments']
    if fps!=c['fps'] or plan['total_frames']!=music_frame_count(plan['music'],fps):
        raise UserError('Reja sozlamalarga mos emas. Rejani qayta tuzing.')
    for i,s in enumerate(segments):
        if s['kind'] not in ('clip','license') or not isinstance(s['frames'],int) or s['frames']<=0 or s['start']!=t:
            raise UserError('Rejadagi kadr ketma-ketligi buzilgan. Rejani qayta tuzing.')
        if s['kind']=='license':
            licensed+=1
            if not 5*fps<=s['frames']<=7*fps or s['source_start']<0 or s['source_start']+s['frames']/fps>s['asset']['duration']+1e-6:
                raise UserError('Litsen parcha 5–7 soniya bo‘lishi va manbaga to‘liq sig‘ishi shart. Rejani qayta tuzing.')
            earliest=math.ceil(c['first_license']*fps) if last_license_end is None else last_license_end+math.ceil(c['license_gap']*fps)
            if t<earliest or i==0 or i==len(segments)-1 or segments[i-1]['kind']!='clip':
                raise UserError('Litsen joylashuvi yoki intervali noto‘g‘ri. Rejani qayta tuzing.')
            if s.get('fx_in') or s.get('fx_out'): raise UserError('Litsen videoga effekt qo‘llanmaydi. Rejani qayta tuzing.')
            last_license_end=t+s['frames']
        for key,neighbor in (('fx_in',i-1),('fx_out',i+1)):
            if s.get(key) and (s[key] not in EFFECTS or not 0<=neighbor<len(segments) or segments[neighbor]['kind']!='clip'):
                raise UserError('Effekt litsen chegarasiga o‘ta olmaydi. Rejani qayta tuzing.')
            if s.get(key):
                anchor=s['start'] if key=='fx_in' else s['start']+s['frames']
                opposite='fx_out' if key=='fx_in' else 'fx_in'
                if anchor not in plan.get('strong_frames',[]) or segments[neighbor].get(opposite)!=s[key]:
                    raise UserError('Effekt kuchli musiqa urg‘usiga mos emas. Rejani qayta tuzing.')
        t+=s['frames']
    if t!=plan['total_frames'] or licensed!=c['license_count']:
        raise UserError('Reja davomiyligi yoki litsen soni mos emas. Rejani qayta tuzing.')

def fingerprint(plan):
    rows=[(s['asset']['path'],s['start'],s['frames'],s['source_start'],s['kind']) for s in plan['segments']]
    return hashlib.sha256(json.dumps([plan['music']['path'],rows],sort_keys=True).encode()).hexdigest()

# Apple Silicon/Intel Macs expose one media engine through VideoToolbox.
GPU_ENCODERS = ('h264_videotoolbox',) if MAC else ('h264_nvenc','h264_qsv','h264_amf')

def encoder(device):
    if device=='cpu': return 'libx264'
    errors=[]
    for name in GPU_ENCODERS:
        try:
            execute([binary('ffmpeg'),'-v','error','-f','lavfi','-i','color=s=128x128:r=30','-frames:v','3','-an','-c:v',name,'-pix_fmt','yuv420p','-f','null','-'],timeout=30)
            return name
        except UserError as e: errors.append(f'{name}: {str(e)[-500:]}')
    raise UserError('GPU kodlash sinovi o‘tmadi. Drayver/FFmpeg mosligini tekshiring yoki CPU rejimini tanlang.\n'+'\n'.join(errors))

def encoding_args(enc,quality,threads=4):
    crf={'economy':25,'balanced':21,'high':18}[quality]
    if enc=='libx264': return ['-c:v',enc,'-preset','fast','-crf',str(crf),'-threads',str(threads),'-bf','0']
    if enc=='h264_nvenc': return ['-c:v',enc,'-preset','p4','-rc','vbr','-cq',str(crf),'-b:v','0']
    if enc=='h264_qsv': return ['-c:v',enc,'-global_quality',str(crf)]
    if enc=='h264_videotoolbox':
        # VideoToolbox rates quality 1–100 upwards; these match the CRF sizes.
        # Software fallback keeps a render alive when the media engine is busy.
        return ['-c:v',enc,'-q:v',str({'economy':45,'balanced':60,'high':75}[quality]),'-allow_sw','1']
    return ['-c:v',enc,'-quality','balanced','-rc','cqp','-qp_i',str(crf),'-qp_p',str(crf)]

def stamp(seconds):
    ms=round(seconds*1000); h,ms=divmod(ms,3600000); m,ms=divmod(ms,60000); s,ms=divmod(ms,1000)
    return f'{h:02}:{m:02}:{s:02}.{ms:03}'

def render_playlist_audio(plan,work,stop):
    """Join normalized PCM, then encode AAC once: no per-track AAC gaps."""
    joined=work/'playlist.pcm'; source=work/'track.pcm'; audio=work/'music.m4a'
    with joined.open('wb') as output:
        for track in plan['tracks']:
            if stop.is_set(): raise Cancelled()
            asset=track['asset']
            try:
                execute([binary('ffmpeg'),'-nostdin','-v','error','-xerror','-y','-err_detect','explode',
                         '-i',asset['path'],'-map','0:a:0','-vn','-ac','2','-ar',str(SAMPLE_RATE),
                         '-f','s16le',str(source)],stop,timeout=max(3600,asset['duration']*6+60))
                if source.stat().st_size!=track['samples']*4:
                    raise UserError('Musiqaning aniq uzunligi playlist rejasiga mos emas.')
            except (UserError,OSError) as e:
                check_storage_error(e)
                raise SourceError(asset,'music',str(e)) from e
            with source.open('rb') as incoming:
                while data:=incoming.read(1024*1024):
                    if stop.is_set(): raise Cancelled()
                    output.write(data)
            source.unlink()
    if joined.stat().st_size!=plan['music']['samples']*4:
        raise UserError('Playlist audiosini birlashtirish tekshiruvi o‘tmadi.')
    execute([binary('ffmpeg'),'-nostdin','-v','error','-xerror','-y','-f','s16le',
             '-ar',str(SAMPLE_RATE),'-ac','2','-i',str(joined),'-c:a','aac','-b:a','192k',str(audio)],
            stop,timeout=max(3600,plan['music']['duration']*6+60))
    if abs(probe(audio,'audio')['duration']-plan['music']['duration'])>.12:
        raise UserError('Birlashtirilgan playlist audiosining uzunligi mos emas.')
    joined.unlink()
    return audio

def render(plan,c,dest,enc,stop,progress):
    validate_plan(plan,c)
    output_filename=video_filename(plan)
    dest=Path(dest); dest.mkdir(parents=True,exist_ok=True)
    # A fresh work directory prevents a stale worker from sharing partial files.
    work=Path(tempfile.mkdtemp(prefix='_work_',dir=dest))
    fps=c['fps']; h=c['height']; w=h*16//9
    diagnostics=dest/'render_diagnostics.txt'
    device='cpu' if enc=='libx264' else 'gpu'
    budget=c.get('_render_budget') or render_budget(c,[device])['lanes'][device]
    workers=max(1,min(4,int(budget['segment_workers'])))
    threads=max(1,min(32,int(budget['encoder_threads'])))
    diagnostic_lock=threading.Lock()
    def record(text):
        with diagnostic_lock:
            with diagnostics.open('a',encoding='utf-8') as log: log.write(text+'\n')
    try:
        # Decode the full music before spending time on video segments.
        audio=work/'music.m4a'
        if plan.get('tracks'):
            audio=render_playlist_audio(plan,work,stop)
        else:
            try:
                execute([binary('ffmpeg'),'-nostdin','-v','error','-xerror','-y','-err_detect','explode',
                         '-i',plan['music']['path'],'-map','0:a:0','-vn','-c:a','aac','-b:a','192k',
                         '-t',str(plan['music']['duration']),str(audio)],stop)
                if abs(probe(audio,'audio')['duration']-plan['music']['duration'])>.12:
                    raise UserError('Musiqaning o‘qilgan uzunligi manba ma’lumotiga mos emas.')
            except (UserError,OSError) as e:
                check_storage_error(e)
                raise SourceError(plan['music'],'music',str(e)) from e
        if enc=='libx264':
            # Exercise the actual dimensions and CPU options before touching video 1.
            execute([binary('ffmpeg'),'-nostdin','-v','error','-filter_threads','2','-f','lavfi','-i',f'color=s={w}x{h}:r={fps}',
                     '-frames:v','3','-an','-pix_fmt','yuv420p']+encoding_args(enc,c['quality'],threads)+['-f','null','-'],stop,timeout=60)
        segments=plan['segments']; completed=set()
        record(f'Resurs: {c.get("resources","auto")} · {workers} parallel segment · {threads} kodlash oqimi · {enc}')
        local_stop=threading.Event()
        class SegmentStop:
            def is_set(self): return stop.is_set() or local_stop.is_set()
            def wait(self,seconds): return local_stop.wait(seconds) or stop.is_set()
        segment_stop=SegmentStop()
        def render_segment(i):
            s=segments[i]
            if segment_stop.is_set(): raise Cancelled()
            path=work/f'{i:05}.mp4'; duration=s['frames']/fps
            cmd=[binary('ffmpeg'),'-nostdin','-v','error','-xerror','-y','-err_detect','explode']
            cmd+=['-filter_threads',str(budget['filter_threads']),'-threads',str(budget['decode_threads'])]
            if s['source_start']: cmd+=['-ss',str(s['source_start'])]
            cmd+=['-i',s['asset']['path']]
            # At most one source-frame interval; never hide a truncated source by
            # freezing its final frame for the whole requested segment duration.
            source_rate=s['asset'].get('frame_rate') or fps
            padding=max(1,min(fps,math.ceil(fps/max(1,source_rate))))
            filters=f'setpts=PTS-STARTPTS,scale={w}:{h}:force_original_aspect_ratio=decrease:force_divisible_by=2,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps},tpad=stop_mode=clone:stop={padding},trim=end_frame={s["frames"]}'
            fx=effect_filters(s,fps,w,h,c.get('effect_strength','balanced'))
            filters+=','+','.join(fx+['format=yuv420p','setsar=1'])
            cmd+=['-map','0:v:0','-an','-sn','-dn','-vf',filters,'-frames:v',str(s['frames'])]+encoding_args(enc,c['quality'],threads)+['-video_track_timescale','90000',str(path)]
            for attempt in range(2 if enc=='libx264' else 1):
                try:
                    execute(cmd,segment_stop,timeout=max(120,min(3600,duration*30+60)))
                    check=probe(path,'video')
                    if abs(check['duration']-duration)>1/fps+.01 or (check['frames'] is not None and check['frames']!=s['frames']):
                        raise UserError('Segment davomiyligi yoki kadr soni rejaga mos emas.')
                    break
                except UserError as e:
                    check_storage_error(e)
                    record(f'Kodlovchi: {enc}\nSegment: {i+1}, {s["asset"]["name"]}\nUrinish: {attempt+1}\n{e}\n')
                    if enc!='libx264' or attempt==1:
                        verify_input(s['asset'],s['kind'],segment_stop)
                        if enc!='libx264': raise EncoderError(str(e)) from e
                        raise SourceError(s['asset'],s['kind'],'Manba render qilinmadi: '+str(e)) from e
                    # Same source, same interval, fewer threads; no skipped footage.
                    cmd=[*cmd]
                    for k,flag in enumerate(cmd[:-1]):
                        if flag in ('-threads','-filter_threads'): cmd[k+1]='1'
            return i
        def render_pending(count):
            local_stop.clear()
            remaining=iter(i for i in range(len(segments)) if i not in completed)
            with ThreadPoolExecutor(max_workers=count) as pool:
                active={pool.submit(render_segment,i) for i in [next(remaining,None) for _ in range(count)] if i is not None}
                try:
                    while active:
                        ready,active=wait(active,return_when=FIRST_COMPLETED)
                        for future in ready:
                            completed.add(future.result())
                            progress(sum(segments[i]['frames'] for i in completed)/plan['total_frames']*.94)
                            i=next(remaining,None)
                            if i is not None: active.add(pool.submit(render_segment,i))
                except BaseException:
                    local_stop.set()
                    for future in active: future.cancel()
                    raise
        try: render_pending(workers)
        except EncoderError:
            if enc=='libx264' or workers==1 or stop.is_set(): raise
            record('GPU parallel kodlashni bajara olmadi. Qolgan segmentlar bitta GPU oqimida qayta ishlanadi.')
            render_pending(1)
        # Relative numeric paths avoid quoting problems with arbitrary Windows directory names.
        listing=work/'concat.txt'; listing.write_text(''.join(f"file '{i:05}.mp4'\n" for i in range(len(segments))),encoding='utf-8')
        partial=dest/'video.partial.mp4'
        execute([binary('ffmpeg'),'-v','error','-xerror','-y','-f','concat','-safe','1','-i',str(listing),'-i',str(audio),'-map','0:v:0','-map','1:a:0','-c','copy','-t',str(plan['music']['duration']),'-movflags','+faststart',str(partial)],stop,timeout=86400)
        vid=probe(partial,'video'); aud=probe(partial,'audio')
        if abs(vid['duration']-plan['music']['duration'])>2/fps+.05 or abs(aud['duration']-plan['music']['duration'])>.1:
            raise UserError('Yakuniy audio/video davomiyligi tekshiruvi o‘tmadi.')
        os.replace(partial,dest/output_filename)
        (dest/'reja.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2),encoding='utf-8')
        write_report(plan,dest,plan.get('video_url',''))
        write_playlist(plan,dest)
        progress(1)
    except Exception as e:
        if not isinstance(e,Cancelled):
            with diagnostics.open('a',encoding='utf-8') as log: log.write(f'Yakuniy xato ({enc}): {e}\n')
        raise
    finally:
        shutil.rmtree(work,ignore_errors=True)
        (dest/'video.partial.mp4').unlink(missing_ok=True)
