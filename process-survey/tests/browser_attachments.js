const { webkit } = require('playwright');
const fs = require('fs');
const path = require('path');

const root = path.resolve(__dirname, '..');
const config = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const result = { browser: 'webkit', viewport: '390x844', checks: {}, errors: [] };

function check(name, condition) {
  result.checks[name] = Boolean(condition);
  if (!condition) throw new Error('Проверка не пройдена: ' + name);
}

(async () => {
  let browser;
  try {
    browser = await webkit.launch({ headless: true });
    const context = await browser.newContext({
      viewport: { width: 390, height: 844 },
      screen: { width: 390, height: 844 },
      deviceScaleFactor: 3,
      isMobile: true,
      hasTouch: true,
      locale: 'ru-RU',
      acceptDownloads: true,
      userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1',
    });
    const page = await context.newPage();
    page.on('pageerror', error => result.errors.push(String(error)));
    page.on('console', message => { if (message.type() === 'error') result.errors.push(message.text()); });
    let ui = page;
    const getSurvey = () => config.stableUrl ? page.frames().find(frame => frame.url().startsWith(config.base)) : page;
    await page.goto(config.stableUrl || config.base + '/', { waitUntil: 'load', timeout: 60000 });
    if (config.stableUrl) {
      ui = page.frameLocator('#app');
      result.stableUrl = config.stableUrl;
    }
    await ui.locator('#f-name').waitFor({ state: 'visible', timeout: 60000 });
    let survey = getSurvey();
    check('survey_frame_loaded', Boolean(survey));
    await ui.locator('#f-name').fill('Автопроверка вложений');
    await ui.locator('#f-dept').selectOption('it');
    await ui.locator('#f-pos').fill('Временный тест');
    await ui.locator('#f-consent').check();
    await ui.locator('#start-btn').click();
    await ui.locator('#answer').waitFor({ state: 'visible' });
    check('chat_visible_without_pull', await ui.locator('.chat').isVisible());
    check('no_touch_autofocus', await survey.evaluate(() => document.activeElement.id !== 'answer'));
    result.interviewId = await survey.evaluate(async () => {
      const response = await fetch('/api/me', { headers: { Authorization: 'Bearer ' + localStorage.getItem('bp_token') } });
      const data = await response.json();
      return data.doc && data.doc.id;
    });

    await survey.evaluate(() => {
      window.__uploadPercents = [];
      const progress = document.querySelector('#attach-progress');
      new MutationObserver(() => {
        const value = Number(progress.getAttribute('aria-valuenow'));
        if (window.__uploadPercents[window.__uploadPercents.length - 1] !== value) window.__uploadPercents.push(value);
      }).observe(progress, { attributes: true, attributeFilter: ['aria-valuenow'] });
    });
    await page.route('**/api/me/attachments/chunk?*', async route => {
      await new Promise(resolve => setTimeout(resolve, 450));
      await route.continue();
    });
    const excel = Buffer.from('browser-excel-attachment');
    await ui.locator('#file-input').setInputFiles([
      { name: 'шаблон.xlsx', mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', buffer: excel },
      { name: 'фото.png', mimeType: 'image/png', buffer: Buffer.alloc(12 * 1024 * 1024, 7) },
    ]);
    await page.waitForTimeout(1200);
    result.progressProbe = await survey.evaluate(() => ({
      percent: document.querySelector('#attach-progress').getAttribute('aria-valuenow'),
      progress: document.querySelector('#attach-progress-text').textContent,
      error: document.querySelector('#attach-err').textContent,
      files: document.querySelectorAll('#attach-list .attachment-chip').length,
    }));
    await survey.waitForFunction(() => document.querySelectorAll('#attach-list .attachment-chip').length === 2, null, { timeout: 90000 });
    const percents = await survey.evaluate(() => window.__uploadPercents);
    result.uploadPercents = percents;
    check('live_progress_changes_between_chunks', percents.some(value => value > 0 && value < 100));
    check('live_progress_reaches_100', percents.includes(100));
    check('progress_hides_after_upload', await ui.locator('#attach-progress').isHidden());
    await ui.locator('#attach-link').click();
    await ui.locator('#sheet-url').fill('https://docs.google.com/spreadsheets/d/browser-test/edit#gid=0');
    await ui.locator('#attach-link-add').click();
    await survey.waitForFunction(() => document.querySelectorAll('#attach-list .attachment-chip').length === 3);
    check('three_materials_visible', await ui.locator('#attach-list').innerText().then(text => text.includes('шаблон.xlsx') && text.includes('фото.png') && text.includes('Google Таблица')));
    await page.screenshot({ path: path.join(root, 'run/attachment-mobile-before-send.png'), fullPage: false });

    await page.reload({ waitUntil: 'load', timeout: 60000 });
    await ui.getByRole('button', { name: 'Продолжить', exact: true }).click();
    await ui.locator('#answer').waitFor({ state: 'visible' });
    survey = getSurvey();
    await survey.waitForFunction(() => document.querySelectorAll('#attach-list .attachment-chip').length === 3);
    check('pending_materials_restore', true);
    const me = await survey.evaluate(async () => {
      const response = await fetch('/api/me', { headers: { Authorization: 'Bearer ' + localStorage.getItem('bp_token') } });
      return response.json();
    });
    result.interviewId = me.doc.id;
    await ui.locator('#answer').fill('');
    await ui.locator('#send').click();
    await survey.waitForFunction(() => document.querySelectorAll('.msg.u .attachment-chip').length === 3);
    check('attachment_only_answer_sent', true);
    await ui.locator('#attach-panel').waitFor({ state: 'visible', timeout: 60000 });
    check('next_question_visible', await ui.locator('#answer').isVisible());
    const saved = await survey.evaluate(async () => {
      const response = await fetch('/api/me', { headers: { Authorization: 'Bearer ' + localStorage.getItem('bp_token') } });
      return response.json();
    });
    check('answer_links_three_ids', saved.doc.messages.some(message => message.role === 'user' && (message.attachmentIds || []).length === 3));
    check('metadata_bound_to_answer', saved.doc.attachments.filter(item => item.messageIndex != null).length === 3);

    const admin = await context.newPage();
    admin.on('pageerror', error => result.errors.push(String(error)));
    await admin.goto(config.base + '/admin', { waitUntil: 'load' });
    await admin.locator('#adm-pw').fill(config.admin);
    await admin.locator('button[type="submit"]').click();
    await admin.getByText('Автопроверка вложений', { exact: true }).click();
    await admin.locator('.attachments-admin').waitFor({ state: 'visible' });
    check('admin_materials_visible', (await admin.locator('.attachments-admin .attachment-chip').count()) === 3);
    const downloadPromise = admin.waitForEvent('download');
    await admin.locator('.attachments-admin .attachment-open').first().click();
    const download = await downloadPromise;
    const downloaded = path.join(root, 'run/attachment-browser-download.xlsx');
    await download.saveAs(downloaded);
    check('admin_download_bytes_match', fs.readFileSync(downloaded).equals(excel));

    const deleted = await admin.evaluate(async id => {
      const response = await fetch('/api/admin/interviews/' + id, { method: 'DELETE', headers: { 'X-Admin-Key': sessionStorage.getItem('bp_admin') } });
      return response.status;
    }, result.interviewId);
    check('temporary_interview_deleted', deleted === 200);
    check('no_javascript_errors', result.errors.length === 0);
  } catch (error) {
    result.fatal = String(error && error.stack || error);
    process.exitCode = 1;
  } finally {
    if (browser) await browser.close();
    if (result.interviewId && !result.checks.temporary_interview_deleted) {
      try {
        const response = await fetch(config.base + '/api/admin/interviews/' + result.interviewId, { method: 'DELETE', headers: { 'X-Admin-Key': config.admin } });
        result.cleanup = { attempted: true, status: response.status, ok: response.ok };
        if (!response.ok) process.exitCode = 1;
      } catch (error) {
        result.cleanup = { attempted: true, ok: false, error: String(error) };
        process.exitCode = 1;
      }
    }
    fs.writeFileSync(path.join(root, 'run/attachment-browser-result.json'), JSON.stringify(result, null, 2) + '\n');
    console.log(JSON.stringify(result, null, 2));
  }
})();
