// Upload screen: drop / select a video, real upload progress, list of past analyses.
import { fmtTime } from './data.js';

const $ = id => document.getElementById(id);
let bound = false;

export function openUpload() {
  $('upload-progress').hidden = true;
  $('upload-error').hidden = true;
  $('file-input').value = '';
  if (!bound) bind();
  loadRecent();
}

function bind() {
  bound = true;
  const dz = $('dropzone');
  $('file-input').addEventListener('change', e => e.target.files[0] && upload(e.target.files[0]));
  ['dragenter', 'dragover'].forEach(t => dz.addEventListener(t, e => { e.preventDefault(); dz.classList.add('drag'); }));
  ['dragleave', 'drop'].forEach(t => dz.addEventListener(t, e => { e.preventDefault(); dz.classList.remove('drag'); }));
  dz.addEventListener('drop', e => e.dataTransfer.files[0] && upload(e.dataTransfer.files[0]));
}

function upload(file) {
  const err = $('upload-error');
  err.hidden = true;
  if (!/\.(mp4|mov|m4v|mkv|webm|avi)$/i.test(file.name)) {
    err.textContent = 'Please choose a video file (MP4 or MOV).';
    err.hidden = false;
    return;
  }
  const xhr = new XMLHttpRequest();
  const body = new FormData();
  body.append('file', file);
  $('upload-progress').hidden = false;
  xhr.upload.onprogress = e => {
    if (!e.lengthComputable) return;
    const p = Math.round((e.loaded / e.total) * 100);
    $('upload-pct').textContent = `${p}%`;
    $('upload-bar').style.width = `${p}%`;
  };
  xhr.onload = () => {
    let res = {};
    try { res = JSON.parse(xhr.responseText); } catch { /* keep {} */ }
    if (xhr.status >= 200 && xhr.status < 300 && res.id) {
      location.hash = `#/processing/${res.id}`;
    } else {
      $('upload-progress').hidden = true;
      err.textContent = res.detail || `Upload failed (${xhr.status}).`;
      err.hidden = false;
    }
  };
  xhr.onerror = () => {
    $('upload-progress').hidden = true;
    err.textContent = 'Upload failed: is the analyzer server still running?';
    err.hidden = false;
  };
  xhr.open('POST', '/api/jobs');
  xhr.send(body);
}

async function loadRecent() {
  let jobs = [];
  try { jobs = await (await fetch('/api/jobs')).json(); } catch { return; }
  const list = $('recent-list');
  list.innerHTML = '';
  for (const j of jobs.slice(0, 8)) {
    const li = document.createElement('li');
    const href = j.status === 'done' ? `#/analysis/${j.id}`
      : j.status === 'needs_selection' ? `#/select/${j.id}` : `#/processing/${j.id}`;
    const [status, cls] = j.status === 'done' ? ['Ready', 'ok'] : j.status === 'needs_selection' ? ['Select fighters', 'act']
      : j.status === 'error' ? ['Failed', 'err'] : j.status === 'queued' ? ['Queued', 'act'] : ['Processing', 'act'];
    const dur = j.status === 'done' && j.result ? fmtTime(j.result.duration).slice(0, 5) : '';
    const when = new Date(j.created * 1000).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
    li.innerHTML = `<a href="${href}"><span class="r-name"></span><span class="r-meta">${dur}</span><span class="r-meta">${when}</span><span class="r-status ${cls}">${status}</span></a>`;
    li.querySelector('.r-name').textContent = j.name;
    list.appendChild(li);
  }
  $('recent').hidden = jobs.length === 0;
}
