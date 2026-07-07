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
function activatePanel(panelId) {
  $$('.nav-btn').forEach((b) => b.classList.toggle('active', b.dataset.panel === panelId));
  $$('.panel').forEach((p) => p.classList.add('hidden'));
  const panel = $('#' + panelId);
  if (panel) panel.classList.remove('hidden');
}

$$('[data-panel]').forEach((btn) => {
  btn.addEventListener('click', () => activatePanel(btn.dataset.panel));
});

/* ------------------------------------------------------------ settings -- */
function formatDateTime(iso) {
  return iso ? new Date(iso).toLocaleString('fr-FR') : 'désactivé';
}

function metricText(id, value) {
  const el = $('#' + id);
  if (el) el.textContent = value;
}

function setNextRun(iso) {
  const value = formatDateTime(iso);
  $('#next-run').textContent = value;
  metricText('home-next-run-value', value);
  metricText('home-next-run-detail', iso ? 'Planification active.' : 'Envoi automatique désactivé.');
}

function formatMediaCount(count) {
  if (count === null || count === undefined) return '—';
  return `${count} média${count > 1 ? 's' : ''}`;
}

function renderLastSend(log) {
  if (!log) {
    metricText('home-last-send-value', 'Aucun envoi');
    metricText('home-last-send-detail', 'L’historique est vide.');
    return;
  }
  metricText('home-last-send-value', log.status || 'inconnu');
  metricText(
    'home-last-send-detail',
    `${formatDateTime(log.created_at)} — ${log.items_count || 0} média(s), ${log.recipients || 0} destinataire(s)`,
  );
}

async function loadDashboardSummary() {
  const summary = await (await api('/api/dashboard-summary')).json();
  setNextRun(summary.next_run);
  metricText('home-recent-count-value', formatMediaCount(summary.recent_items_count));
  metricText(
    'home-recent-count-detail',
    summary.recent_items_error || `Sur ${summary.lookback_days || 7} jour(s) configuré(s).`,
  );
  metricText('home-subscribers-value', String(summary.subscribers_count || 0));
  metricText('home-subscribers-detail', 'Abonnés actifs en base.');
  renderLastSend(summary.last_send);
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
  await loadNewsletterEditor(settings);
  setNextRun(settings._next_run);
  if (settings.logo_filename) {
    const img = $('#logo-preview');
    img.src = '/uploads/' + settings.logo_filename + '?t=' + Date.now();
    img.classList.remove('hidden');
  }
}

let newsletterEditorMeta = null;
let newsletterBlocksState = [];

function blockMeta(blockId) {
  return (newsletterEditorMeta?.blocks || []).find((block) => block.id === blockId) || { id: blockId, label: blockId, mandatory: false };
}

function defaultNewsletterBlocks() {
  try {
    return JSON.parse(newsletterEditorMeta.default_blocks_json);
  } catch (_) {
    return (newsletterEditorMeta?.blocks || []).map((block) => ({ id: block.id, enabled: true }));
  }
}

function parseNewsletterBlocks(value) {
  if (!value) return defaultNewsletterBlocks();
  try {
    const parsed = JSON.parse(value);
    return Array.isArray(parsed) ? parsed : defaultNewsletterBlocks();
  } catch (_) {
    return defaultNewsletterBlocks();
  }
}

function normalizeNewsletterBlocks(rawBlocks) {
  const known = new Set((newsletterEditorMeta?.blocks || []).map((block) => block.id));
  const seen = new Set();
  const normalized = [];
  rawBlocks.forEach((block) => {
    const id = String(block.id || '');
    if (!known.has(id) || seen.has(id)) return;
    const meta = blockMeta(id);
    normalized.push({ id, enabled: meta.mandatory ? true : block.enabled !== false });
    seen.add(id);
  });
  (newsletterEditorMeta?.blocks || []).forEach((meta) => {
    if (!seen.has(meta.id)) normalized.push({ id: meta.id, enabled: true });
  });
  return normalized;
}

function syncNewsletterBlocksInput() {
  const input = $('#newsletter-blocks-json');
  if (!input) return;
  input.value = JSON.stringify(newsletterBlocksState.map((block) => ({ id: block.id, enabled: !!block.enabled })));
}

