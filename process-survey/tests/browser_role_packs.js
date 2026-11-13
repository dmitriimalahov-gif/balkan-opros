const { webkit } = require('playwright');
const fs = require('fs');
const path = require('path');

const root = path.resolve(__dirname, '..');
const config = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const packs = JSON.parse(fs.readFileSync(path.join(root, 'role_packs.json'), 'utf8')).roles;
const result = { browser: 'webkit', roles: {}, errors: [], cleanup: [] };

async function chooseRoles(page, keys) {
  await page.locator('#role-picker').evaluate(picker => { picker.open = true; });
  await page.locator('.role-choice').evaluateAll(inputs => inputs.forEach(input => { if (input.checked) input.click(); }));
  for (const key of keys) await page.locator('.role-choice[value="' + key + '"]').check();
}

(async () => {
  let browser;
  const ids = [];
  try {
    browser = await webkit.launch({ headless: true });
    const context = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, locale: 'ru-RU' });
    const page = await context.newPage();
    page.on('pageerror', error => result.errors.push(String(error)));
    for (const [key, pack] of Object.entries(packs)) {
      await page.goto(config.base + '/', { waitUntil: 'load' });
      await page.locator('#f-name').waitFor({ state: 'visible' });
      await page.locator('#f-name').fill('Проверка ' + key);
      await page.locator('#f-dept').selectOption(pack.dept);
      await chooseRoles(page, [key]);
      await page.locator('#f-pos').fill(pack.title.ru);
      await page.locator('#f-consent').check();
      await page.locator('#start-btn').click();
      await page.locator('.msg.a .txt').first().waitFor({ state: 'visible' });
      const text = await page.locator('.msg.a .txt').first().innerText();
      if (!text.includes(pack.questions[0].ru)) throw new Error(key + ': неверный первый вопрос: ' + text);
      const me = await page.evaluate(async () => {
        const response = await fetch('/api/me', { headers: { Authorization: 'Bearer ' + localStorage.getItem('bp_token') } });
        return response.json();
      });
      if (me.doc.roleKey !== key || me.doc.script.stage !== 'role') throw new Error(key + ': роль не сохранена');
      if (me.doc.messages[0].questionKey !== pack.questions[0].id) throw new Error(key + ': нет questionKey');
      ids.push(me.doc.id);
      result.roles[key] = { firstQuestion: true, savedRole: true, questionKey: me.doc.messages[0].questionKey };
      await page.evaluate(() => { localStorage.removeItem('bp_token'); sessionStorage.clear(); });
    }

    await page.goto(config.base + '/', { waitUntil: 'load' });
    await page.locator('#f-name').fill('Две функции');
    await page.locator('#f-dept').selectOption('prod_dir');
    await chooseRoles(page, ['01', '20']);
    await page.locator('#f-pos').fill('Директор производства и качество');
    await page.locator('#f-consent').check();
    result.branding = await page.evaluate(() => ({
      logo: document.querySelector('.brand-logo') && document.querySelector('.brand-logo').src.startsWith('data:image/png;base64,'),
      accent: getComputedStyle(document.documentElement).getPropertyValue('--accent').trim(),
    }));
    await page.locator('#start-btn').click();
    await page.locator('.msg.a .txt').first().waitFor({ state: 'visible' });
    const multiText = await page.locator('.msg.a .txt').first().innerText();
    if (!multiText.includes(packs['01'].questions[0].ru)) throw new Error('Многоролевой сценарий: основная функция неверна');
    const multiMe = await page.evaluate(async () => {
      const response = await fetch('/api/me', { headers: { Authorization: 'Bearer ' + localStorage.getItem('bp_token') } });
      return response.json();
    });
    if (multiMe.doc.roleKey !== '01' || multiMe.doc.roleKeys.join(',') !== '01,20') throw new Error('Многоролевой сценарий: роли не сохранены');
    ids.push(multiMe.doc.id);
    result.multiRole = { primary: multiMe.doc.roleKey, roles: multiMe.doc.roleKeys, firstQuestion: true };
    await page.evaluate(() => { localStorage.removeItem('bp_token'); sessionStorage.clear(); });

    await page.goto(config.base + '/', { waitUntil: 'load' });
    await page.locator('#f-name').fill('Персональные вопросы');
    await page.locator('#f-dept').selectOption('mgmt');
    await chooseRoles(page, ['14']);
    await page.locator('#f-pos').fill('Руководитель компании');
    await page.locator('#f-about').fill('Готовлю отчёты по результатам компании и отслеживаю выполнение целей.');
    await page.locator('#f-consent').check();
    await page.locator('#start-btn').click();
    await page.locator('.msg.a .txt').first().waitFor({ state: 'visible' });
    const personalMe = await page.evaluate(async () => {
      const response = await fetch('/api/me', { headers: { Authorization: 'Bearer ' + localStorage.getItem('bp_token') } });
      return response.json();
    });
    if (personalMe.doc.messages[0].questionKey !== '14-02') throw new Error('Персонализация: первый вопрос ' + personalMe.doc.messages[0].questionKey);
    if (!personalMe.doc.aboutAnalysis.activities.length) throw new Error('Персонализация: нет занятий');
    ids.push(personalMe.doc.id);
    result.aboutPriority = { firstQuestion: personalMe.doc.messages[0].questionKey, activities: personalMe.doc.aboutAnalysis.activities.length };
    await page.evaluate(() => { localStorage.removeItem('bp_token'); sessionStorage.clear(); });

    await page.goto(config.base + '/', { waitUntil: 'load' });
    await page.getByRole('button', { name: 'RO', exact: true }).click();
    await page.locator('#f-name').fill('Test RO');
    await page.locator('#f-dept').selectOption('quality');
    await chooseRoles(page, ['20']);
    await page.locator('#f-pos').fill('Calitate');
    await page.locator('#f-consent').check();
    await page.locator('#start-btn').click();
    await page.locator('.msg.a .txt').first().waitFor({ state: 'visible' });
    const romanian = await page.locator('.msg.a .txt').first().innerText();
    if (!romanian.includes(packs['20'].questions[0].ro)) throw new Error('RO: неверный первый вопрос: ' + romanian);
    const roMe = await page.evaluate(async () => {
      const response = await fetch('/api/me', { headers: { Authorization: 'Bearer ' + localStorage.getItem('bp_token') } });
      return response.json();
    });
    ids.push(roMe.doc.id);
    result.romanian = { firstQuestion: true, questionKey: roMe.doc.messages[0].questionKey };

    await page.evaluate(() => { localStorage.removeItem('bp_token'); sessionStorage.clear(); });
    await page.goto(config.base + '/', { waitUntil: 'load' });
    await page.locator('#f-name').fill('Полная анкета');
    await page.locator('#f-dept').selectOption('other');
    await chooseRoles(page, ['00']);
    await page.locator('#f-pos').fill('Универсальная роль');
    await page.locator('#f-consent').check();
    await page.locator('#start-btn').click();
    await page.locator('#answer').waitFor({ state: 'visible' });
    const fullMe = await page.evaluate(async () => {
      const response = await fetch('/api/me', { headers: { Authorization: 'Bearer ' + localStorage.getItem('bp_token') } });
      return response.json();
    });
    ids.push(fullMe.doc.id);
    for (let index = 0; index < 25; index++) {
      if (await page.locator('.done-view').isVisible()) break;
      await page.locator('#answer').fill('Тестовый ответ с фактическим процессом и документом');
      await page.locator('#send').click();
      await page.waitForTimeout(60);
    }
    const probeResponse = await fetch(config.base + '/api/admin/interviews', { headers: { 'X-Admin-Key': config.admin } });
    const probeData = await probeResponse.json();
    const probeDoc = probeData.interviews.find(item => item.id === fullMe.doc.id);
    result.fullProbe = probeDoc && { status: probeDoc.status, script: probeDoc.script, messages: probeDoc.messages.length, body: await page.locator('body').innerText() };
    await page.locator('.done-view').waitFor({ state: 'visible', timeout: 5000 });
    const adminResponse = await fetch(config.base + '/api/admin/interviews', { headers: { 'X-Admin-Key': config.admin } });
    if (!adminResponse.ok) throw new Error('Полная анкета: нет доступа администратора');
    const adminData = await adminResponse.json();
    const fullDoc = adminData.interviews.find(item => item.id === fullMe.doc.id);
    if (!fullDoc) throw new Error('Полная анкета: интервью не найдено');
    const asked = new Set(fullDoc.messages.filter(item => item.questionKey).map(item => item.questionKey));
    for (const question of packs['00'].questions) if (!asked.has(question.id)) throw new Error('Полная анкета: пропущен ' + question.id);
    if (fullDoc.status !== 'done') throw new Error('Полная анкета: статус ' + fullDoc.status);
    result.fullScript = { completed: true, baseQuestions: asked.size, status: fullDoc.status };
    if (result.errors.length) throw new Error('Ошибки JavaScript: ' + result.errors.join(' | '));
  } catch (error) {
    result.fatal = String(error && error.stack || error);
    process.exitCode = 1;
  } finally {
    if (browser) await browser.close();
    for (const id of ids) {
      try {
        const response = await fetch(config.base + '/api/admin/interviews/' + id, { method: 'DELETE', headers: { 'X-Admin-Key': config.admin } });
        result.cleanup.push({ id, status: response.status });
        if (!response.ok) process.exitCode = 1;
      } catch (error) {
        result.cleanup.push({ id, error: String(error) });
        process.exitCode = 1;
      }
    }
    fs.writeFileSync(path.join(root, 'run/browser_role_packs-result.json'), JSON.stringify(result, null, 2) + '\n');
    console.log(JSON.stringify({ roles: Object.keys(result.roles).length, romanian: result.romanian, errors: result.errors, fatal: result.fatal, cleanup: result.cleanup.length }, null, 2));
  }
})();
