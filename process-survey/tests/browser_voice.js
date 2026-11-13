const { webkit } = require('playwright');
const fs = require('fs');
const path = require('path');

const root = path.resolve(__dirname, '..');
const config = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const result = { browser: 'webkit', viewport: '390x844', mode: 'owner-voice-api', checks: {}, errors: [], httpErrors: [], speech: {}, cleanup: [] };
const ids = [];
const voiceRequests = [];
const prefetchRequests = [];
let forceAi = false;
let ownerVoice = true;
let voiceDelay = 0;
let pendingOnce = false;

function check(name, condition) {
  result.checks[name] = Boolean(condition);
  if (!condition) throw new Error('Проверка не пройдена: ' + name);
}

async function installMocks(context) {
  await context.addInitScript(() => {
    const state = window.__voice = { audio: [], browserSpeechCalls: 0, recognitions: [], autoStart: true, micInterval: null };
    window.Audio = class {
      constructor() {
        this.playCount = 0; this.pauseCount = 0; this.src = ''; this.preload = '';
        state.audio.push(this);
      }
      play() {
        this.playCount++;
        if (this.onplay) this.onplay();
        return Promise.resolve();
      }
      pause() { this.pauseCount++; }
    };
    window.SpeechSynthesisUtterance = function (text) { this.text = text; };
    Object.defineProperty(window, 'speechSynthesis', {
      configurable: true, writable: true,
      value: { speak() { state.browserSpeechCalls++; }, cancel() {}, getVoices() { return []; } },
    });
    class FakeRecognition {
      constructor() {
        this.startCount = 0; this.stopCount = 0; this.abortCount = 0;
        state.recognitions.push(this);
      }
      start() {
        this.startCount++;
        if (state.autoStart) setTimeout(() => { if (this.onstart) this.onstart(); }, 0);
      }
      stop() { this.stopCount++; setTimeout(() => { if (this.onend) this.onend(); }, 0); }
      abort() { this.abortCount++; setTimeout(() => { if (this.onend) this.onend(); }, 0); }
      emitResult(text) {
        const item = [{ transcript: text }]; item.isFinal = true;
        if (this.onresult) this.onresult({ resultIndex: 0, results: [item] });
      }
      emitError(code) {
        if (this.onerror) this.onerror({ error: code });
        if (this.onend) this.onend();
      }
    }
    Object.defineProperty(window, 'SpeechRecognition', { configurable: true, writable: true, value: FakeRecognition });
    Object.defineProperty(window, 'webkitSpeechRecognition', { configurable: true, writable: true, value: undefined });
    const nativeInterval = window.setInterval.bind(window);
    window.setInterval = function (callback, milliseconds, ...args) {
      if (milliseconds === 1000) state.micInterval = callback;
      return nativeInterval(callback, milliseconds, ...args);
    };
  });
}

