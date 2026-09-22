'use strict';
const $=id=>document.getElementById(id),form=$('settings');
const labels={idle:'Yangi loyiha',planning:'Reja tuzilmoqda',ready:'Reja tayyor',running:'Jarayonda',stopping:'To‘xtatilmoqda',paused:'To‘xtatilgan',error:'Xatolik',completed:'Yakunlandi',pending:'Navbatda',done:'Tayyor'};
labels.completed_issues='Tayyor · muammolar qayd etilgan';
let token='',state=null,selected=null,lastList='',lastOptions='',lastReport='',lastLogs='',draftConfig='',dirty=false,linkDirty=false,toastTimer,showLimit=100,browsing=false,closed=false,issueLimit=100,lastIssues='';
const orderKeys=['playlist_first','playlist_second','playlist_third'];
// Replaced from /api/init so the page names this computer's launcher and encoder.
let platform={os:'windows',package:'Mustaqil Windows paketi',launcher:'MusicPro.exe',
 gpu_label:'GPU · videokarta',
 gpu_note:'Videokarta kodlovchisi amalda tekshiriladi. Mos videokarta drayveri kerak.'};
let musicList=[],musicListFolder='',musicLoading=false,musicRequest=0,musicTimer;
let videoPlaylists={},videoTarget=1,orderPage=0,lastTargets='';
const orderPageSize=10;
function node(tag,cls,text){const e=document.createElement(tag);if(cls)e.className=cls;if(text!==undefined)e.textContent=text;return e}
function icon(name){const s=document.createElementNS('http://www.w3.org/2000/svg','svg'),u=document.createElementNS(s.namespaceURI,'use');u.setAttribute('href','#i-'+name);s.append(u);return s}
function toast(message,error=false){$('toast-text').textContent=message;$('toast').hidden=false;$('toast').classList.toggle('error',error);clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('toast').hidden=true,9000)}
$('toast-close').onclick=()=>{$('toast').hidden=true};
function theme(value){document.documentElement.dataset.theme=value;try{localStorage.setItem('musicpro-theme',value)}catch{}}
try{theme(localStorage.getItem('musicpro-theme')||'dark')}catch{theme('dark')}
$('theme-btn').onclick=()=>theme(document.documentElement.dataset.theme==='light'?'dark':'light');
async function request(path,data={}){const r=await fetch('/api/'+path,{method:'POST',headers:{'Content-Type':'application/json','X-MusicPro-Token':token},body:JSON.stringify(data)});if(!r.ok){const d=await r.json();throw Error(d.error||'So‘rov bajarilmadi.')}return r}
async function api(path,data={}){return (await request(path,data)).json()}
function format(seconds){const s=Math.floor(seconds);return `${String(Math.floor(s/60)).padStart(2,'0')}:${String(s%60).padStart(2,'0')}`}
function formSignature(){return JSON.stringify({fields:[...form.elements].filter(e=>e.name&&(!['radio','checkbox'].includes(e.type)||e.checked)).map(e=>[e.name,e.value]),playlists:videoPlaylists})}
function formData(){const data=Object.fromEntries(new FormData(form));data.playlist_per_video=JSON.parse(JSON.stringify(videoPlaylists));data.playlist_order_enabled=false;return data}
function playlistSize(){return Math.max(1,Math.min(1000,Number(form.elements.playlist_count.value)||1))}
function videoEntry(){return videoPlaylists[String(videoTarget)]||{enabled:false,tracks:[]}}
function drawVideoTargets(){
 const count=Math.max(1,Math.min(10000,Number(form.elements.total.value)||1)),size=playlistSize();
 videoTarget=Math.min(videoTarget,count);
 const signature=JSON.stringify([count,size,videoPlaylists]);
 if(signature!==lastTargets){
  lastTargets=signature;const target=$('playlist-target');target.replaceChildren();
  for(let id=1;id<=count;id++){
   const entry=videoPlaylists[String(id)],chosen=entry?.enabled?(entry.tracks||[]).slice(0,size).filter(Boolean).length:0;
   const option=node('option','',id+'-video · '+(chosen?chosen+' ta tanlangan':'Random'));option.value=id;target.append(option);
  }
 }
 $('playlist-target').value=videoTarget;
}
function drawOrder(){
 const entry=videoEntry(),size=playlistSize();orderPage=Math.min(orderPage,Math.floor((size-1)/orderPageSize));
 $('order-toggle-label').textContent=videoTarget+'-video uchun musiqalarni tanlash';
 $('playlist-order-enabled').checked=!!entry.enabled;
 $('playlist-order-fields').hidden=!entry.enabled;
 const fields=$('playlist-slot-fields');fields.replaceChildren();
 const selected=(entry.tracks||[]).slice(0,size).filter(Boolean).length;
 $('playlist-order-note').textContent=entry.enabled
  ?videoTarget+'-video: '+selected+' / '+size+' ta musiqa tanlangan. Bo‘sh o‘rinlar random to‘ldiriladi. Boshqa video uchun yuqoridagi ro‘yxatdan video raqamini tanlang.'
  :videoTarget+'-video uchun musiqalarni dastur random tanlaydi. Boshqa videolarning tanlovlari saqlanadi.';
 if(!entry.enabled)return;
 const first=orderPage*orderPageSize,last=Math.min(size,first+orderPageSize);
 for(let index=first;index<last;index++){
  const label=node('label'),number=node('span','order-number',String(index+1).padStart(2,'0'));
  label.append(number,document.createTextNode((index+1)+'-musiqa'));
  const select=node('select');select.dataset.playlistSlot=index;select.setAttribute('aria-label',videoTarget+'-video, '+(index+1)+'-musiqa');
  const random=node('option','','Random tanlash');random.value='';select.append(random);
  const value=entry.tracks[index]||'';
  for(const music of musicList){const option=node('option','',music.name);option.value=music.path;option.disabled=(entry.tracks||[]).slice(0,size).some((path,i)=>i!==index&&path===music.path);select.append(option)}
  if(value&&!musicList.some(a=>a.path===value)){const option=node('option','',value.split(/[\\/]/).pop()+' · ro‘yxatda topilmadi');option.value=value;select.append(option)}
  select.value=value;
  select.onchange=()=>{const tracks=[...(videoEntry().tracks||[])];while(tracks.length<=index)tracks.push('');tracks[index]=select.value;while(tracks.length&&!tracks[tracks.length-1])tracks.pop();videoPlaylists[String(videoTarget)]={enabled:true,tracks}};
  label.append(select);fields.append(label);
 }
 $('order-pagination').hidden=size<=orderPageSize;
 $('order-page-label').textContent=(first+1)+'–'+last+' / '+size;
}
function fillMusicChoices(){drawOrder()}
function orderControls(busy){
 const active=form.elements.music_mode.value==='playlist'&&videoEntry().enabled;
 for(const select of $('playlist-slot-fields').querySelectorAll('select'))select.disabled=busy||musicLoading||!active;
 $('refresh-music').disabled=busy||musicLoading||!active;
 $('order-prev').disabled=busy||musicLoading||orderPage===0;
 $('order-next').disabled=busy||musicLoading||(orderPage+1)*orderPageSize>=playlistSize();
}
async function loadMusic(silent=false){
 const folder=form.elements.music.value.trim(),id=++musicRequest;
 if(!folder){musicList=[];musicListFolder='';musicLoading=false;fillMusicChoices();$('music-list-note').textContent='Avval Musikalar papkasini tanlang.';controls();return}
 musicLoading=true;controls();$('music-list-note').textContent='Musiqalar ro‘yxati o‘qilmoqda…';
 try{
  const d=await api('music-list',{music:folder});
  if(id!==musicRequest||folder!==form.elements.music.value.trim())return;
  musicList=d.files;musicListFolder=folder;fillMusicChoices();
  $('music-list-note').textContent=d.files.length+' ta musiqa. Tanlanmagan o‘rinlar random to‘ldiriladi.';
 }catch(e){if(id!==musicRequest)return;musicList=[];musicListFolder='';fillMusicChoices();$('music-list-note').textContent=e.message;if(!silent)toast(e.message,true)}
 finally{if(id===musicRequest){musicLoading=false;controls()}}
}
function optionsChanged(){
 const playlist=form.elements.music_mode.value==='playlist';
 $('playlist-settings').hidden=!playlist;
 $('playlist-order').hidden=!playlist;
 drawVideoTargets();drawOrder();
 if(!playlist&&!form.elements.playlist_count.value)form.elements.playlist_count.value='5';
 $('music-distribution-note').textContent=playlist?'Har video tanlangan miqdordagi musiqalardan tuziladi.':'Musiqalar orasida teng taqsimlanadi.';
 $('beat-settings').hidden=form.elements.mode.value!=='beat';
 $('summary-total').textContent=(form.elements.total.value||0)+' ta video';
 $('summary-format').textContent=form.elements.height.value+'p / '+form.elements.fps.value+' FPS';
 const d=form.elements.device.value;
 $('device-note').textContent=d==='cpu'?'Protsessor orqali render. Ish boshlanishidan oldin kodlash tekshiriladi.':d==='gpu'?platform.gpu_note:'CPU va GPU umumiy navbatdan ishlaydi: bo‘shagan qurilma navbatdagi boshlanmagan videoni oladi. Boshlangan video o‘z qurilmasida tugaydi. RAM yetarli bo‘lsa kamida 2 video parallel tayyorlanadi.';
 const resources=form.elements.resources.value;
 $('resource-note').textContent={auto:'CPU limiti boshqa dasturlar yukiga qarab 15–60% oralig‘ida moslashadi. Render pastroq ustuvorlikda ishlaydi.',medium:'CPU uchun 60% yuqori chegara. RAM yetarli bo‘lsa 2 tagacha segment bir vaqtda tayyorlanadi.',high:'CPU uchun 85% yuqori chegara. CPUda 4 tagacha, GPUda 3 tagacha parallel segment; RAM va yadrolar hisobga olinadi.'}[resources];
 const effect=form.elements.effects.value;
 $('effect-note').textContent={off:'Effektlar o‘chirilgan.',edit:'Zoom, shake, vibratsiya va yon harakat navbat bilan qo‘llanadi.',all:'Zoom, shake, vibratsiya, whip, RGB va blur kuchli urg‘ularda navbat bilan qo‘llanadi. Har to‘liq davrda olti tur ishlatiladi; qisqa videoda mos urg‘ular kam bo‘lsa, hammasi sig‘masligi mumkin.',zoom:'Kuchli urg‘uda tez yaqinlashish.',shake:'Kuchli urg‘uda qisqa kamera silkinishi.',vibration:'Kuchli urg‘uda qisqa, tez tebranish.',whip:'Kuchli urg‘uda tasvirning yon tomonga harakati.',rgb:'Kuchli urg‘uda qisqa rang ajralishi.',blur:'Kuchli urg‘uda qisqa xiralashib ochilish.'}[effect]+(effect!=='off'?(form.elements.mode.value==='beat'?' Faqat kuchli urg‘uga mos kadr chegaralarida; qolgan almashishlar effektsiz.':' Tasodifiy bo‘lak chegarasi kuchli urg‘uga mos tushsagina effekt ishlaydi. Ko‘proq mos almashish uchun Musiqaga mos rejimini tanlang.'):'');
 dirty=!!draftConfig&&formSignature()!==draftConfig;$('dirty-note').hidden=!dirty;controls();
}
form.addEventListener('input',event=>{
 // These editors commit in their target change handler before the form redraws.
 if(['playlist-target','playlist-order-enabled'].includes(event.target.id)||event.target.dataset.playlistSlot!==undefined)return;
 optionsChanged();
});form.addEventListener('change',optionsChanged);
function controls(){const busy=!!state?.busy;for(const e of form.elements)e.disabled=busy||browsing;
 orderControls(busy||browsing);
 $('plan-btn').disabled=busy||browsing||musicLoading;$('stop-btn').disabled=!busy||state?.status==='stopping';
 const jobs=state?.jobs||[];$('run-btn').disabled=busy||dirty||!jobs.length||jobs.every(j=>j.status==='done');
 $('run-btn').querySelector('span').textContent=['paused','error'].includes(state?.status)?'Davom ettirish':'Montajni boshlash';
 $('open-btn').disabled=!state?.config?.output;$('exit-btn').disabled=busy||browsing||closed;
}
function chosenJob(){return state?.jobs.find(j=>j.id===selected)}
function setSelected(id,scroll=false){selected=Number(id)||null;linkDirty=false;lastReport='';$('report-job').value=selected||'';drawReport();if(scroll)$('reports').scrollIntoView({behavior:'smooth',block:'start'})}
function drawJobs(){
 if(!state)return;const query=$('search-jobs').value.toLocaleLowerCase(),status=$('status-filter').value;
 const jobs=state.jobs.filter(j=>(j.music+' '+(j.playlist_text||'')).toLocaleLowerCase().includes(query)&&(status==='all'||j.status===status));
 const shown=jobs.slice(0,showLimit),sig=JSON.stringify(shown.map(j=>[j.id,j.music,j.status,j.device,j.duration,j.error,j.warning_count,j.effect_count,j.music_count]));
 if(sig!==lastList){lastList=sig;const box=$('jobs');box.replaceChildren();
  if(!shown.length){const empty=node('div','empty');empty.append(node('span','','▷'),node('h3','',state.jobs.length?'Mos video topilmadi':'Birinchi montajni tayyorlang'),node('p','',state.jobs.length?'Qidiruv yoki holat filtrini o‘zgartiring.':'Papkalarni tanlab, “Tekshirish va reja tuzish” tugmasini bosing.'));box.append(empty)}
  for(const j of shown){const row=node('button','job-row');row.type='button';row.dataset.id=j.id;row.title=j.error||'Litsenlar jadvalini ko‘rish';row.setAttribute('aria-label',`${j.id}. ${j.music} — ${labels[j.status]}`);
   const thumb=node('span','job-thumb');thumb.append(icon(j.status==='done'?'check':'play'));const copy=node('span','job-copy');copy.append(node('strong','',j.music),node('small','',`${format(j.duration)} · ${j.device==='auto'?'Umumiy navbat':j.device.toUpperCase()} · ${j.music_count||1} ta musiqa · ${j.licenses.length} ta litsen · ${j.effect_count||0} ta effekt${j.warning_count?' · '+j.warning_count+' ta qayd':''}`));
   const track=node('span','job-progress');track.append(node('i'));const badge=node('span','job-badge',labels[j.status]||j.status);badge.dataset.status=j.status;
   row.append(node('span','job-index',String(j.id).padStart(2,'0')),thumb,copy,track,node('span','job-value'),badge,node('span','job-arrow','↗'));row.onclick=()=>setSelected(j.id,true);box.append(row);
  }
 }
 for(const j of shown){const row=$('jobs').querySelector(`[data-id="${j.id}"]`);if(!row)continue;row.querySelector('.job-value').textContent=Math.round(j.progress*100)+'%';row.querySelector('.job-progress i').style.width=(j.progress*100)+'%'}
 $('more-jobs').hidden=jobs.length<=showLimit;
}
function drawReport(){
 const j=chosenJob();$('report-content').hidden=!j;$('report-empty').hidden=!!j;if(!j)return;
 const sig=JSON.stringify([j.id,j.status,j.music,j.video_url,j.report_ready,j.report_rows,j.error,j.effect_count,j.strong_accents,j.playlist_text,j.playlist_ready,j.output_name,j.video_filename]);if(sig===lastReport)return;lastReport=sig;
 $('output-name-note').textContent=j.output_name?'Papka: '+j.output_name+' · Video: '+j.video_filename:'';
 $('playlist-report').hidden=!j.playlist_text;
 $('playlist-preview').textContent=j.playlist_text||'';
 $('download-playlist').hidden=!(j.playlist_ready&&j.status==='done');
 $('download-playlist').href='/api/playlist/'+j.id;
 $('playlist-report-note').textContent=j.status==='done'?'TXT yakuniy videodagi musiqa ketma-ketligiga mos.':'Bu rejalashtirilgan ketma-ketlik. Yakuniy TXT video tayyor bo‘lgach ochiladi.';
 $('report-title').textContent=j.music;$('report-count').textContent=j.licenses.length+' ta litsen';$('report-duration').textContent=format(j.duration);
 $('accent-note').textContent=`${j.strong_accents||0} ta kuchli urg‘u · ${j.effect_count||0} ta effekt. Litsenlar effektsiz.`;
 if(!linkDirty)$('report-url').value=j.video_url||'';
 $('save-report').disabled=j.status!=='done';$('report-url').disabled=j.status!=='done';
 $('download-report').hidden=!(j.report_ready&&j.status==='done');$('download-report').href='/api/report/'+j.id;
 $('report-note').textContent=j.status==='done'?"Havola kiritilmasa, “VIDEO LINKI NI QO'YING” yoziladi. Havolani kiritgach, Excelni saqlang.":j.status==='error'?`Montaj tugamagan. Jadval rejani ko‘rsatadi. Xato: ${j.error}`:'Bu montaj rejasidagi vaqtlar. Video tayyor bo‘lgach, Excelni yuklab olishingiz mumkin.';
 const bar=$('timeline');bar.replaceChildren();let end=0;for(const l of j.licenses){const clip=node('span','clip');clip.style.width=(Math.max(0,l.start-end)/j.duration*100)+'%';const lic=node('span','license');lic.style.width=((l.end-l.start)/j.duration*100)+'%';lic.title=`${l.name}: ${format(l.start)}–${format(l.end)}`;bar.append(clip,lic);end=l.end}const tail=node('span','clip');tail.style.flex='1';bar.append(tail);
 const rows=$('report-rows');rows.replaceChildren();for(const values of j.report_rows||[]){const tr=node('tr');for(const v of values)tr.append(node('td','',v));rows.append(tr)}
 if(!j.report_rows?.length){const tr=node('tr'),td=node('td','','Litsen video ishlatilmagan. Excelda faqat ustun sarlavhalari bo‘ladi.');td.colSpan=4;tr.append(td);rows.append(tr)}
}
function drawIssues(){
 const all=state?.issues||[],query=$('issue-search').value.toLocaleLowerCase(),role=$('issue-filter').value;
 const matching=all.filter(r=>(role==='all'||r.role===role)&&[r.name,r.path,r.reason,r.action].join(' ').toLocaleLowerCase().includes(query));
 const shown=matching.slice(0,issueLimit),sig=JSON.stringify([shown,issueLimit]);
 $('issue-count').textContent=all.length;$('nav-issues').textContent=all.length;$('issues-empty').hidden=!!matching.length;$('more-issues').hidden=matching.length<=issueLimit;
 if(sig===lastIssues)return;lastIssues=sig;const rows=$('issue-rows');rows.replaceChildren();
 const roles={clip:'Bo‘lak',license:'Litsen',music:'Musiqa',device:'Qurilma',render:'Render / saqlash'};
 for(const r of shown){const tr=node('tr'),source=node('td'),reason=node('td');source.append(node('b','',r.name),node('small','',roles[r.role]||r.role),node('small','issue-path',r.path));reason.append(node('span','',r.reason),node('b','issue-action',r.action));tr.append(source,reason,node('td','',r.jobs.join(', ')||'Tekshirishda'));rows.append(tr)}
}
function render(){
 const s=state,jobs=s.jobs||[],done=jobs.filter(j=>j.status==='done').length,errors=jobs.filter(j=>j.status==='error').length;
 const p=jobs.length?Math.round(jobs.reduce((a,j)=>a+j.progress,0)/jobs.length*100):0;
 $('state-badge').textContent=labels[s.status]||s.status;$('state-badge').dataset.status=s.status;
 $('count').replaceChildren(document.createTextNode(done+' '),node('span','','/ '+jobs.length));$('percent').replaceChildren(document.createTextNode(String(p)),node('span','','%'));
 $('music-count').textContent=s.summary?.music||'—';$('error-count').textContent=errors;$('nav-count').textContent=jobs.length;$('progress').style.width=p+'%';$('message').textContent=s.message;
 $('persistence-warning').hidden=!s.persistence_warning;$('persistence-warning').textContent=s.persistence_warning||'';
 controls();drawJobs();drawIssues();const optionSig=JSON.stringify(jobs.map(j=>[j.id,j.music]));
 if(optionSig!==lastOptions){lastOptions=optionSig;const select=$('report-job');select.replaceChildren();if(!jobs.length)select.append(node('option','','Avval montaj rejasini tuzing'));
  for(const j of jobs){const o=node('option','',String(j.id).padStart(2,'0')+' · '+j.music);o.value=j.id;select.append(o)}
  if(!jobs.some(j=>j.id===selected))setSelected(jobs[0]?.id);else select.value=selected;
 }drawReport();
 const logSig=JSON.stringify(s.logs||[]);if(logSig!==lastLogs){lastLogs=logSig;const logs=$('logs');logs.replaceChildren();for(const l of(s.logs||[]).slice().reverse()){const r=node('div','log-row');r.append(node('time','',l.time),node('span','',l.message));logs.append(r)}if(!s.logs?.length)logs.textContent='Hozircha yangi hodisa yo‘q.'}
}
async function refresh(){if(closed)return;try{const r=await fetch('/api/state');if(!r.ok)throw Error();const next=await r.json();if(closed)return;state=next;$('connection').classList.remove('offline');$('connection').replaceChildren(node('i'),document.createTextNode(' Ulangan'));render()}catch{if(closed)return;$('connection').classList.add('offline');$('connection').textContent='Aloqa yo‘q';$('message').textContent='Dastur bilan aloqa uzildi. '+platform.launcher+' ni qayta oching.'}}
async function poll(){if(closed)return;await refresh();if(!closed)setTimeout(poll,1400)}
form.addEventListener('submit',async e=>{e.preventDefault();const data=formData();$('plan-btn').disabled=true;try{await api('plan',data);draftConfig=formSignature();dirty=false;$('dirty-note').hidden=true;await refresh();$('queue').scrollIntoView({behavior:'smooth'})}catch(e){toast(e.message,true);controls()}});
for(const b of document.querySelectorAll('[data-browse]'))b.onclick=async()=>{browsing=true;controls();try{const d=await api('browse');if(d.path){$(b.dataset.browse).value=d.path;if(b.dataset.browse==='music')await loadMusic(true)}optionsChanged()}catch(e){toast(e.message,true)}finally{browsing=false;controls()}};
$('refresh-music').onclick=()=>loadMusic();
$('playlist-order-enabled').addEventListener('change',()=>{
 videoPlaylists[String(videoTarget)]={enabled:$('playlist-order-enabled').checked,tracks:[...(videoEntry().tracks||[])]};
 optionsChanged();if(videoEntry().enabled&&musicListFolder!==form.elements.music.value.trim())loadMusic(true);
});
$('playlist-target').onchange=()=>{videoTarget=Number($('playlist-target').value)||1;orderPage=0;drawOrder();controls();if(videoEntry().enabled&&musicListFolder!==form.elements.music.value.trim())loadMusic(true)};
$('order-prev').onclick=()=>{orderPage=Math.max(0,orderPage-1);drawOrder();controls()};
$('order-next').onclick=()=>{orderPage++;drawOrder();controls()};
for(const radio of form.elements.music_mode)radio.addEventListener('change',()=>{if(radio.value==='playlist'&&radio.checked&&videoEntry().enabled&&musicListFolder!==form.elements.music.value.trim())loadMusic(true)});
$('music').addEventListener('input',()=>{musicRequest++;musicLoading=false;musicListFolder='';clearTimeout(musicTimer);if(form.elements.music_mode.value==='playlist'&&$('playlist-order-enabled').checked)musicTimer=setTimeout(()=>loadMusic(true),500)});
$('run-btn').onclick=async()=>{try{await api('run');await refresh()}catch(e){toast(e.message,true)}};
$('stop-btn').onclick=async()=>{try{await api('stop');await refresh()}catch(e){toast(e.message,true)}};
$('open-btn').onclick=async()=>{try{await api('open')}catch(e){toast(e.message,true)}};
$('exit-btn').onclick=async()=>{if(!confirm('MusicPro yopilsinmi? Tayyor natijalar va navbat saqlanadi.'))return;try{await api('shutdown');closed=true;for(const e of document.querySelectorAll('button,input,select'))e.disabled=true;$('connection').textContent='Yopildi';$('message').textContent='MusicPro yopildi. Brauzer oynasini yopishingiz mumkin.';toast('Dastur yopildi. Qayta ochish uchun '+platform.launcher+' ni bosing.')}catch(e){toast(e.message,true)}};
$('search-jobs').oninput=()=>{showLimit=100;drawJobs()};$('status-filter').onchange=()=>{showLimit=100;drawJobs()};$('more-jobs').onclick=()=>{showLimit+=100;drawJobs()};
 $('issue-search').oninput=()=>{issueLimit=100;drawIssues()};$('issue-filter').onchange=()=>{issueLimit=100;drawIssues()};$('more-issues').onclick=()=>{issueLimit+=100;drawIssues()};
