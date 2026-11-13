const fs = require('fs');
const path = require('path');

(async () => {
  const root = path.resolve(__dirname, '..');
  const cfg = JSON.parse(fs.readFileSync(path.join(root, 'pages/current.json'), 'utf8'));
  const admin = fs.readFileSync(path.join(root, 'ADMIN_PASSWORD.txt'), 'utf8').trim();
  const headers = { 'X-Admin-Key': admin };
  const response = await fetch(cfg.url + '/api/admin/interviews', { headers });
  if (!response.ok) throw new Error('Не удалось получить тестовые интервью: HTTP ' + response.status);
  const data = await response.json();
  const candidates = (data.interviews || []).filter(item =>
    item.name === 'Test' && String(item.startedAt || '') >= '2026-11-02T06:00:00'
  );
  for (const item of candidates) {
    const deleted = await fetch(cfg.url + '/api/admin/interviews/' + encodeURIComponent(item.id), {
      method: 'DELETE', headers,
    });
    if (!deleted.ok) throw new Error('Не удалось удалить временное интервью: HTTP ' + deleted.status);
  }
  console.log(JSON.stringify({ deletedTemporaryInterviews: candidates.length }));
})().catch(error => {
  console.error(error.message);
  process.exitCode = 1;
});