function renderNewsletterTemplates(selectedId) {
  const select = $('#newsletter-template-id');
  const cards = $('#newsletter-template-cards');
  if (!select || !cards || !newsletterEditorMeta) return;
  select.textContent = '';
  cards.textContent = '';
  newsletterEditorMeta.templates.forEach((template) => {
    const option = document.createElement('option');
    option.value = template.id;
    option.textContent = template.name;
    select.append(option);

    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'template-card';
    button.dataset.templateId = template.id;
    button.classList.toggle('active', template.id === selectedId);

    const visual = document.createElement('span');
    visual.className = `template-mini template-mini-${template.id}`;
    visual.setAttribute('aria-hidden', 'true');
    for (let i = 0; i < 4; i += 1) {
      visual.append(document.createElement('i'));
    }

    const title = document.createElement('strong');
    title.textContent = template.name;
    const desc = document.createElement('small');
    desc.textContent = template.description || '';
    button.append(visual, title, desc);
    if (template.badge) {
      const badge = document.createElement('span');
      badge.className = 'template-badge';
      badge.textContent = template.badge;
      button.append(badge);
    }
    button.addEventListener('click', () => {
      select.value = template.id;
      renderNewsletterTemplates(template.id);
    });
    cards.append(button);
  });
  select.value = selectedId;
}

function renderNewsletterBlocks() {
  const list = $('#newsletter-block-list');
  if (!list) return;
  list.textContent = '';
  newsletterBlocksState.forEach((block, index) => {
    const meta = blockMeta(block.id);
    const row = document.createElement('div');
    row.className = 'block-row';

    const label = document.createElement('label');
    label.className = 'checkbox block-toggle';
    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.checked = !!block.enabled;
    checkbox.disabled = !!meta.mandatory;
    checkbox.dataset.blockIndex = String(index);
    const name = document.createElement('span');
    name.textContent = meta.label;
    if (meta.mandatory) {
      const mandatory = document.createElement('small');
      mandatory.textContent = 'Obligatoire';
      label.append(checkbox, name, mandatory);
    } else {
      label.append(checkbox, name);
    }

    const controls = document.createElement('div');
    controls.className = 'block-controls';
    const up = document.createElement('button');
    up.type = 'button';
    up.className = 'btn mini';
    up.textContent = '↑';
    up.dataset.moveBlock = 'up';
    up.dataset.blockIndex = String(index);
    up.disabled = block.id === 'preheader' || index === 0;
    const down = document.createElement('button');
    down.type = 'button';
    down.className = 'btn mini';
    down.textContent = '↓';
    down.dataset.moveBlock = 'down';
    down.dataset.blockIndex = String(index);
    down.disabled = block.id === 'footer' || index === newsletterBlocksState.length - 1;
    controls.append(up, down);
    row.append(label, controls);
    list.append(row);
  });
  syncNewsletterBlocksInput();
}

async function loadNewsletterEditor(settings) {
  if (!newsletterEditorMeta) {
    newsletterEditorMeta = await (await api('/api/newsletter/templates')).json();
  }
  const selectedId = settings.newsletter_template_id || newsletterEditorMeta.default_template_id;
  newsletterBlocksState = normalizeNewsletterBlocks(parseNewsletterBlocks(settings.newsletter_blocks_json));
  renderNewsletterTemplates(selectedId);
  renderNewsletterBlocks();
}

$$('.settings-form').forEach((form) => {
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    syncNewsletterBlocksInput();
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
      await loadDashboardSummary();
      toast('Configuration enregistrée ✔');
    } catch (err) {
      toast('Erreur : ' + err.message, true);
    }
  });
});

$('#newsletter-template-id').addEventListener('change', (event) => {
  renderNewsletterTemplates(event.target.value);
});

$('#newsletter-block-list').addEventListener('change', (event) => {
  const index = Number(event.target.dataset.blockIndex);
  if (!Number.isInteger(index) || !newsletterBlocksState[index]) return;
  newsletterBlocksState[index].enabled = !!event.target.checked;
  syncNewsletterBlocksInput();
});

$('#newsletter-block-list').addEventListener('click', (event) => {
  const direction = event.target.dataset.moveBlock;
  if (!direction) return;
  const index = Number(event.target.dataset.blockIndex);
  const target = direction === 'up' ? index - 1 : index + 1;
  if (!newsletterBlocksState[index] || !newsletterBlocksState[target]) return;
  if (newsletterBlocksState[index].id === 'preheader' || newsletterBlocksState[index].id === 'footer') return;
  if (newsletterBlocksState[target].id === 'preheader' || newsletterBlocksState[target].id === 'footer') return;
  [newsletterBlocksState[index], newsletterBlocksState[target]] = [newsletterBlocksState[target], newsletterBlocksState[index]];
  renderNewsletterBlocks();
});

$('#btn-reset-newsletter-blocks').addEventListener('click', () => {
  newsletterBlocksState = normalizeNewsletterBlocks(defaultNewsletterBlocks());
  renderNewsletterBlocks();
});

$('#btn-preview-branding').addEventListener('click', () => window.open('/api/preview', '_blank'));

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

function emptyRow(cols, message) {
  return `<tr><td colspan="${cols}"><div class="empty-state compact">${escapeHtml(message)}</div></td></tr>`;
}

