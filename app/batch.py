"""Unattended batch recovery with a shared, persisted source exclusion list.

Only identified source failures exclude files. GPU/system failures never
quarantine healthy inputs. Replanning preserves licensing and beat constraints.
Every retry consumes a new source exclusion or a bounded system retry.
"""
from __future__ import annotations
import csv
import io
import json
import os
import random
import threading
import time
from pathlib import Path
from engine import scan, analyze_music, analyze_playlist_music, plan_one, fingerprint, validate_plan
from playlist import audio_assets, compose, order_slots, select_tracks
from output_names import prepare_output, music_title
from failures import *

ROLES = {'clip': 'clips', 'license': 'licenses', 'music': 'music'}


def issue_csv(issues):
    stream = io.StringIO(newline='')
    writer = csv.writer(stream)
    writer.writerow(['vaqt','turi','fayl','manzil','sabab','amal','natija_raqamlari'])
    def literal(value):
        value = str(value)
        return "'"+value if value.startswith(('=','+','-','@')) else value
    for row in issues:
        writer.writerow([literal(v) for v in [row['time'], row['role'], row['name'], row['path'],
                         row['reason'], row['action'], ', '.join(map(str,row['jobs']))]])
    return ('\ufeff'+stream.getvalue()).encode('utf-8')


