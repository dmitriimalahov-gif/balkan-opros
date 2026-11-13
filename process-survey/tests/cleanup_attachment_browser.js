const fs = require('fs');
const path = require('path');

(async () => {
  const root = path.resolve(__dirname, '..');
  const current = JSON.parse(fs.readFileSync(path.join(root, 'pages/current.json'), 'utf8'));
  const admin = fs.readFileSync(path.join(root, 'ADMIN_PASSWORD.txt'), 'utf8').trim();
  const base = current.url.replace(/\/$/, '');
  const headers = { 'X-Admin-Key': admin };
  const response = await fetch(base + '/api/admin/interviews', { headers });
  if (!response.ok) throw new Error('Список интервью: HTTP ' + response.status);
  const data = await response.json();
  const testNames = new Set(['Автопроверка вложений', 'Проверка двух функций']);
  const candidates = (data.interviews || []).filter(item => testNames.has(item.name));
  for (const item of candidates) {
    const deleted = await fetch(base + '/api/admin/interviews/' + item.id, { method: 'DELETE', headers });
    if (!deleted.ok) throw new Error('Удаление ' + item.id + ': HTTP ' + deleted.status);
  }
  console.log(JSON.stringify({ deletedTemporaryInterviews: candidates.length }));
})().catch(error => {
  console.error(error.message);
  process.exitCode = 1;
});