function importSummary(result) {
  const imported = result.imported || {};
  const skipped = result.skipped || {};
  const parts = [
    `${imported.settings || 0} paramètre(s)`,
    `${imported.subscribers || 0} abonné(s)`,
    `${imported.send_logs || 0} log(s)`,
    `${imported.archives || 0} archive(s)`,
  ];
  const skippedTotal = (skipped.subscribers || 0) + (skipped.send_logs || 0) + (skipped.archives || 0);
  return `Sauvegarde importée : ${parts.join(', ')}${skippedTotal ? ` — ${skippedTotal} doublon(s) ignoré(s)` : ''} ✔`;
}

function statusClass(value) {
  return String(value || 'unknown').toLowerCase().replace(/[^a-z0-9_-]/g, '-');
}

async function loadSubscribers() {
  const subs = await (await api('/api/subscribers')).json();
  metricText('home-subscribers-value', String(subs.length));
  $('#subscribers-body').innerHTML = subs.map((s) => `
    <tr>
      <td>${escapeHtml(s.email)}</td>
      <td>${escapeHtml((s.created_at || '').replace('T', ' '))}</td>
      <td><button class="btn danger" data-del="${s.id}">Supprimer</button></td>
    </tr>`).join('') || emptyRow(3, 'Aucun abonné pour le moment.');
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
      const box = $('#libraries-box');
      box.textContent = '';
      if (!libs.length) {
        const empty = document.createElement('em');
        empty.textContent = 'Aucune bibliothèque trouvée.';
        box.append(empty);
        return;
      }
      libs.forEach((lib) => {
        const id = String(lib.id || '');
        const label = document.createElement('label');
        label.className = 'checkbox';

        const input = document.createElement('input');
        input.type = 'checkbox';
        input.value = id;
        input.checked = current.includes(id);
        input.addEventListener('change', () => {
          $('input[name="library_ids"]').value = selectedLibraryIds();
        });

        label.append(input, document.createTextNode(' ' + String(lib.name || '')));
        box.append(label);
      });
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
  if (!confirm('Importer cette sauvegarde complète ? Les données existantes seront fusionnées, pas supprimées.')) return;
  withBusy(e.target, 'Import…', async () => {
    try {
      await importFile('#settings-file', '/api/settings/import', async (r) => {
        await Promise.all([loadSettings(), loadSubscribers(), loadLogs(), loadArchives()]);
        toast(importSummary(r));
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
    </tr>`).join('') || emptyRow(5, 'Aucune archive pour le moment.');
}

/* ---------------------------------------------------------------- logs -- */
async function loadLogs() {
  const logs = await (await api('/api/logs')).json();
  renderLastSend(logs[0]);
  $('#logs-body').innerHTML = logs.map((l) => {
    const status = escapeHtml(l.status || 'unknown');
    const klass = statusClass(l.status);
    return `
      <tr>
        <td>${escapeHtml((l.created_at || '').replace('T', ' '))}</td>
        <td>${escapeHtml(l.trigger)}</td>
        <td><span class="status-pill is-${klass}">${status}</span></td>
        <td>${l.items_count}</td>
        <td>${l.recipients}</td>
        <td>${escapeHtml(l.detail || '')}</td>
      </tr>`;
  }).join('') || emptyRow(6, 'Aucun envoi pour le moment.');
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
      metricText('home-recent-count-value', formatMediaCount(result.count));
      metricText('home-recent-count-detail', 'Dernier test Jellyfin manuel.');
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
      if (result.queued) {
        toast('Campagne lancée en arrière-plan ✔');
      } else {
        toast(`Terminé : ${result.sent} email(s) envoyés, ${result.items} médias (${result.status})`);
      }
      await Promise.all([loadLogs(), loadArchives(), loadDashboardSummary()]);
    } catch (err) {
      toast('Erreur : ' + err.message, true);
      await Promise.all([loadLogs(), loadArchives(), loadDashboardSummary()]);
    }
  });
});

$('#btn-refresh-dashboard').addEventListener('click', (e) =>
  withBusy(e.target, 'Actualisation…', async () => {
    try {
      await loadDashboardSummary();
      toast('Résumé actualisé ✔');
    } catch (err) {
      toast('Erreur : ' + err.message, true);
    }
  }));

/* ------------------------------------------------------ fuseaux horaires -- */
async function loadTimezones() {
  const zones = await (await api('/api/timezones')).json();
  $('#tz-list').innerHTML = zones.map((z) => `<option value="${escapeHtml(z)}">`).join('');
}

/* ----------------------------------------------------------------- init -- */
(async () => {
  try {
    await Promise.all([loadSettings(), loadSubscribers(), loadLogs(), loadArchives(), loadTimezones()]);
    await loadDashboardSummary();
  } catch (err) {
    toast('Erreur de chargement : ' + err.message, true);
  }
})();