class BatchRecovery:
    def __init__(self, config, state, state_lock, stop, save, log):
        self.c = config; self.state = state; self.state_lock = state_lock
        self.stop = stop; self.save = save; self.log = log
        self.lock = threading.RLock()
        self.rng = random.SystemRandom()
        self.state.setdefault('issues', [])
        self.state.setdefault('blocked', {role: [] for role in ROLES})
        self.state.setdefault('analysis', {})
        self.catalog = state.get('catalog', {})
        self.history = set()
        history_file = Path(config['output'])/'.musicpro_history.json'
        if history_file.exists():
            self.history = set(json.loads(history_file.read_text(encoding='utf-8')))
        self.rejected = set()

    def issue(self, role, asset, reason, job=None, action='Ishlatilmadi; muqobil manba tanlanadi'):
        with self.state_lock:
            path = asset.get('path',''); name = asset.get('name',path)
            row = next((r for r in self.state['issues'] if r['role']==role and r['path']==path and r['action']==action),None)
            fresh = row is None
            if fresh:
                row = dict(time=time.strftime('%Y-%m-%d %H:%M:%S'),role=role,name=name,path=path,
                           reason=str(reason)[-2000:],action=action,jobs=[])
                self.state['issues'].append(row)
            if job and job['id'] not in row['jobs']: row['jobs'].append(job['id'])
            if job: job['warning_count'] = sum(job['id'] in r['jobs'] for r in self.state['issues'])
            self.save()
        if fresh: self.log(f'{name}: {action}. {str(reason)[-350:]}')

    def exclude(self, role, asset, reason, job=None):
        with self.lock:
            with self.state_lock:
                blocked = self.state['blocked'].setdefault(role,[])
                if asset['path'] not in blocked: blocked.append(asset['path'])
            self.issue(role,asset,reason,job)

    def available(self, role):
        blocked = set(self.state['blocked'].get(role,[]))
        return [a for a in self.catalog.get(role,[]) if a['path'] not in blocked]

    def load_catalog(self):
        with self.lock:
            self.catalog = {}
            for role, field in ROLES.items():
                if role=='license' and not self.c['license_count']:
                    self.catalog[role]=[]; continue
                try:
                    assets = scan(self.c[field], 'audio' if role=='music' else 'video',
                                  lambda a,e,r=role:self.exclude(r,a,e),self.stop)
                except UserError as e:
                    self.issue(role,{'path':self.c[field],'name':Path(self.c[field]).name},str(e))
                    assets=[]
                if role=='license':
                    for a in assets:
                        if a['duration'] < 5: self.exclude(role,a,'5 soniyadan qisqa litsen manba.')
                self.catalog[role]=assets
            with self.state_lock: self.state['catalog']=self.catalog; self.save()

    def music_analysis(self, asset, job):
        playlist = self.c.get('music_mode','single')=='playlist'
        key = json.dumps([asset['path'],asset['size'],asset['mtime']]+(['playlist48-v1'] if playlist else []))
        if key not in self.state['analysis']:
            try:
                analysis = (analyze_playlist_music if playlist else analyze_music)(asset['path'],self.stop)
                if abs(analysis['decoded_duration']-asset['duration']) > max(.15,asset['duration']*.002):
                    raise UserError('Musiqa to‘liq o‘qilmadi; davomiylik ma’lumotiga mos emas.')
            except (UserError,OSError) as e:
                check_storage_error(e)
                self.exclude('music',asset,str(e),job)
                raise SourceError(asset,'music',str(e)) from e
            with self.state_lock: self.state['analysis'][key]=analysis; self.save()
        return self.state['analysis'][key]

    def prepare(self, job, preferred=None):
        # Serializes source-pool and uniqueness decisions, not running renders.
        with self.lock:
            if self.stop.is_set(): raise Cancelled()
            clips = self.available('clip'); licenses = self.available('license')
            if not clips: raise UserError('Yaroqli oddiy bo‘lak qolmadi.')
            if self.c['license_count'] and not licenses: raise UserError('Yaroqli, kamida 5 soniyali litsen manba qolmadi.')
            if self.c.get('music_mode','single')=='playlist':
                return self.prepare_playlist(job,clips,licenses)
            music = self.available('music'); self.rng.shuffle(music)
            with self.state_lock:
                others = [j for j in self.state['jobs'] if j['id']!=job['id'] and j.get('plan')]
                usage = {a['path']:sum(j['plan']['music']['path']==a['path'] for j in others) for a in music}
                seen = self.history | {fingerprint(j['plan']) for j in others}
            music.sort(key=lambda a:(a['path']!=preferred,usage[a['path']]))
            pool = tuple(sorted(a['path'] for a in clips+licenses))
            for asset in music:
                if self.stop.is_set(): raise Cancelled()
                if (asset['path'],pool) in self.rejected: continue
                try: analysis = self.music_analysis(asset,job)
                except SourceError: continue
                reason = 'Yangi unikal variantlar yetarli emas.'
                for _ in range(128):
                    try: plan = plan_one(clips,licenses,asset,self.c,self.rng.randrange(2**63),analysis)
                    except UserError as e: reason=str(e); break
                    if fingerprint(plan) not in seen:
                        with self.state_lock:
                            prepare_output(job,plan,self.c,self.state['batch'])
                            job.update(plan=plan,music=asset['name'],progress=0)
                            self.save()
                        return plan
                self.rejected.add((asset['path'],pool))
                self.issue('music',asset,reason,job,'Bu parametrlar uchun boshqa musiqa tanlanadi')
            raise UserError('Qolgan musiqalar bilan talabga mos unikal reja tuzib bo‘lmadi. Yaroqli manbalar yoki variantlar tugadi.')

    def prepare_playlist(self,job,clips,licenses):
        """Called under the planning lock; keep healthy tracks during recovery."""
        count=self.c.get('playlist_count',5)
        with self.state_lock:
            others=[j for j in self.state['jobs'] if j['id']!=job['id'] and j.get('plan')]
            seen=self.history|{fingerprint(j['plan']) for j in others}
        preferred=job.get('plan',{}).get('tracks',[])
        slots=order_slots(self.c,job['id'])
        reason='Yangi unikal playlist varianti topilmadi.'
        limit=128+len(self.catalog.get('music',[]))
        for attempt in range(limit):
            if self.stop.is_set(): raise Cancelled()
            pool=self.available('music')
            if len(pool)<count:
                raise UserError(f'Playlist uchun {count} ta turli yaroqli musiqa kerak; hozir {len(pool)} ta mavjud. '
                                'Musiqa qo‘shing yoki har playlistdagi musiqa sonini kamaytiring.')
            selected,fallbacks=select_tracks(pool,count,self.rng,slots,preferred,
                                             longest=attempt==1 and not preferred)
            for index,path in fallbacks.items():
                self.issue('music',{'path':path,'name':Path(path).name},
                           'Tanlangan musiqa mavjud emas yoki shu navbatda yaroqsiz deb topilgan.',
                           job,f'{int(index)+1}-o‘rin boshqa yaroqli musiqa bilan avtomatik to‘ldiriladi')
            try:
                analyses=[self.music_analysis(a,job) for a in selected]
            except SourceError:
                # Preserve all healthy positions while a rejected track is replaced.
                preferred=[{'asset':a} for a in selected]
                continue
            music,tracks,analysis=compose(selected,analyses)
            try:
                plan=plan_one(clips,licenses,music,self.c,self.rng.randrange(2**63),analysis)
                plan.update(plan_version=5,tracks=tracks,playlist_order_fallbacks=fallbacks,playlist_job_id=job['id'])
                validate_plan(plan,self.c)
            except UserError as e:
                reason=str(e); preferred=[]; continue
            if fingerprint(plan) in seen:
                preferred=[]; continue
            with self.state_lock:
                prepare_output(job,plan,self.c,self.state['batch'])
                job.update(plan=plan,music=music_title(plan)+f' · Playlist ({count})',progress=0)
                self.save()
            return plan
        raise UserError('Mavjud musiqalar bilan talabga mos unikal playlist tuzilmadi. '+reason)

    def plan_current(self, job):
        plan = job.get('plan')
        if not plan: return False
        if 'playlist_per_video' in self.c and plan.get('tracks') and plan.get('playlist_job_id')!=job['id']:
            return False
        try: validate_plan(plan,self.c)
        except UserError: return False
        with self.lock:
            if plan.get('tracks'):
                healthy={a['path'] for a in self.available('music')}
                if any(path in healthy and plan['tracks'][index]['asset']['path']!=path
                       for index,path in order_slots(self.c,job['id']).items()):
                    return False
            seen=set(); valid=True
            for role,asset in [('music',a) for a in audio_assets(plan)]+[(s['kind'],s['asset']) for s in plan['segments']]:
                if (role,asset['path']) in seen: continue
                seen.add((role,asset['path']))
                if asset['path'] in self.state['blocked'].get(role,[]):
                    self.issue(role,asset,'Avval shu navbatda muammo aniqlangan.',job); valid=False; continue
                try:
                    stat = Path(asset['path']).stat()
                    if stat.st_size!=asset['size'] or stat.st_mtime_ns!=asset['mtime']:
                        raise OSError('Fayl reja tuzilgandan keyin o‘zgargan.')
                except OSError as e:
                    self.exclude(role,asset,str(e),job); valid=False
            return valid

    def run_job(self, job, render, config):
        limit = sum(len(a) for a in self.catalog.values())+4
        system_retries = 0
        for attempt in range(limit):
            if self.stop.is_set(): raise Cancelled()
            if not self.plan_current(job):
                preferred=job.get('plan',{}).get('music',{}).get('path')
                self.prepare(job,preferred)
            with self.state_lock:
                prepare_output(job,job['plan'],self.c,self.state['batch'])
                job.update(attempt=attempt+1,progress=0,status='running',error=''); self.save()
            try:
                render(job,config)
                return
            except SourceError as e:
                self.exclude(e.role,e.asset,e.reason,job)
                self.log(f'{job["id"]}-video: muammoli manba almashtirilmoqda; montaj avtomatik davom etadi.')
            except EncoderError as e:
                if job['encoder']=='libx264': raise
                self.issue('device',{'path':'GPU','name':'GPU kodlovchi'},str(e),job,'CPU orqali qayta tayyorlanadi')
                with self.state_lock: job.update(encoder='libx264',device='cpu'); self.save()
                config={**config,'_render_budget':{**config['_render_budget'],'segment_workers':1}}
            except StorageError: raise
            except UserError as e:
                if system_retries>=1: raise
                system_retries+=1
                self.issue('render',{'path':job['dest'],'name':f'{job["id"]}-video'},str(e),job,'Alohida render jarayoni bir marta qayta ishga tushiriladi')
        raise UserError('Mavjud muqobil manbalar bilan tiklash urinishlari tugadi.')

    def completed(self, job):
        with self.lock:
            self.history.add(fingerprint(job['plan']))
            history=Path(self.c['output'])/'.musicpro_history.json'; temp=history.with_suffix('.tmp')
            try:
                temp.write_text(json.dumps(sorted(self.history)),encoding='utf-8'); os.replace(temp,history)
            except OSError as e:
                self.issue('render',{'path':str(history),'name':'Unikallik tarixi'},str(e),job,
                           'Video tayyor; tarix shu jarayon xotirasida saqlanadi, diskka yozilmadi')

    def save_issues(self):
        with self.state_lock: data=issue_csv(self.state['issues'])
        path=Path(self.c['output'])/f'MusicPro_{self.state["batch"]}_muammolar.csv'
        try:
            path.write_bytes(data)
            with self.state_lock: self.state['issues_path']=str(path); self.save()
        except OSError as e:
            self.log(f'Muammolar ro‘yxati dasturda saqlandi; CSV yozilmadi: {e}')
