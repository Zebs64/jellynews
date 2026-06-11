/* JellyNews — logique du portail d'administration (vanilla JS, zéro dépendance). */
'use strict';

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

/* ------------------------------------------------------------- helpers -- */
let toastTimer = null;
function toast(message, isError = false) {
  const el = $('#toast');
  el.textContent = message;
  el.classList.toggle('error', isError);
  el.classList.remove('hidden');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.add('hidden'), 4000);
}

async function api(path, options = {}) {
  const resp = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  if (resp.status === 401) {
    window.location.href = '/login'; // session expirée
    throw new Error('Session expirée');
  }
  if (!resp.ok) {
    let detail = resp.statusText;
    try { detail = (await resp.json()).detail || detail; } catch (_) { /* HTML */ }
    throw new Error(detail);
  }
  return resp;
}

/* ---------------------------------------------------------- navigation -- */
$$('.nav-btn').forEach((btn) => {
  btn.addEventListener('click', () => {
    $$('.nav-btn').forEach((b) => b.classList.remove('active'));
    $$('.panel').forEach((p) => p.classList.add('hidden'));
    btn.classList.add('active');
    $('#' + btn.dataset.panel).classList.remove('hidden');
  });
});

/* ------------------------------------------------------------ settings -- */
function setNextRun(iso) {
  $('#next-run').textContent = iso ? new Date(iso).toLocaleString('fr-FR') : 'désactivé';
}

async function loadSettings() {
  const settings = await (await api('/api/settings')).json();
  $$('.settings-form').forEach((form) => {
    form.querySelectorAll('[name]').forEach((input) => {
      const value = settings[input.name];
      if (value === undefined) return;
      if (input.type === 'checkbox') input.checked = value === '1';
      else input.value = value;
    });
  });
  setNextRun(settings._next_run);
  if (settings.logo_filename) {
    const img = $('#logo-preview');
    img.src = '/uploads/' + settings.logo_filename + '?t=' + Date.now();
    img.classList.remove('hidden');
  }
}

$$('.settings-form').forEach((form) => {
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const payload = {};
    form.querySelectorAll('[name]').forEach((input) => {
      payload[input.name] = input.type === 'checkbox' ? (input.checked ? '1' : '0') : input.value;
    });
    try {
      const result = await (await api('/api/settings', {
        method: 'POST',
        body: JSON.stringify(payload),
      })).json();
      setNextRun(result.next_run);
      toast('Configuration enregistrée ✔');
    } catch (err) {
      toast('Erreur : ' + err.message, true);
    }
  });
});

/* ---------------------------------------------------------------- logo -- */
$('#logo-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const file = $('#logo-file').files[0];
  if (!file) return toast('Choisissez un fichier.', true);
  const data = new FormData();
  data.append('file', file);
  try {
    // Pas de Content-Type manuel : le navigateur pose le boundary multipart.
    const resp = await fetch('/api/logo', { method: 'POST', body: data });
    if (!resp.ok) throw new Error((await resp.json()).detail || resp.statusText);
    const { url } = await resp.json();
    const img = $('#logo-preview');
    img.src = url + '?t=' + Date.now();
    img.classList.remove('hidden');
    toast('Logo mis à jour ✔');
  } catch (err) {
    toast('Erreur : ' + err.message, true);
  }
});

/* ------------------------------------------------------------- abonnés -- */
function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

async function loadSubscribers() {
  const subs = await (await api('/api/subscribers')).json();
  $('#subscribers-body').innerHTML = subs.map((s) => `
    <tr>
      <td>${escapeHtml(s.email)}</td>
      <td>${escapeHtml((s.created_at || '').replace('T', ' '))}</td>
      <td><button class="btn danger" data-del="${s.id}">Supprimer</button></td>
    </tr>`).join('') || '<tr><td colspan="3">Aucun abonné pour le moment.</td></tr>';
}

$('#subscriber-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  try {
    await api('/api/subscribers', {
      method: 'POST',
      body: JSON.stringify({ email: $('#subscriber-email').value }),
    });
    $('#subscriber-email').value = '';
    await loadSubscribers();
    toast('Abonné ajouté ✔');
  } catch (err) {
    toast('Erreur : ' + err.message, true);
  }
});

$('#subscribers-body').addEventListener('click', async (event) => {
  const id = event.target.dataset.del;
  if (!id || !confirm('Supprimer cet abonné ?')) return;
  try {
    await api('/api/subscribers/' + id, { method: 'DELETE' });
    await loadSubscribers();
  } catch (err) {
    toast('Erreur : ' + err.message, true);
  }
});

/* -------------------------------------------------------- bibliothèques -- */
function selectedLibraryIds() {
  return [...$$('#libraries-box input:checked')].map((cb) => cb.value).join(',');
}

$('#btn-load-libraries').addEventListener('click', (e) =>
  withBusy(e.target, 'Chargement…', async () => {
    try {
      const libs = await (await api('/api/jellyfin/libraries')).json();
      const current = $('input[name="library_ids"]').value.split(',').filter(Boolean);
      $('#libraries-box').innerHTML = libs.map((lib) => `
        <label class="checkbox">
          <input type="checkbox" value="${escapeHtml(lib.id)}"
                 ${current.includes(lib.id) ? 'checked' : ''}>
          ${escapeHtml(lib.name)}
        </label>`).join('') || '<em>Aucune bibliothèque trouvée.</em>';
      $$('#libraries-box input').forEach((cb) =>
        cb.addEventListener('change', () => {
          $('input[name="library_ids"]').value = selectedLibraryIds();
        }));
    } catch (err) {
      toast('Erreur : ' + err.message, true);
    }
  }));

