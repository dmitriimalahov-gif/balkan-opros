const fs = require('fs');
const path = require('path');
const { spawnSync } = require('child_process');

const root = path.resolve(__dirname, '..');
const script = process.argv[2] || 'browser_attachments.js';
const current = JSON.parse(fs.readFileSync(path.join(root, 'pages/current.json'), 'utf8'));
const configPath = path.join(root, 'run/published-attachment-config.json');
fs.writeFileSync(configPath, JSON.stringify({
  base: current.url.replace(/\/$/, ''),
  stableUrl: 'https://dmitriimalahov-gif.github.io/balkan-opros/',
  admin: fs.readFileSync(path.join(root, 'ADMIN_PASSWORD.txt'), 'utf8').trim(),
}), { mode: 0o600 });
try {
  const run = spawnSync(process.execPath, [path.join(root, 'tests', script), configPath], { cwd: root, stdio: 'inherit', timeout: 240000 });
  if (run.error) throw run.error;
  process.exitCode = run.status == null ? 1 : run.status;
} finally {
  fs.rmSync(configPath, { force: true });
}