(async () => {
  let browser;
  try {
    browser = await webkit.launch({ headless: true });
    const context = await browser.newContext({
      viewport: { width: 390, height: 844 }, screen: { width: 390, height: 844 },
      deviceScaleFactor: 3, isMobile: true, hasTouch: true, locale: 'ru-RU',
    });
    await installMocks(context);
    const page = await context.newPage();
    page.on('pageerror', error => result.errors.push(String(error)));
    page.on('console', message => { if (message.type() === 'error') result.errors.push(message.text()); });
    page.on('response', response => { if (response.status() >= 400) result.httpErrors.push(response.status() + ' ' + response.url()); });
    await page.route('**/api/config', async route => {
      const response = await route.fetch();
      const data = await response.json();
      data.ai = forceAi;
      data.ownerVoice = ownerVoice;
      await route.fulfill({ response, json: data });
    });
    await page.route('**/api/me/turn', async route => {
      if (!forceAi) return route.continue();
      await route.fulfill({ status: 200, contentType: 'application/json',
        body: JSON.stringify({ text: '[[2]] [[Q:voice-ai]] Следующий вопрос от живого интервьюера?' }) });
    });
    await page.route('**/api/me/voice/*', async route => {
      const index = Number(route.request().url().split('/').pop());
      voiceRequests.push(index);
      try {
        if (voiceDelay) await new Promise(resolve => setTimeout(resolve, voiceDelay));
        if (pendingOnce) {
          pendingOnce = false;
          await route.fulfill({ status: 202, contentType: 'application/json', body: JSON.stringify({ status: 'working', retryAfter: 2 }) });
        } else {
          await route.fulfill({ status: 200, contentType: 'audio/mp4', body: Buffer.from('owner-voice-audio-' + index) });
        }
      } catch (error) {
        if (!String(error).includes('Target')) throw error;
      }
    });
    await page.route('**/api/me/voice-prefetch', async route => {
      prefetchRequests.push(route.request().postDataJSON());
      await route.fulfill({ status: 202, contentType: 'application/json', body: JSON.stringify({ status: 'working', queued: 3, ready: 0, failed: 0 }) });
    });

    const ui = () => config.stableUrl ? page.frameLocator('#app') : page;
    const survey = () => config.stableUrl ? page.frames().find(frame => frame.url().startsWith(config.base)) : page;
    const audio = () => survey().evaluate(() => window.__voice.audio.map(item => ({ plays: item.playCount, pauses: item.pauseCount, src: item.src })));
    const getMe = () => survey().evaluate(async () => {
      const response = await fetch('/api/me', { headers: { Authorization: 'Bearer ' + localStorage.getItem('bp_token') } });
      return response.json();
    });
    const waitChat = async () => {
      await ui().locator('#answer').waitFor({ state: 'visible', timeout: 60000 });
      await page.waitForTimeout(80);
    };
    const waitAudio = async count => {
      await survey().waitForFunction(expected => window.__voice.audio.filter(item => item.playCount > 0).length >= expected, count, { timeout: 15000 });
    };
    const openFresh = async () => {
      const frame = survey();
      if (frame && /^https?:/.test(frame.url())) await frame.evaluate(() => {
        localStorage.removeItem('bp_token');
        Object.keys(localStorage).filter(key => key.startsWith('bp_draft_')).forEach(key => localStorage.removeItem(key));
      });
      if (config.stableUrl && /^https?:/.test(page.url())) await page.evaluate(() => localStorage.removeItem('bp_token'));
      await page.goto(config.stableUrl || config.base + '/', { waitUntil: 'load', timeout: 60000 });
      await ui().locator('#f-name').waitFor({ state: 'visible', timeout: 60000 });
    };
    const startInterview = async (name, position) => {
      await ui().locator('#f-name').fill(name);
      await ui().locator('#f-dept').selectOption('other');
      await ui().locator('#f-pos').fill(position);
      await ui().locator('#f-consent').check();
      await ui().locator('#start-btn').click();
      await waitChat();
      const me = await getMe(); ids.push(me.doc.id); return me;
    };

    await openFresh();
    if (config.stableUrl) {
      const allow = await page.locator('#app').getAttribute('allow');
      check('iframe_microphone_permission', /(?:^|;)\s*microphone(?:\s|;|$)/.test(allow || ''));
    }
    check('voice_off_by_default', (await audio()).length === 0 && voiceRequests.length === 0);
    check('microphone_not_started_automatically', await survey().evaluate(() => window.__voice.recognitions.length === 0));
    await startInterview('Голосовая проверка', 'Временный тест');
    check('first_question_not_autospoken_when_off', (await audio()).length === 0 && voiceRequests.length === 0);
    check('privacy_hint_visible', (await ui().locator('#mic-hint').innerText()).includes('сервисом браузера'));
    check('voice_toggle_44px', await ui().locator('#voice-toggle').evaluate(el => {
      const rect = el.getBoundingClientRect(); return rect.width >= 44 && rect.height >= 44;
    }));
    check('mic_button_44px', await ui().locator('#mic-btn').evaluate(el => {
      const rect = el.getBoundingClientRect(); return rect.width >= 44 && rect.height >= 44;
    }));
    check('mobile_no_horizontal_overflow', await survey().evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1));

    const toggleStarted = Date.now();
    await ui().locator('#voice-toggle').click();
    await waitAudio(1);
    check('autoplay_waits_two_seconds', Date.now() - toggleStarted >= 1800);
    check('owner_audio_requested_for_current_message', voiceRequests.join(',') === '0');
    check('current_and_next_two_prefetched', prefetchRequests[0].message === 0 && prefetchRequests[0].count === 2);
    check('owner_audio_played_once', (await audio()).length === 1 && (await audio())[0].plays === 1);
    check('audio_uses_blob_not_browser_speech', (await audio())[0].src.startsWith('blob:') && await survey().evaluate(() => window.__voice.browserSpeechCalls === 0));
    check('voice_preference_saved', await survey().evaluate(() => localStorage.getItem('bp_voice') === '1'));

    const beforeReload = voiceRequests.length;
    await page.reload({ waitUntil: 'load', timeout: 60000 });
    const resumeStarted = Date.now();
    await ui().getByRole('button', { name: 'Продолжить', exact: true }).click();
    await waitChat();
    await waitAudio(1);
    check('resume_autoplays_current_after_two_seconds', Date.now() - resumeStarted >= 1800 && voiceRequests.length === beforeReload + 1 && (await audio()).length === 1);
    check('history_microphone_stays_off', await survey().evaluate(() => window.__voice.recognitions.length === 0));

    await ui().locator('#answer').fill('Ответ перед следующим вопросом');
    await ui().locator('#send').click();
    await waitAudio(2);
    check('next_question_owner_audio_once', voiceRequests.length === beforeReload + 2 && voiceRequests[voiceRequests.length - 1] === 2);
    await ui().locator('.msg-voice').first().click();
    await waitAudio(3);
    check('older_question_manual_owner_audio', voiceRequests[voiceRequests.length - 1] === 0 && (await audio()).length === 3);
    await ui().locator('.msg-voice').first().click();
    check('message_playback_stops_without_replay', (await audio()).length === 3 && (await audio())[2].pauses === 1);
    check('message_stop_state_visible', await ui().locator('.msg-voice').first().getAttribute('aria-pressed') === 'false');

    await ui().locator('.msg-voice').last().click();
    await waitAudio(4);
    check('latest_question_manual_owner_audio', voiceRequests[voiceRequests.length - 1] === 2 && (await audio()).length === 4);
    await survey().evaluate(() => { const current = window.__voice.audio[3]; if (current.onended) current.onended(); });
    check('audio_end_restores_button', await ui().locator('.msg-voice').last().getAttribute('aria-pressed') === 'false');

    pendingOnce = true;
    await ui().locator('.msg-voice').last().click();
    await page.waitForTimeout(120);
    check('preparing_owner_voice_visible', (await ui().locator('#voice-status').innerText()).includes('Готовлю голос руководителя'));
    await waitAudio(5);
    check('working_status_polled_until_audio_ready', voiceRequests.slice(-2).every(index => index === 2));
    await survey().evaluate(() => { const current = window.__voice.audio[4]; if (current.onended) current.onended(); });

    voiceDelay = 1400;
    await ui().locator('.msg-voice').last().click();
    await page.waitForTimeout(100);
    await ui().locator('.msg-voice').last().click();
    voiceDelay = 0;
    check('pending_audio_request_can_be_cancelled', (await ui().locator('#voice-status').innerText()) === '');
    await page.waitForTimeout(1500);
    check('cancelled_request_does_not_start_audio', (await audio()).length === 5);

    await ui().locator('#answer').fill('Черновик.');
    await ui().locator('#mic-btn').click();
    await ui().locator('#mic-btn.recording').waitFor({ state: 'visible' });
    const recognition = await survey().evaluate(() => {
      const item = window.__voice.recognitions[0];
      return { lang: item.lang, continuous: item.continuous, interim: item.interimResults, alternatives: item.maxAlternatives, starts: item.startCount };
    });
    check('microphone_started_by_button', recognition.starts === 1);
    check('russian_recognition_settings', recognition.lang === 'ru-RU' && recognition.continuous === false && recognition.interim === true && recognition.alternatives === 1);
    check('recording_timer_visible', (await ui().locator('#mic-status').innerText()).includes('0:00'));
    await survey().evaluate(() => window.__voice.recognitions[0].emitResult('Проверяю голосовой ответ'));
    await page.waitForTimeout(500);
    check('transcript_appended_to_draft', await ui().locator('#answer').inputValue() === 'Черновик. Проверяю голосовой ответ');
    check('transcript_input_event_saves_draft', await survey().evaluate(() => Object.keys(localStorage).some(key => key.startsWith('bp_draft_') && localStorage.getItem(key).includes('Проверяю голосовой ответ'))));
    check('recognition_does_not_autofocus_mobile', await survey().evaluate(() => document.activeElement.id !== 'answer'));
    check('editable_transcript_notice', (await ui().locator('#toast').innerText()).includes('исправьте'));
    await ui().locator('#answer').fill('Черновик. Проверяю голосовой ответ. Исправлено.');
    await page.screenshot({ path: path.join(root, 'run/voice-mobile-ru.png'), fullPage: false });
    await ui().locator('#send').click();
    await waitAudio(6);
    check('send_aborts_active_recognition', await survey().evaluate(() => window.__voice.recognitions[0].abortCount === 1));
    check('edited_transcript_sent', (await getMe()).doc.messages.some(message => message.role === 'user' && message.content.includes('Исправлено.')));

    await ui().locator('#mic-btn').click();
    await ui().locator('#mic-btn.recording').waitFor({ state: 'visible' });
    await survey().evaluate(() => { for (let second = 0; second < 120; second++) window.__voice.micInterval(); });
    check('automatic_stop_at_120_seconds', await survey().evaluate(() => window.__voice.recognitions[1].stopCount === 1));
    await page.waitForTimeout(30);
    check('recording_state_cleared_after_stop', await ui().locator('#mic-btn').getAttribute('aria-pressed') === 'false' && (await ui().locator('#mic-status').innerText()) === '');
    await ui().locator('#mic-btn').click();
    await ui().locator('#mic-btn.recording').waitFor({ state: 'visible' });
    await survey().evaluate(() => window.__voice.recognitions[2].emitError('not-allowed'));
    check('permission_error_explained', (await ui().locator('#toast').innerText()).includes('Нет доступа к микрофону'));
    check('permission_error_resets_recording', await ui().locator('#mic-btn').getAttribute('aria-pressed') === 'false');

    await survey().evaluate(async () => {
      const token = localStorage.getItem('bp_token');
      const response = await fetch('/api/me', { headers: { Authorization: 'Bearer ' + token } });
      const data = await response.json(); data.doc.mode = 'ai';
      await fetch('/api/me', { method: 'PUT', headers: { Authorization: 'Bearer ' + token, 'Content-Type': 'application/json' }, body: JSON.stringify({ doc: data.doc }) });
    });
    forceAi = true;
    const beforeAiReload = voiceRequests.length;
    await page.reload({ waitUntil: 'load', timeout: 60000 });
    const aiResumeStarted = Date.now();
    await ui().getByRole('button', { name: 'Продолжить', exact: true }).click();
    await waitChat();
    await waitAudio(1);
    check('ai_resume_autoplays_after_two_seconds', Date.now() - aiResumeStarted >= 1800 && voiceRequests.length === beforeAiReload + 1 && (await audio()).length === 1);
    await ui().locator('#answer').fill('Ответ для живого интервьюера');
    await ui().locator('#send').click();
    await survey().waitForFunction(() => {
      const messages = document.querySelectorAll('.msg.a .txt');
      return messages.length && messages[messages.length - 1].textContent.includes('живого интервьюера');
    });
    await waitAudio(2);
    const savedRu = await getMe();
    check('ai_answer_owner_audio_once', voiceRequests.length === beforeAiReload + 2 && voiceRequests[voiceRequests.length - 1] === savedRu.doc.messages.length - 1);
    result.speech.ru = { source: 'owner-voice-api', messageIndex: voiceRequests[voiceRequests.length - 1] };
    check('only_text_saved_no_audio_in_messages', savedRu.doc.messages.every(message => !('audio' in message) && !('recording' in message)) && !(savedRu.doc.attachments || []).length);

    forceAi = false;
    await openFresh();
    await ui().getByRole('button', { name: 'RO', exact: true }).click();
    await startInterview('Test vocal', 'Test temporar');
    await waitAudio(1);
    check('romanian_question_owner_audio_once', voiceRequests[voiceRequests.length - 1] === 0 && (await audio()).length === 1);
    result.speech.ro = { source: 'owner-voice-api', messageIndex: voiceRequests[voiceRequests.length - 1] };
    await ui().locator('#mic-btn').click();
    await ui().locator('#mic-btn.recording').waitFor({ state: 'visible' });
    check('romanian_recognition_language', await survey().evaluate(() => window.__voice.recognitions[0].lang === 'ro-RO'));
    await survey().evaluate(() => window.__voice.recognitions[0].emitResult('Răspuns vocal de test'));
    check('romanian_transcript_editable', await ui().locator('#answer').inputValue() === 'Răspuns vocal de test');
    await page.screenshot({ path: path.join(root, 'run/voice-mobile-ro.png'), fullPage: false });
    await ui().locator('#mic-btn').click();
    await page.waitForTimeout(30);
    check('romanian_manual_stop', await survey().evaluate(() => window.__voice.recognitions[0].stopCount === 1));
    const beforeAutoCancel = voiceRequests.length;
    await ui().locator('#send').click();
    await ui().locator('#mic-btn').click();
    await ui().locator('#mic-btn.recording').waitFor({ state: 'visible' });
    await page.waitForTimeout(2200);
    check('next_autoplay_cancelled_by_microphone', voiceRequests.length === beforeAutoCancel && (await audio()).length === 1);
    check('romanian_text_sent', (await getMe()).doc.messages.some(message => message.role === 'user' && message.content === 'Răspuns vocal de test'));
    await ui().locator('#mic-btn').click();
    await page.waitForTimeout(30);

    await survey().evaluate(() => { window.SpeechRecognition = undefined; window.webkitSpeechRecognition = undefined; });
    await ui().locator('#mic-btn').click();
    check('unsupported_microphone_fallback', (await ui().locator('#toast').innerText()).includes('Scrieți răspunsul'));
    ownerVoice = false;
    await page.reload({ waitUntil: 'load', timeout: 60000 });
    await ui().getByRole('button', { name: 'Continuă', exact: true }).click();
    await waitChat();
    await ui().locator('#voice-toggle').click();
    await ui().locator('#voice-toggle').click();
    check('owner_voice_unavailable_has_no_browser_substitute', (await ui().locator('#toast').innerText()).includes('conducătorului'));
    check('browser_synthesis_never_used', await survey().evaluate(() => window.__voice.browserSpeechCalls === 0));
    check('text_answer_remains_available', await ui().locator('#answer').isEnabled());

    await page.setViewportSize({ width: 1280, height: 900 });
    await page.screenshot({ path: path.join(root, 'run/voice-desktop.png'), fullPage: false });
    check('desktop_no_horizontal_overflow', await survey().evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1));
    check('no_javascript_errors', result.errors.length === 0);
    check('no_http_errors', result.httpErrors.length === 0);
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
        result.cleanup.push({ id, error: String(error) }); process.exitCode = 1;
      }
    }
    result.ownerVoiceRequests = voiceRequests;
    result.prefetchRequests = prefetchRequests;
    fs.writeFileSync(path.join(root, 'run/browser_voice-result.json'), JSON.stringify(result, null, 2) + '\n');
    console.log(JSON.stringify({ checks: result.checks, errors: result.errors, httpErrors: result.httpErrors, fatal: result.fatal, cleanup: result.cleanup.length }, null, 2));
  }
})();