/* ------------------------------------------------------------- test LLM -- */
$('#btn-test-llm').addEventListener('click', (e) =>
  withBusy(e.target, 'Génération…', async () => {
    const box = $('#llm-test-result');
    try {
      const result = await (await api('/api/test/llm', { method: 'POST' })).json();
      box.textContent = result.intro;
      box.classList.remove('hidden');
      toast('Intro générée ✔');
    } catch (err) {
      box.classList.add('hidden');
      toast('Erreur : ' + err.message, true);
    }
  }));

/* --------------------------------------------------------- import/export -- */
async function importFile(inputSel, url, onDone) {
  const file = $(inputSel).files[0];
  if (!file) return toast('Choisissez un fichier.', true);
  const data = new FormData();
  data.append('file', file);
  const resp = await fetch(url, { method: 'POST', body: data });
  if (!resp.ok) throw new Error((await resp.json()).detail || resp.statusText);
  return onDone(await resp.json());
}

$('#btn-import-subscribers').addEventListener('click', (e) =>
  withBusy(e.target, 'Import…', async () => {
    try {
      await importFile('#subscribers-file', '/api/subscribers/import', async (r) => {
        await loadSubscribers();
        toast(`Import terminé : ${r.added} ajout(s) sur ${r.found} adresse(s) trouvée(s)`);
      });
    } catch (err) {
      toast('Erreur : ' + err.message, true);
    }
  }));

$('#btn-import-settings').addEventListener('click', (e) => {
  if (!confirm('Écraser la configuration actuelle avec ce fichier ?')) return;
  withBusy(e.target, 'Import…', async () => {
    try {
      await importFile('#settings-file', '/api/settings/import', async (r) => {
        await loadSettings();
        toast(`Configuration importée (${r.imported} paramètres) ✔`);
      });
    } catch (err) {
      toast('Erreur : ' + err.message, true);
    }
  });
});

/* ------------------------------------------------------------- archives -- */
async function loadArchives() {
  const archives = await (await api('/api/archives')).json();
  $('#archives-body').innerHTML = archives.map((a) => `
    <tr>
      <td>${escapeHtml((a.created_at || '').replace('T', ' '))}</td>
      <td>${escapeHtml(a.subject)}</td>
      <td>${a.items_count}</td>
      <td>${a.recipients}</td>
      <td><a class="btn" href="/api/archives/${a.id}" target="_blank">Voir</a></td>
    </tr>`).join('') || '<tr><td colspan="5">Aucune archive pour le moment.</td></tr>';
}

/* ---------------------------------------------------------------- logs -- */
async function loadLogs() {
  const logs = await (await api('/api/logs')).json();
  $('#logs-body').innerHTML = logs.map((l) => `
    <tr>
      <td>${escapeHtml((l.created_at || '').replace('T', ' '))}</td>
      <td>${escapeHtml(l.trigger)}</td>
      <td class="status-${escapeHtml(l.status)}">${escapeHtml(l.status)}</td>
      <td>${l.items_count}</td>
      <td>${l.recipients}</td>
      <td>${escapeHtml(l.detail || '')}</td>
    </tr>`).join('') || '<tr><td colspan="6">Aucun envoi pour le moment.</td></tr>';
}

/* -------------------------------------------------------------- actions -- */
async function withBusy(button, label, fn) {
  const original = button.textContent;
  button.disabled = true;
  button.textContent = label;
  try { await fn(); } finally {
    button.disabled = false;
    button.textContent = original;
  }
}

$('#btn-test-jellyfin').addEventListener('click', (e) =>
  withBusy(e.target, 'Test en cours…', async () => {
    try {
      const result = await (await api('/api/test/jellyfin', { method: 'POST' })).json();
      toast(`Connexion OK — ${result.count} nouveautés (${result.sample.join(', ') || 'aucune'})`);
    } catch (err) {
      toast('Erreur : ' + err.message, true);
    }
  }));

$('#btn-test-email').addEventListener('click', (e) =>
  withBusy(e.target, 'Envoi…', async () => {
    try {
      await api('/api/test/email', {
        method: 'POST',
        body: JSON.stringify({ to: $('#test-email-to').value }),
      });
      toast('Email de test envoyé ✔');
    } catch (err) {
      toast('Erreur : ' + err.message, true);
    }
  }));

$('#btn-preview').addEventListener('click', () => window.open('/api/preview', '_blank'));

$('#btn-send-now').addEventListener('click', (e) => {
  if (!confirm('Envoyer la newsletter à tous les abonnés maintenant ?')) return;
  withBusy(e.target, 'Envoi en cours…', async () => {
    try {
      const result = await (await api('/api/send-now', { method: 'POST' })).json();
      toast(`Terminé : ${result.sent} email(s) envoyés, ${result.items} médias (${result.status})`);
      await Promise.all([loadLogs(), loadArchives()]);
    } catch (err) {
      toast('Erreur : ' + err.message, true);
      await Promise.all([loadLogs(), loadArchives()]);
    }
  });
});

/* ------------------------------------------------------ fuseaux horaires -- */
async function loadTimezones() {
  const zones = await (await api('/api/timezones')).json();
  $('#tz-list').innerHTML = zones.map((z) => `<option value="${escapeHtml(z)}">`).join('');
}

/* ----------------------------------------------------------------- init -- */
(async () => {
  try {
    await Promise.all([loadSettings(), loadSubscribers(), loadLogs(), loadArchives(), loadTimezones()]);
  } catch (err) {
    toast('Erreur de chargement : ' + err.message, true);
  }
})();
