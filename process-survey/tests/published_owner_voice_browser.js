const { webkit } = require('playwright');
const fs = require('fs');
const path = require('path');

const root = path.resolve(__dirname, '..');
const current = JSON.parse(fs.readFileSync(path.join(root, 'pages/current.json'), 'utf8'));
const base = current.url.replace(/\/$/, '');
const stableUrl = 'https://dmitriimalahov-gif.github.io/balkan-opros/';
const admin = fs.readFileSync(path.join(root, 'ADMIN_PASSWORD.txt'), 'utf8').trim();
const result = { browser: 'webkit-real-audio', checks: {}, playback: {}, errors: [], cleanup: [] };
const ids = [];

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
      const NativeAudio = window.Audio;
      window.__ownerAudio = [];
      window.Audio = function (...args) {
        const audio = new NativeAudio(...args);
        window.__ownerAudio.push(audio);
        return audio;
      };
      window.Audio.prototype = NativeAudio.prototype;
    });
    const page = await context.newPage();
    page.on('pageerror', error => result.errors.push(String(error)));
    page.on('console', message => { if (message.type() === 'error') result.errors.push(message.text()); });
    await page.route('**/api/config', async route => {
      const response = await route.fetch();
      const data = await response.json();
      data.ai = false;
      await route.fulfill({ response, json: data });
    });
    const ui = () => page.frameLocator('#app');
    const survey = () => page.frames().find(frame => frame.url().startsWith(base));
    const getMe = () => survey().evaluate(async () => {
      const response = await fetch('/api/me', { headers: { Authorization: 'Bearer ' + localStorage.getItem('bp_token') } });
      return response.json();
    });
    const waitPlaying = async lang => {
      const ready = page.waitForResponse(response => response.url().includes('/api/me/voice/') && response.status() === 200, { timeout: 120000 });
      await ready;
      try {
        await survey().waitForFunction(() => window.__ownerAudio.some(audio => !audio.paused && audio.currentTime > 0), null, { timeout: 5000 });
      } catch (_) {
        const toast = await ui().locator('#toast').innerText();
        if (!toast.includes('Нажмите динамик') && !toast.includes('Apăsați difuzorul')) throw new Error('Audio did not start: ' + toast);
        await ui().locator('.msg-voice').last().click();
        await survey().waitForFunction(() => window.__ownerAudio.some(audio => !audio.paused && audio.currentTime > 0), null, { timeout: 15000 });
      }
      const playback = await survey().evaluate(() => {
        const audio = window.__ownerAudio.find(item => !item.paused && item.currentTime > 0) || window.__ownerAudio[window.__ownerAudio.length - 1];
        return audio && { duration: audio.duration, currentTime: audio.currentTime, src: audio.src, paused: audio.paused };
      });
      check(lang + '_real_m4a_playing', playback && playback.duration > 0 && playback.currentTime > 0 && playback.src.startsWith('blob:'));
      result.playback[lang] = playback;
    };
    const waitWelcome = async (lang, trigger, disableAfter) => {
      const ready = page.waitForResponse(response => response.url().includes('/api/welcome-voice') && response.url().includes('lang=' + lang) && response.status() === 200, { timeout: 120000 });
      const started = Date.now();
      await trigger();
      await ready;
      try {
        await survey().waitForFunction(() => window.__ownerAudio.some(audio => !audio.paused && audio.currentTime > 0), null, { timeout: 5000 });
      } catch (_) {
        const toast = await ui().locator('#toast').innerText();
        if (!toast.includes('Нажмите динамик') && !toast.includes('Apăsați difuzorul')) throw new Error('Welcome did not start: ' + toast);
        await ui().locator('#voice-toggle').click();
        await survey().waitForFunction(() => window.__ownerAudio.some(audio => !audio.paused && audio.currentTime > 0), null, { timeout: 15000 });
      }
      const playback = await survey().evaluate(() => {
        const audio = window.__ownerAudio.find(item => !item.paused && item.currentTime > 0) || window.__ownerAudio[window.__ownerAudio.length - 1];
        return audio && { duration: audio.duration, currentTime: audio.currentTime, src: audio.src, paused: audio.paused };
      });
      check(lang + '_welcome_real_m4a_playing', playback && playback.duration > 0 && playback.currentTime > 0 && Date.now() - started >= 1800);
      result.playback[lang + '_welcome'] = playback;
      await ui().locator('#voice-toggle').click();
      await page.waitForTimeout(100);
      check(lang + '_welcome_stops', await survey().evaluate(() => window.__ownerAudio.every(audio => audio.paused)));
      if (disableAfter && await survey().evaluate(() => localStorage.getItem('bp_voice') === '1')) await ui().locator('#voice-toggle').click();
    };
    const start = async (name, position) => {
      await ui().locator('#f-name').fill(name);
      await ui().locator('#f-dept').selectOption('other');
      await ui().locator('#f-pos').fill(position);
      await ui().locator('#f-consent').check();
      await ui().locator('#start-btn').click();
      await ui().locator('#answer').waitFor({ state: 'visible', timeout: 60000 });
      const me = await getMe(); ids.push(me.doc.id);
    };

    await waitWelcome('ru', () => page.goto(stableUrl, { waitUntil: 'load', timeout: 60000 }), true);
    await ui().locator('#f-name').waitFor({ state: 'visible', timeout: 60000 });
    await start('Настоящее прослушивание', 'Временный тест');
    const prefetchResponse = page.waitForResponse(response => response.url().includes('/api/me/voice-prefetch'), { timeout: 30000 });
    const firstStarted = Date.now();
    await ui().locator('#voice-toggle').click();
    await waitPlaying('ru');
    check('first_autoplay_after_two_seconds', Date.now() - firstStarted >= 1800);
    const prefetchData = await (await prefetchResponse).json();
    check('current_and_next_two_queued', prefetchData.queued === 3);
    await page.screenshot({ path: path.join(root, 'run/owner-voice-public-mobile.png'), fullPage: false });
    await ui().locator('.msg-voice').last().click();
    await page.waitForTimeout(100);
    check('real_audio_stop', await survey().evaluate(() => window.__ownerAudio.every(audio => audio.paused)));
    const cacheReady = await survey().evaluate(async () => {
      const token = localStorage.getItem('bp_token');
      for (let attempt = 0; attempt < 60; attempt++) {
        const response = await fetch('/api/me/voice-prefetch', {
          method: 'POST', headers: { Authorization: 'Bearer ' + token, 'Content-Type': 'application/json' },
          body: JSON.stringify({ message: 0, count: 2 }),
        });
        const data = await response.json();
        if (data.ready === 3) return data;
        await new Promise(resolve => setTimeout(resolve, 2000));
      }
      return null;
    });
    check('next_two_audio_files_cached', cacheReady && cacheReady.ready === 3 && cacheReady.failed === 0);
    const nextStarted = Date.now();
    await ui().locator('#answer').fill('Ответ для проверки предзагрузки');
    await ui().locator('#send').click();
    await waitPlaying('ru_next');
    const nextElapsed = Date.now() - nextStarted;
    check('next_question_plays_from_cache_after_two_seconds', nextElapsed >= 1800 && nextElapsed < 7000);

    const frame = survey();
    await frame.evaluate(() => localStorage.removeItem('bp_token'));
    await page.evaluate(() => localStorage.removeItem('bp_token'));
    await page.goto(stableUrl, { waitUntil: 'load', timeout: 60000 });
    await waitWelcome('ro', () => ui().getByRole('button', { name: 'RO', exact: true }).click(), false);
    await start('Test audio real', 'Test temporar');
    await waitPlaying('ro');
    check('no_javascript_errors', result.errors.length === 0);
  } catch (error) {
    result.fatal = String(error && error.stack || error);
    process.exitCode = 1;
  } finally {
    if (browser) await browser.close();
    for (const id of ids) {
      const response = await fetch(base + '/api/admin/interviews/' + id, { method: 'DELETE', headers: { 'X-Admin-Key': admin } });
      result.cleanup.push({ id, status: response.status });
      if (!response.ok) process.exitCode = 1;
    }
    fs.writeFileSync(path.join(root, 'run/published-owner-voice-browser-result.json'), JSON.stringify(result, null, 2) + '\n');
    console.log(JSON.stringify(result, null, 2));
  }
})();
