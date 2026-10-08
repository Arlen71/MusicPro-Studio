'use strict';
// Online studio: turns the desktop page's folder pickers into uploads and
// downloads, served by cloud/gateway.py. Runs after studio.js and reuses its
// globals (state, chosenJob, loadMusic, toast); studio.js itself is unchanged.
(function(){
const ACCEPT={clips:'video/*,.mkv,.mts,.m4v',licenses:'video/*,.mkv,.mts,.m4v',music:'audio/*,.flac,.opus,.wma,.m4a'};
const LABEL={clips:'bo‘lak',licenses:'litsen video',music:'musiqa'};
let info=null,lastStatus='',uploading=0;
const el=(tag,cls,text)=>{const e=document.createElement(tag);if(cls)e.className=cls;if(text!==undefined)e.textContent=text;return e};
const size=b=>b>=1073741824?(b/1073741824).toFixed(2)+' GB':b>=1048576?(b/1048576).toFixed(1)+' MB':Math.max(1,Math.round(b/1024))+' KB';
const enc=s=>s.split('/').map(encodeURIComponent).join('/');
const say=(m,e)=>typeof toast==='function'?toast(m,e):alert(m);

async function call(method,url,body){
 const r=await fetch(url,{method,body,credentials:'same-origin'});
 if(r.status===401){location.href='/login';throw Error('Sessiya tugagan.')}
 const d=await r.json().catch(()=>({}));if(!r.ok)throw Error(d.error||'So‘rov bajarilmadi.');return d;
}

// --- top bar: account and logout instead of "close the program"
const exit=document.getElementById('exit-btn');
if(exit){const out=exit.cloneNode(true);out.textContent='Chiqish';out.disabled=false;out.title='Hisobdan chiqish';
 out.onclick=async()=>{await fetch('/auth/logout',{method:'POST',credentials:'same-origin'});location.href='/'};
 exit.replaceWith(out);
 const who=el('span','cloud-user');who.id='cloud-user';out.before(who);}
const openBtn=document.getElementById('open-btn');if(openBtn)openBtn.hidden=true;
const tag=document.querySelector('.sources .micro-tag');if(tag)tag.textContent='SERVER';
const sourcesNote=document.querySelector('.sources .section-title p');if(sourcesNote)sourcesNote.textContent='Fayllarni yuklang — ular faqat sizning hisobingizda saqlanadi.';

// --- devices: the server renders on CPU only
const device=document.querySelector('select[name="device"]');
if(device){for(const o of device.options)if(o.value!=='cpu'){o.disabled=true;o.textContent+=' — onlaynda yo‘q'}device.value='cpu';device.dispatchEvent(new Event('change',{bubbles:true}))}

// --- quota bar
const sources=document.querySelector('.sources');
const quota=el('div','cloud-quota');quota.innerHTML='<div class="cloud-quota-bar"><i></i></div><span></span>';
sources?.querySelector('.section-title')?.after(quota);

// --- one upload panel per source folder
const panels={};
for(const kind of ['clips','licenses','music']){
 const input=document.getElementById(kind);if(!input)continue;
 const field=input.closest('.path-field');field.classList.add('cloud-hidden');
 const box=el('div','cloud-files');const head=el('div','cloud-files-head');
 const count=el('span','cloud-count','Fayl yo‘q');const pick=el('input');pick.type='file';pick.multiple=true;pick.accept=ACCEPT[kind];pick.hidden=true;
 const add=el('button','secondary cloud-add','+ Fayl qo‘shish');add.type='button';add.onclick=()=>pick.click();
 head.append(count,add,pick);const list=el('ul','cloud-list');const progress=el('div','cloud-progress');progress.hidden=true;
 box.append(head,progress,list);field.after(box);
 pick.onchange=()=>{upload(kind,[...pick.files]);pick.value=''};
 box.addEventListener('dragover',e=>{e.preventDefault();box.classList.add('drag')});
 box.addEventListener('dragleave',()=>box.classList.remove('drag'));
 box.addEventListener('drop',e=>{e.preventDefault();box.classList.remove('drag');upload(kind,[...e.dataTransfer.files])});
 panels[kind]={count,list,progress,add};
}

// --- outputs: results live on the server and are downloaded from here
const outInput=document.getElementById('output');
let outBox=null;
if(outInput){const field=outInput.closest('.path-field');field.classList.add('cloud-hidden');
 outBox=el('div','cloud-files cloud-output');outBox.append(el('p','field-note','Tayyor videolar shu yerda paydo bo‘ladi. Yuklab olgach, joy bo‘shatish uchun o‘chirishingiz mumkin.'),el('ul','cloud-list'));
 field.after(outBox);}

function put(kind,file,onprogress){return new Promise((resolve,reject)=>{
 const x=new XMLHttpRequest();x.open('PUT','/files/'+kind+'/'+encodeURIComponent(file.name));
 x.upload.onprogress=e=>e.lengthComputable&&onprogress(e.loaded/e.total);
 x.onload=()=>{let d={};try{d=JSON.parse(x.responseText)}catch{}x.status===200?resolve(d):reject(Error(d.error||('Yuklanmadi: '+file.name)))};
 x.onerror=()=>reject(Error('Tarmoq xatosi: '+file.name));x.send(file)})}

async function upload(kind,files){
 if(!files.length)return;const p=panels[kind];uploading++;p.add.disabled=true;p.progress.hidden=false;
 let done=0;
 for(const f of files){
  if(info&&f.size>info.max_file){say(`${f.name}: fayl ${size(info.max_file)} dan katta.`,true);continue}
  try{await put(kind,f,v=>{p.progress.style.setProperty('--p',((done+v)/files.length*100)+'%');p.progress.textContent=`${f.name} · ${Math.round(v*100)}%`});done++}
  catch(e){say(e.message,true)}
 }
 uploading--;p.add.disabled=false;p.progress.hidden=true;
 if(done)say(`${done} ta ${LABEL[kind]} yuklandi.`);
 await refresh();
 if(kind==='music'&&typeof loadMusic==='function')try{await loadMusic(true)}catch{}
 if(typeof optionsChanged==='function')optionsChanged();
}

async function remove(kind,path,label){
 if(!confirm(`${label} o‘chirilsinmi?`))return;
 try{await call('DELETE','/files/'+kind+'/'+enc(path));await refresh();if(kind==='music'&&typeof loadMusic==='function')loadMusic(true)}catch(e){say(e.message,true)}
}

function drawList(kind,items){
 const p=panels[kind];if(!p)return;p.list.replaceChildren();
 const total=items.reduce((a,f)=>a+f.size,0);
 p.count.textContent=items.length?`${items.length} ta fayl · ${size(total)}`:'Fayl yo‘q — yuklang yoki shu yerga tashlang';
 for(const f of items){const li=el('li');const del=el('button','cloud-del','×');del.type='button';del.title='O‘chirish';
  del.onclick=()=>remove(kind,f.name,f.name);li.append(el('span','cloud-name',f.name),el('small','',size(f.size)),del);p.list.append(li)}
}

function drawOutputs(outputs){
 if(!outBox)return;const list=outBox.querySelector('.cloud-list');list.replaceChildren();
 if(!outputs.length){list.append(el('li','cloud-empty','Hozircha natija yo‘q.'));return}
 for(const o of outputs){const li=el('li','cloud-result');const name=el('span','cloud-name',o.name);const links=el('span','cloud-links');
  for(const f of o.files.filter(f=>/\.(mp4|xlsx)$/i.test(f.name)||f.name==='Playlist.txt')){const a=el('a','',f.name.toLowerCase().endsWith('.mp4')?'Video':f.name.toLowerCase().endsWith('.xlsx')?'Excel':'Playlist');
   a.href='/files/output/'+enc(o.name+'/'+f.name);a.setAttribute('download',f.name);a.title=`${f.name} · ${size(f.size)}`;links.append(a)}
  const del=el('button','cloud-del','×');del.type='button';del.title='Natijani o‘chirish';del.onclick=()=>remove('output',o.name,`“${o.name}” natijasi`);
  li.append(name,links,del);list.append(li)}
}

async function refresh(){
 try{info=await call('GET','/files')}catch(e){return}
 for(const k of ['clips','licenses','music'])drawList(k,info[k]);
 drawOutputs(info.output);
 const pct=Math.min(100,info.usage/info.quota*100);
 quota.querySelector('i').style.width=pct+'%';quota.classList.toggle('full',pct>=95);
 quota.querySelector('span').textContent=`Disk: ${size(info.usage)} / ${size(info.quota)} · bir martada ${info.max_videos} tagacha video`;
 const who=document.getElementById('cloud-user');if(who)who.textContent=info.email;
 const total=document.querySelector('input[name="total"]');if(total){total.max=info.max_videos;if(+total.value>info.max_videos)total.value=info.max_videos}
}

// --- per-job video link in the report panel, and refresh when a batch ends
const report=document.getElementById('download-report');
let video=null;
if(report){video=report.cloneNode(false);video.id='download-video';video.removeAttribute('href');video.hidden=true;
 video.innerHTML='<svg><use href="#i-download"/></svg>Videoni yuklab olish';report.after(video)}
setInterval(()=>{
 if(typeof state==='undefined'||!state)return;
 const j=typeof chosenJob==='function'?chosenJob():null;
 if(video){const ok=j&&j.status==='done'&&j.output_name&&j.video_filename;video.hidden=!ok;
  if(ok)video.href='/files/output/'+enc(j.output_name+'/'+j.video_filename)}
 const s=state.status+':'+(state.jobs||[]).filter(x=>x.status==='done').length;
 if(s!==lastStatus){lastStatus=s;if(!uploading)refresh()}
},1500);

refresh();
})();
