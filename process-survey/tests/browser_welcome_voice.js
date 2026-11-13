const { webkit } = require('playwright');
const fs = require('fs');
const path = require('path');

const root = path.resolve(__dirname, '..');
const config = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const result = { browser: 'webkit', checks: {}, errors: [], httpErrors: [], requests: [], cleanup: [] };
let interviewId = null;
let welcomeDelay = 1400;

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
      deviceScaleFactor: 3, isMobile: true, hasTouch: true, locale: 'ru-RU',
    });
    await context.addInitScript(() => {
      window.__welcomeAudio = [];
      window.Audio = class {
        constructor() { this.playCount = 0; this.pauseCount = 0; this.src = ''; window.__welcomeAudio.push(this); }
        play() { this.playCount++; if (this.onplay) this.onplay(); return Promise.resolve(); }
        pause() { this.pauseCount++; }
      };
    });
    const page = await context.newPage();
    page.on('pageerror', error => result.errors.push(String(error)));
    page.on('console', message => { if (message.type() === 'error') result.errors.push(message.text()); });
    page.on('response', response => { if (response.status() >= 400) result.httpErrors.push(response.status() + ' ' + response.url()); });
    await page.route('**/api/config', async route => {
      const response = await route.fetch();
      const data = await response.json(); data.ai = false; data.ownerVoice = true;
      await route.fulfill({ response, json: data });
    });
    await page.route('**/api/welcome-voice?*', async route => {
      const lang = new URL(route.request().url()).searchParams.get('lang');
      result.requests.push({ lang, at: Date.now() });
      if (welcomeDelay) await new Promise(resolve => setTimeout(resolve, welcomeDelay));
      await route.fulfill({ status: 200, contentType: 'audio/mp4', body: Buffer.from('welcome-owner-voice-' + lang) });
    });
    const ui = () => config.stableUrl ? page.frameLocator('#app') : page;
    const survey = () => config.stableUrl ? page.frames().find(frame => frame.url().startsWith(config.base)) : page;
    const audio = () => survey().evaluate(() => window.__welcomeAudio.map(item => ({ plays: item.playCount, pauses: item.pauseCount, src: item.src })));
    const waitAudio = async count => {
      await survey().waitForFunction(expected => window.__welcomeAudio.filter(item => item.playCount > 0).length >= expected, count, { timeout: 15000 });
    };

    const started = Date.now();
    await page.goto(config.stableUrl || config.base + '/', { waitUntil: 'load', timeout: 60000 });
    await ui().locator('#f-name').waitFor({ state: 'visible', timeout: 60000 });
    check('no_audio_before_two_seconds', (await audio()).length === 0 && result.requests.length === 0);
    await page.waitForTimeout(2200);
    check('welcome_preparing_visible', (await ui().locator('#welcome-voice-status').innerText()).includes('Готовлю голос руководителя'));
    await waitAudio(1);
    result.firstDelayMs = Date.now() - started;
    check('welcome_autoplays_after_two_seconds', result.firstDelayMs >= 1800);
    check('russian_welcome_requested', result.requests.length === 1 && result.requests[0].lang === 'ru');
    check('welcome_audio_is_blob', (await audio())[0].src.startsWith('blob:'));
    welcomeDelay = 0;

    await ui().locator('#voice-toggle').click();
    check('welcome_stop_button_pauses_audio', (await audio())[0].pauses === 1);
    const manualStarted = Date.now();
    await ui().locator('#voice-toggle').click();
    await waitAudio(2);
    check('manual_welcome_replay_is_immediate', Date.now() - manualStarted < 1800 && result.requests.length === 2);

    const romanianStarted = Date.now();
    await ui().getByRole('button', { name: 'RO', exact: true }).click();
    await waitAudio(3);
    check('romanian_welcome_after_two_seconds', Date.now() - romanianStarted >= 1800 && result.requests[2].lang === 'ro');
    await page.screenshot({ path: path.join(root, 'run/welcome-voice-mobile.png'), fullPage: false });
    await ui().locator('#voice-toggle').click();
    await ui().locator('#voice-toggle').click();

    await ui().locator('#f-name').fill('Проверка приветствия');
    await ui().locator('#f-dept').selectOption('other');
    await ui().locator('#f-pos').fill('Временный тест');
    await ui().locator('#f-consent').check();
    await ui().locator('#start-btn').click();
    await ui().locator('#answer').waitFor({ state: 'visible', timeout: 60000 });
    interviewId = await survey().evaluate(async () => {
      const response = await fetch('/api/me', { headers: { Authorization: 'Bearer ' + localStorage.getItem('bp_token') } });
      return (await response.json()).doc.id;
    });
    const requestsAtStart = result.requests.length;
    await page.waitForTimeout(2200);
    check('welcome_stops_when_interview_starts', result.requests.length === requestsAtStart && (await audio()).length === 3 && (await audio())[2].pauses >= 1);
    check('mobile_no_horizontal_overflow', await survey().evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1));
    check('no_javascript_errors', result.errors.length === 0);
    check('no_http_errors', result.httpErrors.length === 0);
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
    fs.writeFileSync(path.join(root, 'run/browser_welcome_voice-result.json'), JSON.stringify(result, null, 2) + '\n');
    console.log(JSON.stringify(result, null, 2));
  }
})();
