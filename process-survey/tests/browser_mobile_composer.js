const { webkit } = require('playwright');
const fs = require('fs');
const path = require('path');
const root = path.resolve(__dirname, '..');
const config = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const result = { checks: {}, errors: [], cleanup: [] };
let interviewId = null;
function check(name, value) { result.checks[name] = Boolean(value); if (!value) throw new Error(name); }
(async () => {
  let browser;
  try {
    browser = await webkit.launch({ headless: true });
    const context = await browser.newContext({ viewport: { width: 390, height: 844 }, screen: { width: 390, height: 844 }, isMobile: true, hasTouch: true, deviceScaleFactor: 3, locale: 'ru-RU' });
    await context.addInitScript(() => {
      const original = window.scrollTo;
      window.__scrollCalls = [];
      window.scrollTo = function (options) { window.__scrollCalls.push(options); return original.call(window, options); };
    });
    const page = await context.newPage();
    page.on('pageerror', error => result.errors.push(String(error)));
    page.on('console', message => { if (message.type() === 'error') result.errors.push(message.text()); });
    await page.route('**/api/config', async route => {
      const response = await route.fetch();
      const data = await response.json(); data.ai = true;
      await route.fulfill({ response, json: data });
    });
    await page.route('**/api/me/turn', async route => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ text: '[[2]] [[Q:00-02]] Какой результат вашей работы нужно видеть руководителю?\n[[OPTIONS many: Отчёт | Подпись | Серия | Спецификация | Протокол | Excel | Журнал | Ошибка]]' }) });
    });
    const ui = () => config.stableUrl ? page.frameLocator('#app') : page;
    const survey = () => config.stableUrl ? page.frames().find(frame => frame.url().startsWith(config.base)) : page;
    await page.goto(config.stableUrl || config.base + '/', { waitUntil: 'load', timeout: 60000 });
    await ui().locator('#f-name').fill('Мобильный компоновщик');
    await ui().locator('#f-dept').selectOption('other');
    await ui().locator('#f-pos').fill('Временный тест');
    await ui().locator('#f-consent').check();
    await ui().locator('#start-btn').click();
    await ui().locator('#answer').waitFor({ state: 'visible', timeout: 60000 });
    interviewId = await survey().evaluate(async () => {
      const response = await fetch('/api/me', { headers: { Authorization: 'Bearer ' + localStorage.getItem('bp_token') } });
      return (await response.json()).doc.id;
    });
    await survey().evaluate(async () => {
      const token = localStorage.getItem('bp_token');
      const response = await fetch('/api/me', { headers: { Authorization: 'Bearer ' + token } });
      const data = await response.json();
      data.doc.mode = 'ai';
      await fetch('/api/me', { method: 'PUT', headers: { Authorization: 'Bearer ' + token, 'Content-Type': 'application/json' }, body: JSON.stringify({ doc: data.doc }) });
    });
    await page.reload({ waitUntil: 'load', timeout: 60000 });
    await ui().getByRole('button', { name: 'Продолжить', exact: true }).click();
    await ui().locator('#answer').waitFor({ state: 'visible', timeout: 60000 });
    await ui().locator('#answer').fill('Проверяю серии и документы');
    await ui().locator('#send').click();
    await ui().locator('#opts .opt').nth(7).waitFor({ state: 'visible', timeout: 30000 });
    await page.waitForTimeout(200);
    result.layout = await survey().evaluate(() => {
      const composer = document.querySelector('.composer');
      const questions = document.querySelectorAll('.msg.a:not(.pending) .txt');
      const question = questions[questions.length - 1];
      const composerRect = composer.getBoundingClientRect();
      const questionRect = question.getBoundingClientRect();
      return {
        viewportHeight: window.innerHeight,
        composerHeight: composerRect.height,
        composerTop: composerRect.top,
        questionBottom: questionRect.bottom,
        questionTop: questionRect.top,
        scrollHeight: composer.scrollHeight,
        clientHeight: composer.clientHeight,
        overflowY: getComputedStyle(composer).overflowY,
        scrollY: window.scrollY,
        scrollCalls: window.__scrollCalls,
        barHeight: document.querySelector('#bar').getBoundingClientRect().height,
        documentHeight: document.documentElement.scrollHeight,
        lastChildClass: document.querySelector('#log').lastElementChild.className,
        questionVisible: questionRect.top >= 0 && questionRect.bottom <= composerRect.top + 1,
      };
    });
    check('composer_height_limited', result.layout.composerHeight <= result.layout.viewportHeight * 0.52 + 2);
    check('question_visible_above_composer', result.layout.questionVisible);
    check('composer_scrollable', result.layout.scrollHeight > result.layout.clientHeight && result.layout.overflowY === 'auto');
    await survey().evaluate(() => { document.querySelector('.composer').scrollTop = document.querySelector('.composer').scrollHeight; });
    check('send_visible_after_internal_scroll', await ui().locator('#send').isVisible());
    await page.screenshot({ path: path.join(root, 'run/mobile-composer-options.png'), fullPage: false });
    check('no_javascript_errors', result.errors.length === 0);
  } catch (error) {
    result.fatal = String(error && error.stack || error);
    process.exitCode = 1;
  } finally {
    if (browser) await browser.close();
    if (interviewId) {
      const response = await fetch(config.base + '/api/admin/interviews/' + interviewId, { method: 'DELETE', headers: { 'X-Admin-Key': config.admin } });
      result.cleanup.push({ id: interviewId, status: response.status });
      if (!response.ok) process.exitCode = 1;
    }
    fs.writeFileSync(path.join(root, 'run/browser_mobile_composer-result.json'), JSON.stringify(result, null, 2) + '\n');
    console.log(JSON.stringify(result, null, 2));
  }
})();
