const { webkit } = require('playwright');
const fs = require('fs');
const path = require('path');

const root = path.resolve(__dirname, '..');
const config = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const result = { browser: 'webkit', checks: {}, errors: [], cleanup: [] };
let interviewId = null;

function check(name, value) {
  result.checks[name] = Boolean(value);
  if (!value) throw new Error(name);
}

(async () => {
  let browser;
  try {
    browser = await webkit.launch({ headless: true });
    const context = await browser.newContext({
      viewport: { width: 390, height: 844 }, screen: { width: 390, height: 844 },
      deviceScaleFactor: 3, isMobile: true, hasTouch: true, locale: 'ru-RU', acceptDownloads: true,
    });
    const page = await context.newPage();
    page.on('pageerror', error => result.errors.push(String(error)));
    page.on('console', message => { if (message.type() === 'error') result.errors.push(message.text()); });
    let ui = page;
    const survey = () => config.stableUrl ? page.frames().find(frame => frame.url().startsWith(config.base)) : page;
    if (config.stableUrl) ui = page.frameLocator('#app');
    await page.goto(config.stableUrl || config.base + '/', { waitUntil: 'load', timeout: 60000 });
    await ui.locator('#f-name').waitFor({ state: 'visible', timeout: 60000 });
    await ui.locator('#f-name').fill('Проверка базы знаний');
    await ui.locator('#f-dept').selectOption('other');
    await ui.locator('#f-pos').fill('Временный тест');
    await ui.locator('#f-consent').check();
    await ui.locator('#start-btn').click();
    await ui.locator('#answer').waitFor({ state: 'visible', timeout: 60000 });
    interviewId = await survey().evaluate(async () => {
      const response = await fetch('/api/me', { headers: { Authorization: 'Bearer ' + localStorage.getItem('bp_token') } });
      return (await response.json()).doc.id;
    });

    await ui.locator('#file-input').setInputFiles([
      path.join(root, 'tests/fixtures/process-template.xlsx'),
      path.join(root, 'tests/fixtures/batch-instruction.docx'),
    ]);
    await survey().waitForFunction(() => document.querySelectorAll('#attach-list .attachment-chip').length === 2, null, { timeout: 60000 });
    await ui.locator('#answer').fill('Прикладываю шаблон проверки серии и инструкцию');
    await ui.locator('#send').click();
    await survey().waitForFunction(() => document.querySelectorAll('.msg.a:not(.pending) .txt').length >= 2 && !document.querySelector('#send').disabled, null, { timeout: 120000 });
    check('next_question_after_analysis', await ui.locator('#answer').isVisible());
    result.analysisProbe = await survey().evaluate(() => ({
      text: document.querySelector('#attach-progress-text').textContent,
      hidden: document.querySelector('#attach-panel').hidden,
      mode: document.querySelector('#send').disabled,
      body: document.querySelector('.composer').innerText,
    }));
    check('analysis_feedback_visible', (await ui.locator('#attach-progress-text').innerText()).match(/базу знаний|сохранены|проверки/i) !== null);
    const me = await survey().evaluate(async () => {
      const response = await fetch('/api/me', { headers: { Authorization: 'Bearer ' + localStorage.getItem('bp_token') } });
      return response.json();
    });
    check('answer_keeps_both_attachments', me.doc.messages.some(message => message.role === 'user' && (message.attachmentIds || []).length === 2));

    const admin = await context.newPage();
    admin.on('pageerror', error => result.errors.push(String(error)));
    admin.on('console', message => { if (message.type() === 'error') result.errors.push(message.text()); });
    await admin.goto(config.base + '/admin', { waitUntil: 'load', timeout: 60000 });
    await admin.locator('#adm-pw').fill(config.admin);
    await admin.locator('button[type="submit"]').click();
    await admin.getByRole('tab', { name: /База знаний/ }).click();
    await admin.locator('.knowledge-card').first().waitFor({ state: 'visible', timeout: 60000 });
    check('knowledge_cards_visible', await admin.locator('.knowledge-card').count() >= 2);
    const cardsText = await admin.locator('.knowledge-grid').innerText();
    check('source_documents_visible', cardsText.includes('process-template.xlsx') && cardsText.includes('batch-instruction.docx'));
    check('analysis_fields_visible', cardsText.includes('Артикул'));
    const statuses = await admin.evaluate(async id => {
      const response = await fetch('/api/admin/knowledge', { headers: { 'X-Admin-Key': sessionStorage.getItem('bp_admin') } });
      const data = await response.json();
      return data.items.filter(item => item.interviewId === id).map(item => item.status);
    }, interviewId);
    result.knowledgeStatuses = statuses;
    check('analysis_finished', statuses.length === 2 && statuses.every(status => status === 'ready' || status === 'extracted'));

    await admin.locator('#knowledge-q').fill('process-template.xlsx');
    await admin.locator('form.toolbar button[type="submit"]').click();
    await admin.waitForFunction(() => document.querySelectorAll('.knowledge-card').length === 1, null, { timeout: 30000 });
    check('search_finds_excel_by_field', (await admin.locator('.knowledge-grid').innerText()).includes('process-template.xlsx'));
    check('search_filters_other_document', !(await admin.locator('.knowledge-grid').innerText()).includes('batch-instruction.docx'));
    await admin.locator('.knowledge-card details summary').click();
    check('raw_text_available_for_verification', (await admin.locator('.knowledge-card').innerText()).includes('BAL-001'));
    await admin.screenshot({ path: path.join(root, 'run/knowledge-browser-admin.png'), fullPage: false });
    check('no_javascript_errors', result.errors.length === 0);
  } catch (error) {
    result.fatal = String(error && error.stack || error);
    process.exitCode = 1;
  } finally {
    if (browser) await browser.close();
    if (interviewId) {
      try {
        const response = await fetch(config.base + '/api/admin/interviews/' + interviewId, { method: 'DELETE', headers: { 'X-Admin-Key': config.admin } });
        result.cleanup.push({ id: interviewId, status: response.status });
        if (!response.ok) process.exitCode = 1;
      } catch (error) {
        result.cleanup.push({ id: interviewId, error: String(error) });
        process.exitCode = 1;
      }
    }
    fs.writeFileSync(path.join(root, 'run/browser_knowledge-result.json'), JSON.stringify(result, null, 2) + '\n');
    console.log(JSON.stringify(result, null, 2));
  }
})();
