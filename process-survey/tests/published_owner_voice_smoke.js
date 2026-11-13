const fs = require('fs');
const path = require('path');

const root = path.resolve(__dirname, '..');
const current = JSON.parse(fs.readFileSync(path.join(root, 'pages/current.json'), 'utf8'));
const base = current.url.replace(/\/$/, '');
const admin = fs.readFileSync(path.join(root, 'ADMIN_PASSWORD.txt'), 'utf8').trim();
const results = [];
const ids = [];

async function json(response) {
  const text = await response.text();
  let data = {};
  try { data = text ? JSON.parse(text) : {}; } catch (_) {}
  return { status: response.status, data };
}

async function generate(lang, text) {
  const createdResponse = await fetch(base + '/api/interviews', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name: 'Проверка голоса владельца', dept: 'other', position: 'Временный тест', lang, consent: true, mode: 'script' }),
  });
  const created = await json(createdResponse);
  if (created.status !== 200) throw new Error('Create ' + lang + ': ' + JSON.stringify(created));
  const token = created.data.token;
  const doc = created.data.doc;
  ids.push(doc.id);
  doc.messages = [{ role: 'assistant', content: text, phase: 1 }];
  const saved = await json(await fetch(base + '/api/me', {
    method: 'PUT', headers: { Authorization: 'Bearer ' + token, 'Content-Type': 'application/json' }, body: JSON.stringify({ doc }),
  }));
  if (saved.status !== 200) throw new Error('Save ' + lang + ': ' + JSON.stringify(saved));

  const started = Date.now();
  let audio;
  for (let attempt = 0; attempt < 100; attempt++) {
    const response = await fetch(base + '/api/me/voice/0', { headers: { Authorization: 'Bearer ' + token, Accept: 'audio/mp4, application/json' } });
    if (response.status === 202) {
      await new Promise(resolve => setTimeout(resolve, 2000));
      continue;
    }
    if (response.status !== 200) throw new Error('Voice ' + lang + ': HTTP ' + response.status + ' ' + await response.text());
    audio = Buffer.from(await response.arrayBuffer());
    if ((response.headers.get('content-type') || '').split(';')[0] !== 'audio/mp4') throw new Error('Voice content type: ' + response.headers.get('content-type'));
    break;
  }
  if (!audio) throw new Error('Voice timeout: ' + lang);
  if (audio.length < 1000 || !audio.subarray(0, 40).includes('ftyp')) throw new Error('Invalid M4A: ' + lang);
  const generationMs = Date.now() - started;
  const cacheStarted = Date.now();
  const cached = await fetch(base + '/api/me/voice/0', { headers: { Authorization: 'Bearer ' + token } });
  if (cached.status !== 200) throw new Error('Cached voice: ' + lang + ' HTTP ' + cached.status);
  const cachedBytes = Buffer.from(await cached.arrayBuffer());
  if (!cachedBytes.equals(audio)) throw new Error('Cached bytes differ: ' + lang);
  const file = path.join(root, 'run/public-owner-voice-' + lang + '.m4a');
  fs.writeFileSync(file, audio);
  return { lang, status: 'ready', bytes: audio.length, generationMs, cacheMs: Date.now() - cacheStarted, cachedBytesMatch: true };
}

(async () => {
  try {
    results.push(await generate('ru', 'Здравствуйте! Расскажите, какие задачи вы выполняете каждый день?'));
    results.push(await generate('ro', 'Bună ziua! Spuneți-ne ce sarcini îndepliniți în fiecare zi?'));
  } catch (error) {
    results.fatal = String(error && error.stack || error);
    process.exitCode = 1;
  } finally {
    const cleanup = [];
    for (const id of ids) {
      const response = await fetch(base + '/api/admin/interviews/' + id, { method: 'DELETE', headers: { 'X-Admin-Key': admin } });
      cleanup.push({ id, status: response.status });
      if (!response.ok) process.exitCode = 1;
    }
    const output = { results, cleanup, fatal: results.fatal };
    delete output.fatal;
    if (results.fatal) output.fatal = results.fatal;
    fs.writeFileSync(path.join(root, 'run/published-owner-voice-result.json'), JSON.stringify(output, null, 2) + '\n');
    console.log(JSON.stringify(output, null, 2));
  }
})();