$('report-job').onchange=()=>setSelected($('report-job').value);
$('report-url').oninput=()=>{linkDirty=true};
$('save-report').onclick=async()=>{const id=selected;$('save-report').disabled=true;try{await api('report',{id,video_url:$('report-url').value});linkDirty=false;lastReport='';await refresh();toast('Excel hisoboti saqlandi. Video qayta render qilinmadi.')}catch(e){toast(e.message,true);$('save-report').disabled=false}};
$('convert-btn').onclick=async()=>{const f=$('legacy-file').files[0];if(!f)return toast('Avval TXT hisobotni tanlang.',true);if(f.size>1900000)return toast('TXT fayl 1.9 MB dan kichik bo‘lsin.',true);$('convert-btn').disabled=true;try{const response=await request('convert',{text:await f.text(),video_url:$('legacy-url').value});const url=URL.createObjectURL(await response.blob()),a=node('a');a.href=url;a.download='Litsen_video_malumot.xlsx';a.click();setTimeout(()=>URL.revokeObjectURL(url),5000);toast('Excel hisoboti tayyor.')}catch(e){toast(e.message,true)}finally{$('convert-btn').disabled=false}};
for(const a of document.querySelectorAll('nav a'))a.onclick=()=>{document.querySelector('nav a.active')?.classList.remove('active');a.classList.add('active')};
(async()=>{try{
 const r=await fetch('/api/init'),d=await r.json();token=d.token;
 if(d.platform){
  platform={...platform,...d.platform};
  $('package-note').textContent=platform.package;
  const gpu=form.elements.device.querySelector('option[value="gpu"]');
  if(gpu)gpu.textContent=platform.gpu_label;
 }
 for(const[k,v]of Object.entries(d.config)){
  const field=form.elements.namedItem(k);if(!field)continue;
  field.value=String(k==='effects'&&['flash','black'].includes(v)?'edit':v);
 }
 if(d.config.playlist_per_video)videoPlaylists=JSON.parse(JSON.stringify(d.config.playlist_per_video));
 else if([true,1,'1','true','on'].includes(d.config.playlist_order_enabled)){
  const tracks=orderKeys.map(key=>d.config[key]||'');
  for(let id=1;id<=Math.min(10000,Number(d.config.total)||10);id++)videoPlaylists[String(id)]={enabled:true,tracks:[...tracks]};
 }
 draftConfig=formSignature();optionsChanged();
 if(form.elements.music_mode.value==='playlist'&&videoEntry().enabled)await loadMusic(true);
 poll();
}catch{toast('Dasturga ulanib bo‘lmadi. Sahifani yangilang.',true)}})();
