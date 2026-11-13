const { webkit } = require('playwright');
const fs = require('fs');
const path = require('path');

const root = path.resolve(__dirname, '..');
const stableUrl = 'https://dmitriimalahov-gif.github.io/balkan-opros/';
const cfg = JSON.parse(fs.readFileSync(path.join(root, 'pages/current.json'), 'utf8'));
const output = {
  browser: 'webkit',
  stableUrl,
  stages: {},
  errors: [],
  cleanup: null,
};

async function metrics(frame) {
  return frame.evaluate(() => {
    const main = document.querySelector('#main');
    const bar = document.querySelector('#bar');
    const chat = document.querySelector('.chat');
    const composer = document.querySelector('.composer');
    const rect = el => {
      if (!el) return null;
      const r = el.getBoundingClientRect();
      return { top: r.top, bottom: r.bottom, height: r.height };
    };
    return {
      href: location.href,
      viewport: { width: innerWidth, height: innerHeight },
      scroll: { x: scrollX, y: scrollY },
      document: {
        clientHeight: document.documentElement.clientHeight,
        scrollHeight: document.documentElement.scrollHeight,
        bodyScrollHeight: document.body.scrollHeight,
      },
      active: document.activeElement && document.activeElement.id,
      text: document.body.innerText.slice(0, 1000),
      rects: { bar: rect(bar), main: rect(main), chat: rect(chat), composer: rect(composer) },
    };
  });
}

(async () => {
  let browser;
  let interviewId;
  try {
    browser = await webkit.launch({ headless: true });
    const context = await browser.newContext({
      viewport: { width: 390, height: 844 },
      screen: { width: 390, height: 844 },
      deviceScaleFactor: 3,
      isMobile: true,
      hasTouch: true,
      userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1',
      locale: 'ru-RU',
      ignoreHTTPSErrors: false,
    });
    const page = await context.newPage();
    page.on('pageerror', error => output.errors.push(String(error)));
    page.on('console', message => {
      if (message.type() === 'error') output.errors.push('console: ' + message.text());
    });
    await page.goto(stableUrl + '?webkit-repro=' + Date.now(), { waitUntil: 'load', timeout: 60000 });
    const app = page.frameLocator('#app');
    await app.locator('#f-name').waitFor({ state: 'visible', timeout: 60000 });
    const frame = page.frames().find(f => f.url().startsWith(cfg.url));
    if (!frame) throw new Error('Не найден frame опросника');
    output.stages.welcome = await metrics(frame);
    await page.screenshot({ path: path.join(root, 'run/mobile-webkit-welcome.png'), fullPage: false });

    await app.locator('#f-name').fill('Тест мобильной вёрстки');
    await app.locator('#f-dept').selectOption('it');
    await app.locator('#f-pos').fill('Временная автопроверка');
    await app.locator('#f-consent').check();
    await app.locator('#start-btn').click();
    await app.locator('#answer').waitFor({ state: 'attached', timeout: 30000 });
    output.stages.chatImmediate = await metrics(frame);
    await page.screenshot({ path: path.join(root, 'run/mobile-webkit-chat-immediate.png'), fullPage: false });
    await page.waitForTimeout(1200);
    output.stages.chatAfter1200ms = await metrics(frame);
    await page.screenshot({ path: path.join(root, 'run/mobile-webkit-chat-1200ms.png'), fullPage: false });

    await app.locator('#answer').fill('Отвечаю за учёт рабочего времени и ежедневные отчёты в Excel.');
    await app.locator('#send').click();
    output.stages.thinkingImmediate = await metrics(frame);
    await page.screenshot({ path: path.join(root, 'run/mobile-webkit-thinking-immediate.png'), fullPage: false });
    await page.waitForTimeout(1200);
    output.stages.thinkingAfter1200ms = await metrics(frame);
    await page.screenshot({ path: path.join(root, 'run/mobile-webkit-thinking-1200ms.png'), fullPage: false });

    await frame.evaluate(() => window.scrollTo({ top: 0, behavior: 'instant' }));
    await page.waitForTimeout(300);
    output.stages.thinkingAfterScrollTop = await metrics(frame);
    await page.screenshot({ path: path.join(root, 'run/mobile-webkit-thinking-scroll-top.png'), fullPage: false });

    const state = await frame.evaluate(() => ({ id: null }));
    const meResponse = await frame.evaluate(async () => {
      const token = localStorage.getItem('bp_token');
      if (!token) return null;
      const response = await fetch('/api/me', { headers: { Authorization: 'Bearer ' + token } });
      if (!response.ok) return null;
      return response.json();
    });
    interviewId = meResponse && meResponse.doc && meResponse.doc.id;
    output.interviewCreated = Boolean(interviewId);
    output.stateProbe = state;
  } catch (error) {
    output.fatal = String(error && error.stack || error);
  } finally {
    if (browser) await browser.close();
    if (interviewId) {
      try {
        const admin = fs.readFileSync(path.join(root, 'ADMIN_PASSWORD.txt'), 'utf8').trim();
        const response = await fetch(cfg.url + '/api/admin/interviews/' + encodeURIComponent(interviewId), {
          method: 'DELETE',
          headers: { 'X-Admin-Key': admin },
        });
        output.cleanup = { attempted: true, status: response.status, ok: response.ok };
      } catch (error) {
        output.cleanup = { attempted: true, ok: false, error: String(error) };
      }
    }
    fs.writeFileSync(path.join(root, 'run/mobile-webkit-repro.json'), JSON.stringify(output, null, 2) + '\n');
    console.log(JSON.stringify(output, null, 2));
  }
})();
