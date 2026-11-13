const { webkit } = require('playwright');
const fs = require('fs');
const path = require('path');

const root = path.resolve(__dirname, '..');
const config = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const result = { checks: {}, errors: [] };
function check(name, value) { result.checks[name] = Boolean(value); if (!value) throw new Error(name); }

(async () => {
  let browser, interviewId;
  try {
    browser = await webkit.launch({ headless: true });
    const context = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, locale: 'ru-RU' });
    const page = await context.newPage();
    page.on('pageerror', error => result.errors.push(String(error)));
    await page.goto(config.stableUrl || config.base + '/', { waitUntil: 'load', timeout: 60000 });
    const app = config.stableUrl ? page.frameLocator('#app') : page;
    await app.locator('#f-name').waitFor({ state: 'visible', timeout: 60000 });
    await app.locator('#f-name').fill('Проверка двух функций');
    await app.locator('#f-dept').selectOption('prod_dir');
    await app.locator('#role-picker').evaluate(picker => { picker.open = true; });
    await app.locator('.role-choice').evaluateAll(inputs => inputs.forEach(input => { if (input.checked) input.click(); }));
    for (const key of ['01', '20']) {
      await app.locator('#role-picker').evaluate(picker => { picker.open = true; });
      await app.locator('.role-choice[value="' + key + '"]').check();
    }
    await app.locator('#f-pos').fill('Директор производства и качество');
    await app.locator('#f-about').fill('Каждый день сверяю остатки сырья и готовлю отчёт в Excel. Проверяю BOM и согласую изменения с командой.');
    await app.locator('#f-consent').check();
    const frame = page.frames().find(item => item.url().startsWith(config.base));
    await page.screenshot({ path: path.join(root, 'run/multirole-welcome.png'), fullPage: false });
    const branding = await frame.evaluate(() => ({
      accent: getComputedStyle(document.documentElement).getPropertyValue('--accent').trim(),
      logo: document.querySelector('.brand-logo') && document.querySelector('.brand-logo').src.startsWith('data:image/png;base64,'),
    }));
    check('blue_brand', branding.accent === '#21439B');
    check('embedded_logo', branding.logo);
    await app.locator('#start-btn').click();
    await app.locator('#answer').waitFor({ state: 'visible', timeout: 60000 });
    await frame.waitForFunction(async () => {
      const response = await fetch('/api/me', { headers: { Authorization: 'Bearer ' + localStorage.getItem('bp_token') } });
      const data = await response.json();
      return data.doc && (data.doc.messages || []).length > 0;
    }, null, { timeout: 30000 });
    const me = await frame.evaluate(async () => {
      const response = await fetch('/api/me', { headers: { Authorization: 'Bearer ' + localStorage.getItem('bp_token') } });
      return response.json();
    });
    interviewId = me.doc.id;
    check('primary_role', me.doc.roleKey === '01');
    check('two_roles', me.doc.roleKeys.join(',') === '01,20');
    check('about_analysis_present', me.doc.about.includes('сверяю остатки') && me.doc.aboutAnalysis.activities.length > 0);
    check('primary_question', me.doc.messages[0].questionKey === '01-01');
    check('no_js_errors', result.errors.length === 0);
    const response = await fetch(config.base + '/api/admin/interviews', { headers: { 'X-Admin-Key': config.admin } });
    const data = await response.json();
    const doc = data.interviews.find(item => item.id === interviewId);
    check('admin_roles_saved', doc && doc.roleKey === '01' && doc.roleKeys.join(',') === '01,20');
  } catch (error) {
    result.fatal = String(error && error.stack || error);
    process.exitCode = 1;
  } finally {
    if (browser) await browser.close();
    if (interviewId) {
      const response = await fetch(config.base + '/api/admin/interviews/' + interviewId, { method: 'DELETE', headers: { 'X-Admin-Key': config.admin } });
      result.cleanup = { attempted: true, status: response.status, ok: response.ok };
      if (!response.ok) process.exitCode = 1;
    }
    fs.writeFileSync(path.join(root, 'run/multirole-smoke-result.json'), JSON.stringify(result, null, 2) + '\n');
    console.log(JSON.stringify(result, null, 2));
  }
})();
