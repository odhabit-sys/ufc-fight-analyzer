// Hash router:  #/ upload · #/processing/<id> · #/select/<id> · #/analysis/<id>
import { openUpload } from './upload.js';
import { closeProcessing, openProcessing } from './processing.js';
import { closeViewer, openViewer } from './viewer.js';
import { closeSelect, openSelect } from './select.js';

const $ = id => document.getElementById(id);
const VIEWS = ['upload', 'processing', 'select', 'viewer'];

function show(name) {
  for (const v of VIEWS) $(`view-${v}`).hidden = v !== name;
  $('btn-new').hidden = name === 'upload';
  if (name === 'upload') setFile('');
}

function setFile(name) { $('topbar-file').textContent = name ? `/ ${name}` : ''; }

async function route() {
  const [, view, id] = location.hash.split('/');
  closeProcessing();
  closeSelect();
  if (view !== 'analysis') closeViewer();
  if (view === 'select' && id) {
    show('select');
    openSelect(id, setFile);
  } else if (view === 'processing' && id) {
    show('processing');
    openProcessing(id, setFile);
  } else if (view === 'analysis' && id) {
    show('viewer');
    try {
      await openViewer(id, setFile);
    } catch (e) {
      console.error(e);
      location.hash = `#/processing/${id}`;   // not finished (or failed): show its status
    }
  } else {
    show('upload');
    openUpload();
  }
}

window.addEventListener('hashchange', route);
route();
