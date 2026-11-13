"""Собирает static/index.html из страницы-артефакта: заменяет слой claude.ai на свой API сервера опроса.
Запуск: python3 build_index.py <исходная страница артефакта>"""
import re, sys, os, json, base64
src_path = sys.argv[1]
out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'index.html')
s = open(src_path, encoding='utf-8').read()
base = os.path.dirname(os.path.abspath(__file__))
logo_data = base64.b64encode(open(os.path.join(base, 'static', 'balkan-logo-source.png'), 'rb').read()).decode('ascii')
role_data = json.load(open(os.path.join(base, 'role_packs.json'), encoding='utf-8'))
role_defaults = {pack['dept']: key for key, pack in role_data['roles'].items() if key != '11'}
assert len(role_data['roles']) == 22 and len(role_defaults) == 21

def rep(a, b, count=1):
    global s
    n = s.count(a)
    assert n == count, (a[:80], n)
    s = s.replace(a, b)

def fn_span(name):
    i = s.index('function ' + name + '(')
    j = s.index('{', i)
    d = 0
    for k in range(j, len(s)):
        if s[k] == '{': d += 1
        elif s[k] == '}':
            d -= 1
            if d == 0:
                end = k + 1
                while end < len(s) and s[end] == '\n': end += 1
                return i, end
    raise ValueError(name)

def replace_fn(name, new):
    global s
    i, e = fn_span(name)
    s = s[:i] + new.strip('\n') + '\n' + s[e:]

def remove_fn(name):
    global s
    i, e = fn_span(name)
    s = s[:i] + s[e:]

# --- документ целиком (вне claude.ai нет обёртки) ---
rep('<title>Карта процессов Balkan</title>\n<meta name="claude:viewport-fit-sides" content="cover">\n',
    '<!doctype html>\n<html lang="ru">\n<head>\n<meta charset="utf-8">\n<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">\n<title>Карта процессов Balkan</title>\n')
rep('</style>\n\n<header id="bar" class="bar"></header>', '</style>\n</head>\n<body>\n<header id="bar" class="bar"></header>')
s = s.rstrip('\n') + '\n</body>\n</html>\n'
rep('*{box-sizing:border-box}\n', '*{box-sizing:border-box}\n[hidden]{display:none!important}\nimg{max-width:100%}\n')
rep('body{background:var(--bg);', 'body{margin:0;background:var(--bg);')
rep("h('span', { class: 'mark', 'aria-hidden': 'true' }, 'B')", "h('img', { class: 'brand-logo', src: 'data:image/png;base64," + logo_data + "', alt: 'Balkan Pharmaceuticals' })")

# --- тексты ---
rep("    scriptNotice: 'ИИ-помощник недоступен для вашей учётной записи. Продолжим по готовым вопросам — ответы так же попадут руководителю.',",
    "    scriptNotice: 'ИИ-помощник сейчас недоступен. Продолжим по готовым вопросам — ответы так же попадут руководителю.',\n    errNet: 'Нет связи с сервером. Проверьте интернет и нажмите «Повторить».',\n    connTitle: 'Нет связи с сервером опроса', connLead: 'Проверьте интернет и обновите страницу. Если не помогает — сообщите руководителю: возможно, ссылка поменялась.',\n    resumeLink: 'Ссылка для продолжения', resumeCopied: 'Ссылка скопирована. Откройте её, чтобы продолжить с другого устройства.',")
rep("    scriptNotice: 'Asistentul AI nu este disponibil pentru contul dvs. Continuăm cu întrebări pregătite — răspunsurile ajung la fel la conducător.',",
    "    scriptNotice: 'Asistentul AI nu este disponibil acum. Continuăm cu întrebări pregătite — răspunsurile ajung la fel la conducător.',\n    errNet: 'Nu există conexiune cu serverul. Verificați internetul și apăsați „Reîncearcă”.',\n    connTitle: 'Nu există conexiune cu serverul sondajului', connLead: 'Verificați internetul și reîncărcați pagina. Dacă nu ajută, anunțați conducătorul: poate s-a schimbat linkul.',\n    resumeLink: 'Link pentru continuare', resumeCopied: 'Link copiat. Deschideți-l pentru a continua de pe alt dispozitiv.',")

# --- ролевые профили и состояние ---
rep("/* ---------- состояние ---------- */\nvar S = {", "var ROLE_PACKS = " + json.dumps(role_data['roles'], ensure_ascii=False, separators=(',', ':')) + ";\nvar ROLE_DEFAULT_BY_DEPT = " + json.dumps(role_defaults, ensure_ascii=False, separators=(',', ':')) + ";\n\n/* ---------- состояние ---------- */\nvar S = {")
rep("  db: null, user: null, sample: null, downloads: null,\n", "  ai: false, token: null, adminPage: false, admin: false, adminKey: '', publicUrl: '', connErr: false, poll: null, sig: '',\n")

# --- промпты живут на сервере ---
for name in ('rulesPrompt', 'transcriptText', 'summaryPrompt', 'analysisPrompt', 'buildInput', 'docPath', 'subscribeCol'):
    remove_fn(name)
s = re.sub(r"var COMPANY = '[^\n]*';\n", '', s, count=1)
rep("var cols = { interviews: [], guests: [] };\n", '')

# --- API ---
rep("function errText(e) {", """var API = {
  req: function (method, path, body, opts) {
    opts = opts || {};
    var headers = { 'Accept': 'application/json' };
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    if (opts.admin) headers['X-Admin-Key'] = S.adminKey;
    else if (S.token) headers['Authorization'] = 'Bearer ' + S.token;
    return fetch(path, { method: method, headers: headers, body: body !== undefined ? JSON.stringify(body) : undefined, cache: 'no-store' })
      .then(function (r) {
        return r.text().then(function (txt) {
          var data = {};
          try { data = txt ? JSON.parse(txt) : {}; } catch (e) {}
          if (!r.ok) throw { status: r.status, code: data.error || ('http_' + r.status) };
          return data;
        });
      }, function () { throw { status: 0, code: 'network' }; });
  }
};
function errText(e) {""")
replace_fn('errText', """function errText(e) {
  var c = e && e.code;
  if (c === 'rate_limited' || c === 'too_many_turns') return t('errRate');
  if (c === 'network') return t('errNet');
  return t('errGeneric');
}""")

replace_fn('saveMine', """function saveMine() {
  if (!S.token || !S.iv) return Promise.resolve(false);
  S.iv.updatedAt = now();
  var data = clone(S.iv);
  setSave('saving');
  chain = chain.then(function () {
    var put = function () { return API.req('PUT', '/api/me', { doc: data }); };
    return put().catch(function (e) {
      if (e && (e.code === 'network' || e.status >= 500)) return sleep(800 + Math.random() * 800).then(put);
      throw e;
    }).then(function () { setSave('saved'); return true; }, function () { setSave('fail'); return false; });
  });
  return chain;
}""")

replace_fn('renderBar', """function renderBar() {
  var bar = $('#bar');
  bar.replaceChildren();
  var dash = S.adminPage;
  var actions = h('div', { class: 'bar-actions' });
  if (dash) {
    if (S.admin) actions.append(
      h('a', { class: 'btn small', href: '/', target: '_blank', rel: 'noopener' }, 'Открыть анкету'),
      h('button', { class: 'btn small', onclick: exportCsv, disabled: !S.all.length }, 'Скачать CSV'),
      h('button', { class: 'btn small', onclick: exportJson, disabled: !S.all.length }, 'Скачать JSON'),
      h('button', { class: 'btn small ghost', onclick: logout }, 'Выйти'));
  } else {
    actions.append(voiceToggleBtn());
    var seg = h('div', { class: 'seg', role: 'group', 'aria-label': 'Язык / Limba' });
    ['ru', 'ro'].forEach(function (l) {
      seg.append(h('button', { 'aria-pressed': S.lang === l ? 'true' : 'false', onclick: function () { setLang(l); } }, l.toUpperCase()));
    });
    actions.append(seg);
  }
  bar.append(h('div', { class: 'wrap bar-in' },
    h('div', { class: 'brand' }, h('img', { class: 'brand-logo', src: 'data:image/png;base64,""" + logo_data + """', alt: 'Balkan Pharmaceuticals' }),
      h('span', { class: 'brand-t' }, h('b', null, 'Balkan · ' + (dash ? 'Карта процессов' : (S.lang === 'ro' ? 'Harta proceselor' : 'Карта процессов'))), h('span', null, dash ? 'Панель руководителя: интервью сотрудников' : t('brand')))),
    actions));
  if (!dash && S.iv && S.view !== 'welcome') {
    var phase = S.view === 'done' || S.view === 'review' || S.view === 'summarizing' ? 6 : (S.iv.phase || 1);
    var rail = h('div', { class: 'wrap rail', 'aria-label': 'Этапы' });
    t('phases').forEach(function (name, i) {
      var n = i + 1;
      rail.append(h('div', { class: 'rail-step' + (n < phase ? ' done' : n === phase ? ' cur' : ''), title: name },
        h('div', { class: 'rail-bar' }), h('div', { class: 'rail-l' }, h('b', null, n), name)));
    });
    bar.append(rail);
  }
}""")

replace_fn('render', """function render() {
  document.documentElement.lang = S.adminPage ? 'ru' : S.lang;
  renderBar();
  var main = $('#main');
  main.replaceChildren();
  if (S.adminPage) { main.append(S.admin ? viewDash() : viewLogin()); return; }
  main.append(employeeView());
}
function viewLogin() {
  var inp = h('input', { class: 'input', id: 'adm-pw', type: 'password', autocomplete: 'current-password' });
  var form = h('form', { class: 'card form', novalidate: true, onsubmit: function (e) {
    e.preventDefault();
    S.adminKey = inp.value.trim();
    S.loginErr = '';
    API.req('GET', '/api/admin/ping', undefined, { admin: true }).then(function (res) {
      S.admin = true; S.publicUrl = res.publicUrl || '';
      try { sessionStorage.setItem('bp_admin', S.adminKey); } catch (e2) {}
      startAdmin(); render();
    }, function (err) {
      S.loginErr = err && err.status === 429 ? 'Слишком много попыток. Подождите 15 минут.' : err && err.status === 401 ? 'Неверный пароль.' : 'Нет связи с сервером.';
      render();
    });
  } },
    h('div', { class: 'field' }, h('label', { for: 'adm-pw' }, 'Пароль руководителя'), inp),
    S.loginErr && h('div', { class: 'notice err', role: 'alert' }, S.loginErr),
    h('div', { class: 'actions' }, h('button', { class: 'btn primary', type: 'submit', disabled: !S.ready }, 'Войти')));
  setTimeout(function () { var el = $('#adm-pw'); if (el) el.focus(); }, 0);
  return h('section', { class: 'center-state' }, h('div', { class: 'eyebrow' }, 'Карта процессов · панель руководителя'), h('h1', null, 'Вход для руководителя'), form);
}
function startAdmin() {
  loadAll(); loadKnowledge();
  API.req('GET', '/api/admin/analysis', undefined, { admin: true }).then(function (res) { if (res.analysis) { S.analysis = res.analysis; render(); } }, function () {});
  clearInterval(S.poll);
  S.poll = setInterval(loadAll, 20000);
}
function loadAll() {
  if (S.tab === 'knowledge') loadKnowledge();
  return API.req('GET', '/api/admin/interviews', undefined, { admin: true }).then(function (res) {
    var list = res.interviews || [];
    var sig = list.map(function (d) { return d.id + ':' + d.updatedAt + ':' + (d.summary ? 1 : 0); }).join('|') + '#' + (res.publicUrl || '');
    S.publicUrl = res.publicUrl || '';
    var wasErr = !!S.dashErr;
    S.dashErr = '';
    if (sig === S.sig && !wasErr) return;
    S.sig = sig;
    S.all = list.map(function (d) { return Object.assign({}, d); });
    render();
  }, function (e) {
    if (e && e.status === 401) { logout(); return; }
    S.dashErr = 'Нет связи с сервером опроса. Данные обновятся, когда связь вернётся.';
    render();
  });
}
function logout() {
  clearInterval(S.poll);
  S.admin = false; S.adminKey = ''; S.all = []; S.sig = ''; S.analysis = null; S.selected = null;
  try { sessionStorage.removeItem('bp_admin'); } catch (e) {}
  render();
}""")

replace_fn('employeeView', """function employeeView() {
  if (S.connErr) return centerState(t('connTitle'), t('connLead'));
  switch (S.view) {
    case 'chat': return viewChat();
    case 'summarizing': return viewSummarizing();
    case 'review': return viewReview();
    case 'done': return viewDone();
    default: return viewWelcome();
  }
}""")

rep("  var canStart = S.ready && !S.offline && S.db && S.uid && !S.readOnly;", "  var canStart = S.ready && !S.connErr;")
rep("""    S.offline && h('div', { class: 'notice' }, h('b', null, t('offlineTitle') + '. '), t('offlineLead')),
    S.readOnly && h('div', { class: 'notice' }, t('readOnly')),
    h('div', { class: 'actions' }, h('button', { class: 'btn primary', type: 'submit', disabled: !canStart }, S.ready || S.offline ? t('start') : t('connecting')),
      h('span', { id: 'welcome-voice-status', class: 'mic-status', role: 'status', 'aria-live': 'polite' }))""",
    """    h('div', { class: 'actions' }, h('button', { class: 'btn primary', type: 'submit', id: 'start-btn', disabled: !canStart }, S.ready ? t('start') : t('connecting')),
      h('span', { id: 'welcome-voice-status', class: 'mic-status', role: 'status', 'aria-live': 'polite' }))""")

replace_fn('onStart', """function onStart(e) {
  e.preventDefault();
  var name = $('#f-name').value.trim(), dept = $('#f-dept').value, roleKeys = (S.formDraft.roleKeys || []).slice(), roleKey = roleKeys[0] || '', about = $('#f-about').value.trim(), position = $('#f-pos').value.trim(), consent = $('#f-consent').checked;
  S.formDraft = Object.assign({}, S.formDraft, { name: name, dept: dept, roleKey: roleKey, roleKeys: roleKeys, about: about, position: position, consent: consent });
  if (!name || !dept || !roleKey || !position || !consent) { S.formErr = t('needFields'); render(); return; }
  S.formErr = '';
  var btn = $('#start-btn');
  if (btn) btn.disabled = true;
  API.req('POST', '/api/interviews', { name: name, dept: dept, roleKey: roleKey, roleKeys: roleKeys, about: about, position: position, lang: S.lang, consent: true, mode: S.ai ? 'ai' : 'script' }).then(function (res) {
    S.token = res.token;
    storeToken(res.token);
    S.iv = res.doc;
    S.iv.uid = res.doc.id;
    S.notice = S.iv.mode === 'ai' ? '' : t('scriptNotice');
    go('chat');
    scriptAsk();
  }, function (err) {
    S.formErr = err && err.code === 'rate_limited' ? t('errRate') : t('errNet');
    render();
  });
}""")

replace_fn('aiTurn', """function aiTurn() {
  if (S.busy) return;
  if (!S.ai) { switchToScript(); return; }
  var last = S.iv.messages[S.iv.messages.length - 1];
  if (last && last.role === 'assistant') return;
  S.busy = true;
  renderLog(); updateComposer(); scrollLog();
  chain.then(function () { return API.req('POST', '/api/me/turn', {}); }).then(function (res) {
    var r = parseReply(res.text || '');
    if (r.phase) S.iv.phase = r.phase;
    S.iv.messages.push({ role: 'assistant', content: r.body || (r.done ? SCRIPT[S.iv.lang].end : '…'), phase: r.phase || S.iv.phase, options: r.done ? [] : r.options, mode: r.mode, t: now() });
    S.picked = [];
    S.busy = false;
    renderBar(); renderLog(); updateComposer(); scrollLog();
    focusAnswer();
    stopSpeech();
    var message = S.iv.messages[S.iv.messages.length - 1];
    return saveMine().then(function (ok) {
      if (ok && !r.done && S.voiceOn && S.view === 'chat' && S.iv.messages[S.iv.messages.length - 1] === message) scheduleMessageSpeech(message);
      if (r.done) finishInterview();
    });
  }, function (e) {
    S.busy = false;
    var code = e && e.code;
    if (code === 'not_your_turn') { renderLog(); updateComposer(); return; }
    if (code === 'ai_unavailable') {
      return API.req('GET', '/api/config').then(function (c) {
        if (!c.ai) { S.ai = false; renderLog(); switchToScript(); return; }
        S.chatErr = t('errGeneric'); renderLog(); updateComposer();
      }, function () { S.chatErr = t('errNet'); renderLog(); updateComposer(); });
    }
    S.chatErr = errText(e);
    renderLog(); updateComposer();
  });
}""")

rep("  if (S.iv.mode === 'ai' && S.sample) {\n    S.iv.status = 'review';", "  if (S.iv.mode === 'ai' && S.ai) {\n    S.iv.status = 'review';")

replace_fn('buildSummary', """function buildSummary() {
  S.sumErr = '';
  return chain.then(function () { return API.req('POST', '/api/me/summary', {}); }).then(function (res) {
    S.iv.summary = normSummary(res.summary); S.iv.summaryBy = 'employee'; S.iv.summaryAt = now();
    return saveMine();
  }, function (e) { S.sumErr = (e && e.code) || 'upstream_error'; }).then(function () { go('review'); });
}""")

# ссылка для продолжения
rep("        h('span', { id: 'savestate', class: 'savestate' }),", "        h('button', { class: 'btn small ghost', type: 'button', onclick: copyResume }, t('resumeLink')),\n        h('span', { id: 'savestate', class: 'savestate' }),")
rep("    } }, t('reopen'))));\n}", "    } }, t('reopen')), h('button', { class: 'btn ghost', onclick: copyResume }, t('resumeLink'))));\n}\nfunction resumeUrl() { return location.origin + '/#t=' + encodeURIComponent(S.token || ''); }\nfunction copyResume() {\n  var url = resumeUrl();\n  var shown = function () { toast(url); };\n  try { navigator.clipboard.writeText(url).then(function () { toast(t('resumeCopied')); }, shown); } catch (e) { shown(); }\n}\nfunction storeToken(tok) { try { localStorage.setItem('bp_token', tok); } catch (e) {} }\nfunction readToken() {\n  var m = location.hash.match(/(?:^#|&)t=([A-Za-z0-9_\\-]+)/);\n  if (m) { storeToken(m[1]); try { history.replaceState(null, '', location.pathname); } catch (e) {} return m[1]; }\n  try { return localStorage.getItem('bp_token'); } catch (e) { return null; }\n}")

replace_fn('personName', "function personName(iv) { return iv.name || 'Сотрудник'; }")

rep("h('button', { class: 'btn primary', onclick: function () { S.ownerMode = 'self'; render(); resumeIfNeeded(); } }, 'Пройти интервью самому')",
    "h('a', { class: 'btn primary', href: '/', target: '_blank', rel: 'noopener' }, 'Открыть анкету')")
rep("Сначала пройдите интервью сами, чтобы увидеть его глазами сотрудника, затем разошлите приглашения.", "Сначала откройте анкету и пройдите её сами, чтобы увидеть глазами сотрудника, затем разошлите ссылку.")
rep("['invite', 'Как пригласить', null]", "['invite', 'Ссылка и приглашение', null]")
rep("'Как пригласить сотрудников')", "'Ссылка и приглашение')")

# анализ
rep("h('div', { class: 'actions' }, h('span', { class: 'muted dots', id: 'anprog' }, 'Анализирую'), h('button', { class: 'btn small', onclick: function () { if (S.anCtl) S.anCtl.abort(); } }, 'Остановить'))",
    "h('div', { class: 'actions' }, h('span', { class: 'muted dots', id: 'anprog' }, 'Анализирую, это займёт несколько минут'))")
rep("'Claude сведёт резюме всех интервью: каталог процессов, кандидаты на автоматизацию, узкие места на стыках, кого опросить ещё.'",
    "'ИИ сведёт резюме всех интервью: каталог процессов, кандидаты на автоматизацию, узкие места на стыках, кого опросить ещё.'")
rep("'ИИ недоступен в этом окне, поэтому анализ собрать нельзя. Откройте страницу в claude.ai под своей учётной записью.'",
    "'Локальная модель недоступна: проверьте, что Ollama запущена на Mac.'")
replace_fn('runAnalysis', """function runAnalysis() {
  var items = S.all.filter(function (x) { return x.summary; });
  if (!items.length || !S.ai || S.anBusy) return;
  S.anBusy = true; S.anErr = '';
  render();
  API.req('POST', '/api/admin/analysis/run', {}, { admin: true }).then(function (res) {
    S.analysis = { generatedAt: now(), basedOn: res.basedOn || items.length, result: normAnalysis(res.analysis) };
    return API.req('PUT', '/api/admin/analysis', { analysis: clone(S.analysis) }, { admin: true }).catch(function () { toast('Анализ готов, но не сохранился на сервере.'); });
  }, function (e) {
    S.anErr = e && e.code === 'invalid_json' ? 'Модель вернула ответ не в том формате. Нажмите кнопку ещё раз.'
      : e && e.code === 'ai_unavailable' ? 'Локальная модель не ответила. Проверьте Ollama на Mac и попробуйте ещё раз.' : errText(e);
  }).then(function () { S.anBusy = false; render(); });
}""")

# карточка сотрудника
rep("S.db.doc(docPath(x)).delete().then(function () { toast('Интервью удалено'); }",
    "API.req('DELETE', '/api/admin/interviews/' + x.id, undefined, { admin: true }).then(function () { toast('Интервью удалено'); loadAll(); }")
rep("'Нажмите «Разобрать ответы», чтобы Claude составил его по расшифровке.'", "'Нажмите «Разобрать ответы», чтобы ИИ составил его по расшифровке.'")
replace_fn('extractMany', """function extractMany(ids) {
  if (!S.ai) return;
  var queue = ids.filter(function (id) { return !S.extracting[id]; });
  queue.forEach(function (id) { S.extracting[id] = true; delete S.extractErr[id]; });
  render();
  var next = function () {
    var id = queue.shift();
    if (!id) return loadAll();
    return API.req('POST', '/api/admin/interviews/' + id + '/extract', {}, { admin: true }).then(function (res) {
      return API.req('PUT', '/api/admin/interviews/' + id + '/summary', { summary: normSummary(res.summary) }, { admin: true });
    }).catch(function (e) {
      S.extractErr[id] = e && e.code === 'invalid_json' ? 'Ответ модели не в том формате, попробуйте ещё раз' : errText(e);
    }).then(function () { delete S.extracting[id]; render(); return next(); });
  };
  next();
}""")

replace_fn('dashInvite', """function dashInvite() {
  var link = S.publicUrl ? S.publicUrl + '/' : '';
  var linkText = link || '[ссылка на анкету]';
  var textRu = 'Коллеги, добрый день!\\n\\nМы собираем карту рабочих процессов компании, чтобы убрать рутину: ручной перенос данных, лишние согласования, однообразные отчёты. Это не проверка и не оценка вашей работы.\\n\\nПожалуйста, пройдите короткое интервью (15–20 минут, можно с перерывами). На большинство вопросов можно выбрать готовые варианты или ответить своими словами. Ответы вижу только я.\\n\\nСсылка: ' + linkText + '\\nРегистрация не нужна — откройте ссылку на телефоне или компьютере.\\n\\nСпасибо!';
  var textRo = 'Stimați colegi, bună ziua!\\n\\nRealizăm harta proceselor de lucru ale companiei pentru a elimina rutina: transferul manual de date, aprobările inutile, rapoartele repetitive. Nu este o verificare sau o evaluare a muncii dumneavoastră.\\n\\nVă rog să parcurgeți un interviu scurt (15–20 de minute, cu pauze dacă e nevoie). La majoritatea întrebărilor puteți alege variante gata făcute sau răspunde cu cuvintele dumneavoastră. Răspunsurile le văd doar eu.\\n\\nLink: ' + linkText + '\\nNu este nevoie de înregistrare — deschideți linkul pe telefon sau calculator.\\n\\nMulțumesc!';
  function copyBox(label, text, id) {
    var pre = h('div', { class: 'invite-text', id: id }, text);
    return h('div', { class: 'panel' }, h('h2', null, label), pre, copyBtn(text, pre));
  }
  return h('div', { class: 'invite' },
    h('div', { class: 'panel' }, h('h2', null, 'Ссылка на анкету'),
      link ? h('div', { class: 'invite-text', id: 'pub-url', style: 'font-family:var(--f-mono);font-size:13.5px;overflow-wrap:anywhere' }, link)
        : h('p', { class: 'notice' }, 'Публичная ссылка сейчас не поднята. Сторож на Mac поднимет её сам за пару минут; страница обновится.'),
      link && copyBtn(link, null),
      h('ol', { class: 'howto', style: 'margin-top:18px' },
        h('li', null, h('span', null, 'Отправьте ссылку сотрудникам вместе с текстом приглашения — в Viber, Telegram или по почте.')),
        h('li', null, h('span', null, 'Сотрудник открывает ссылку на телефоне или компьютере, вводит имя, отдел и должность и отвечает. Регистрация и приглашения не нужны.')),
        h('li', null, h('span', null, 'Каждый видит только своё интервью: у него личный секретный ключ в браузере. Чужих ответов по ссылке не видно.')),
        h('li', null, h('span', null, 'Ответы появляются во вкладках «Сотрудники» и «Процессы» по мере прохождения, страница обновляется сама.'))),
      h('div', { class: 'notice info', style: 'margin-top:16px;display:flex;flex-direction:column;gap:6px' },
        h('span', null, 'Адрес временный (бесплатный туннель Cloudflare) и обычно живёт около суток. Если он оборвётся, сторож поднимет новый — актуальный всегда здесь. Ответы при этом сохраняются, но незаконченные интервью сотрудникам придётся начать заново по новой ссылке. Поэтому проводите опрос в течение одного дня или подключите постоянный адрес.'),
        h('span', null, 'ИИ-интервьюер работает на локальной модели на этом Mac: ответы сотрудников не уходят в сторонние сервисы. Mac должен быть включён и не спать.'))),
    h('div', { style: 'display:flex;flex-direction:column;gap:18px;min-width:0' }, copyBox('Приглашение на русском', textRu, 'inv-ru'), copyBox('Invitație în română', textRo, 'inv-ro')));
}
function copyBtn(text, el) {
  return h('button', { class: 'btn small', onclick: function () {
    var manual = function () { if (el) selectEl(el); toast('Скопируйте текст вручную'); };
    try { navigator.clipboard.writeText(text).then(function () { toast('Скопировано'); }, manual); } catch (e) { manual(); }
  } }, 'Скопировать');
}""")

replace_fn('saveFile', """function saveFile(filename, data) {
  try {
    var blob = new Blob([data], { type: /\\.csv$/.test(filename) ? 'text/csv;charset=utf-8' : 'application/json;charset=utf-8' });
    var a = h('a', { href: URL.createObjectURL(blob), download: filename });
    document.body.append(a);
    a.click();
    setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 1500);
    toast('Файл сохранён');
  } catch (e) { toast('Не удалось сохранить файл'); }
}""")

replace_fn('subscribeAll', '')
replace_fn('boot', """function boot() {
  S.adminPage = location.pathname.replace(/\\/+$/, '') === '/admin';
  render();
  API.req('GET', '/api/config').then(function (c) { S.ai = !!c.ai; }, function () { S.connErr = true; }).then(function () {
    if (S.adminPage) {
      var key = null;
      try { key = sessionStorage.getItem('bp_admin'); } catch (e) {}
      if (!key) { S.ready = true; render(); return; }
      S.adminKey = key;
      return API.req('GET', '/api/admin/ping', undefined, { admin: true }).then(function (res) {
        S.admin = true; S.publicUrl = res.publicUrl || ''; startAdmin();
      }, function () { S.adminKey = ''; }).then(function () { S.ready = true; render(); });
    }
    var tok = S.connErr ? null : readToken();
    if (!tok) { S.ready = true; render(); scheduleWelcomeVoice(); return; }
    S.token = tok;
    return API.req('GET', '/api/me').then(function (res) {
      S.iv = res.doc;
      S.iv.uid = S.iv.id;
      S.iv.roleKey = S.iv.roleKey || ROLE_DEFAULT_BY_DEPT[S.iv.dept] || '00';
      S.iv.roleKeys = S.iv.roleKeys && S.iv.roleKeys.length ? S.iv.roleKeys : [S.iv.roleKey];
      S.attachments = pendingAttachments();
      if (S.iv.lang === 'ru' || S.iv.lang === 'ro') S.lang = S.iv.lang;
      if (!S.iv.script) S.iv.script = { stage: 'p1', i: 0, task: 1 };
      S.view = S.iv.status === 'done' ? 'done' : S.iv.status === 'review' ? 'review' : 'chat';
      if (S.iv.mode === 'ai' && !S.ai) {
        var asked = {};
        (S.iv.messages || []).forEach(function (m) { if (m.questionKey) asked[m.questionKey] = true; });
        var roleQuestions = currentRoleQuestionList(), roleIndex = 0;
        while (roleIndex < roleQuestions.length && asked[roleQuestions[roleIndex].id]) roleIndex++;
        S.iv.mode = 'script';
        S.iv.script = { stage: roleIndex < roleQuestions.length ? 'role' : 'p3', i: roleIndex, task: 1 };
        S.notice = t('scriptNotice');
      }
    }, function (e) {
      S.token = null;
      if (e && e.status === 404) { try { localStorage.removeItem('bp_token'); } catch (x) {} } else S.connErr = true;
    }).then(function () { S.ready = true; render(); resumeIfNeeded(); });
  });
}""")
replace_fn('resumeIfNeeded', """function resumeIfNeeded() {
  if (S.adminPage || S.view !== 'chat' || !S.iv || S.busy || S.reopened) return;
  var last = S.iv.messages && S.iv.messages[S.iv.messages.length - 1];
  if (last && last.role !== 'user') { if (S.voiceOn) scheduleMessageSpeech(last); return; }
  if (S.iv.mode === 'ai' && S.iv.messages.length) aiTurn(); else scriptAsk();
}""")

# общий компьютер: не показывать чужое интервью без вопроса, после отправки забыть ключ
rep("    resumeLink: 'Ссылка для продолжения',", "    resumeTitle: 'Продолжить интервью?', resumeLead: 'В этом браузере уже начато интервью: {who}.', resumeYes: 'Продолжить', resumeNo: 'Я другой сотрудник — начать своё',\n    resumeLink: 'Ссылка для продолжения',")
rep("    resumeLink: 'Link pentru continuare',", "    resumeTitle: 'Continuați interviul?', resumeLead: 'În acest browser a fost deja început un interviu: {who}.', resumeYes: 'Continuă', resumeNo: 'Sunt alt angajat — încep propriul interviu',\n    resumeLink: 'Link pentru continuare',")
rep("    case 'done': return viewDone();\n    default: return viewWelcome();\n  }\n}", """    case 'done': return viewDone();
    case 'resume': return viewResume();
    default: return viewWelcome();
  }
}
function viewResume() {
  var who = S.iv.name + ', ' + deptName(S.iv.dept, S.lang);
  return h('section', { class: 'center-state' }, h('div', { class: 'eyebrow' }, t('eyebrow')), h('h1', null, t('resumeTitle')),
    h('p', null, t('resumeLead').replace('{who}', who)),
    h('div', { class: 'actions' },
      h('button', { class: 'btn primary', onclick: function () { go(S.iv.status === 'review' ? 'review' : 'chat'); resumeIfNeeded(); } }, t('resumeYes')),
      h('button', { class: 'btn', onclick: function () { forgetToken(); S.token = null; S.iv = null; S.notice = ''; S.formDraft = null; go('welcome'); } }, t('resumeNo'))));
}
function forgetToken() { try { localStorage.removeItem('bp_token'); localStorage.removeItem('bp_draft_' + S.uid); } catch (e) {} }""")
rep("    S.iv.status = 'done'; S.iv.submittedAt = now();\n    saveMine().then(function () { go('done'); });\n  }\n}",
    "    S.iv.status = 'done'; S.iv.submittedAt = now();\n    saveMine().then(function () { forgetToken(); go('done'); });\n  }\n}")
rep("function submitInterview() {\n  S.iv.status = 'done'; S.iv.submittedAt = now();\n  saveMine().then(function () { go('done'); });",
    "function submitInterview() {\n  S.iv.status = 'done'; S.iv.submittedAt = now();\n  saveMine().then(function () { forgetToken(); go('done'); });")
rep("      S.reopened = true;\n", "      S.reopened = true;\n      storeToken(S.token);\n")
rep("  if (m) { storeToken(m[1]); try { history.replaceState(null, '', location.pathname); } catch (e) {} return m[1]; }",
    "  if (m) { S.fromLink = true; storeToken(m[1]); try { history.replaceState(null, '', location.pathname); } catch (e) {} return m[1]; }")
rep("      S.view = S.iv.status === 'done' ? 'done' : S.iv.status === 'review' ? 'review' : 'chat';\n      if (S.iv.mode === 'ai' && !S.ai) {",
    "      S.view = S.iv.status === 'done' ? 'done' : S.iv.status === 'review' ? 'review' : 'chat';\n      if (!S.fromLink && S.iv.status === 'done') { forgetToken(); S.token = null; S.iv = null; S.view = 'welcome'; return; }\n      if (!S.fromLink) S.view = 'resume';\n      if (S.iv.mode === 'ai' && !S.ai) {")
rep("  $('#stop').hidden = !(S.busy && S.iv.mode === 'ai');", "  $('#stop').hidden = true;")

# постоянная ссылка: опрос встроен в страницу GitHub Pages; ключ дублируется родителю (переживает смену туннеля)
rep("  ai: false, token: null, adminPage: false,", "  stableUrl: '', stableOrigin: '', ai: false, token: null, adminPage: false,")
rep("API.req('GET', '/api/config').then(function (c) { S.ai = !!c.ai; }, function () { S.connErr = true; })",
    "API.req('GET', '/api/config').then(function (c) { S.ai = !!c.ai; S.ownerVoice = !!c.ownerVoice; S.stableUrl = c.stableUrl || ''; S.stableOrigin = c.stableOrigin || ''; }, function () { S.connErr = true; })")
rep("""  var m = location.hash.match(/(?:^#|&)t=([A-Za-z0-9_\\-]+)/);
  if (m) { S.fromLink = true; storeToken(m[1]); try { history.replaceState(null, '', location.pathname); } catch (e) {} return m[1]; }""",
    """  var m = location.hash.match(/(?:^#|&)(s?t)=([A-Za-z0-9_\\-]+)/);
  if (m) { S.fromLink = m[1] === 't'; storeToken(m[2]); try { history.replaceState(null, '', location.pathname + location.search); } catch (e) {} return m[2]; }""")
rep("function storeToken(tok) { try { localStorage.setItem('bp_token', tok); } catch (e) {} }",
    """function storeToken(tok) { try { localStorage.setItem('bp_token', tok); } catch (e) {} tellParent(tok); }
function tellParent(tok) {
  if (window.parent === window || !S.stableOrigin) return;
  try { window.parent.postMessage({ type: 'bp_token', token: tok || null }, S.stableOrigin); } catch (e) {}
}""")
rep("function forgetToken() { try { localStorage.removeItem('bp_token'); localStorage.removeItem('bp_draft_' + S.uid); } catch (e) {} }",
    "function forgetToken() { try { localStorage.removeItem('bp_token'); localStorage.removeItem('bp_draft_' + S.uid); } catch (e) {} tellParent(null); }")
rep("function resumeUrl() { return location.origin + '/#t=' + encodeURIComponent(S.token || ''); }",
    "function resumeUrl() { return (S.stableUrl || location.origin + '/') + '#t=' + encodeURIComponent(S.token || ''); }")
rep("      h('a', { class: 'btn small', href: '/', target: '_blank', rel: 'noopener' }, 'Открыть анкету'),",
    "      h('a', { class: 'btn small', href: S.stableUrl || '/', target: '_blank', rel: 'noopener' }, 'Открыть анкету'),")
rep("h('a', { class: 'btn primary', href: '/', target: '_blank', rel: 'noopener' }, 'Открыть анкету')",
    "h('a', { class: 'btn primary', href: S.stableUrl || '/', target: '_blank', rel: 'noopener' }, 'Открыть анкету')")
rep("      S.admin = true; S.publicUrl = res.publicUrl || '';\n      try { sessionStorage",
    "      S.admin = true; S.publicUrl = res.publicUrl || ''; S.stableUrl = res.stableUrl || S.stableUrl;\n      try { sessionStorage")
rep("    S.publicUrl = res.publicUrl || '';\n    var wasErr", "    S.publicUrl = res.publicUrl || '';\n    S.stableUrl = res.stableUrl || S.stableUrl;\n    var wasErr")
rep("  var link = S.publicUrl ? S.publicUrl + '/' : '';", "  var link = S.stableUrl || (S.publicUrl ? S.publicUrl + '/' : '');")
rep("""        : h('p', { class: 'notice' }, 'Публичная ссылка сейчас не поднята. Сторож на Mac поднимет её сам за пару минут; страница обновится.'),""",
    """        : h('p', { class: 'notice' }, 'Публичная ссылка сейчас не поднята. Сторож на Mac поднимет её сам за пару минут; страница обновится.'),
      S.publicUrl && h('p', { class: 'muted', style: 'font-size:12.5px;margin-top:6px;overflow-wrap:anywhere' }, 'Технический адрес сервера сейчас: ' + S.publicUrl + '. Он меняется сам; сотрудникам его давать не нужно.'),""")
rep("""        h('span', null, 'Адрес временный (бесплатный туннель Cloudflare) и обычно живёт около суток. Если он оборвётся, сторож поднимет новый — актуальный всегда здесь. Ответы при этом сохраняются, но незаконченные интервью сотрудникам придётся начать заново по новой ссылке. Поэтому проводите опрос в течение одного дня или подключите постоянный адрес.'),""",
    """        h('span', null, 'Ссылка постоянная, как у Helper: страница на GitHub Pages сама находит текущий адрес сервера. Когда бесплатный туннель обрывается (обычно раз в сутки), сторож на Mac за несколько минут поднимает новый и обновляет страницу. В эти минуты сотрудник увидит «Опрос временно недоступен», страница повторит попытку сама. Незаконченные интервью не теряются.'),""")

# ключ из ссылки не подменяет сохранённый молча: всегда экран «чьё это интервью», сохранение — после «Продолжить»
rep("  if (m) { S.fromLink = m[1] === 't'; storeToken(m[2]); try {", "  if (m) { S.fromLink = m[1] === 't'; try {")
rep("      if (!S.fromLink) S.view = 'resume';", "      S.view = 'resume';  // всегда показать, чьё это интервью, прежде чем открыть переписку")
rep("h('button', { class: 'btn primary', onclick: function () { go(S.iv.status === 'review' ? 'review' : 'chat'); resumeIfNeeded(); } }, t('resumeYes')),",
    "h('button', { class: 'btn primary', onclick: function () { storeToken(S.token); go(S.iv.status === 'done' ? 'done' : S.iv.status === 'review' ? 'review' : 'chat'); resumeIfNeeded(); } }, t('resumeYes')),")

# тема: по умолчанию светлая (не по системе), переключатель в шапке; выбор хранит постоянная страница (параметр th)
_dark = re.search(r'@media \(prefers-color-scheme: dark\)\{:root:not\(\[data-theme="light"\]\)\{[\s\S]*?color-scheme:dark\}\}\n', s)
assert _dark, 'dark media block'
s = s[:_dark.start()] + s[_dark.end():]
rep("[hidden]{display:none!important}\n", "[hidden]{display:none!important}\n:root{color-scheme:light}\n.theme-btn{padding:6px 8px;line-height:0}\n.theme-btn svg{width:18px;height:18px}\n")
rep("    actions.append(seg);\n  }\n  bar.append(h('div', { class: 'wrap bar-in' },",
    "    actions.append(seg);\n  }\n  actions.append(themeBtn());\n  bar.append(h('div', { class: 'wrap bar-in' },")
rep("function setLang(l) {", """var MOON_SVG = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg>';
var SUN_SVG = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>';
function initTheme() {
  var th = 'light';
  var m = location.hash.match(/(?:^#|&)th=(dark|light)/);
  if (m) th = m[1];
  else { try { th = localStorage.getItem('bp_theme') || 'light'; } catch (e) {} }
  applyTheme(th, false);
}
function applyTheme(th, save) {
  S.theme = th === 'dark' ? 'dark' : 'light';
  document.documentElement.setAttribute('data-theme', S.theme);
  if (!save) return;
  try { localStorage.setItem('bp_theme', S.theme); } catch (e) {}
  if (window.parent !== window && S.stableOrigin) { try { window.parent.postMessage({ type: 'bp_theme', theme: S.theme }, S.stableOrigin); } catch (e) {} }
}
function themeBtn() {
  var dark = S.theme === 'dark';
  var ro = !S.adminPage && S.lang === 'ro';
  var label = dark ? (ro ? 'Temă luminoasă' : 'Светлая тема') : (ro ? 'Temă întunecată' : 'Тёмная тема');
  var b = h('button', { class: 'btn small ghost theme-btn', type: 'button', 'aria-label': label, title: label, onclick: function () { applyTheme(dark ? 'light' : 'dark', true); renderBar(); } });
  b.innerHTML = dark ? SUN_SVG : MOON_SVG;
  return b;
}
function setLang(l) {""")
rep("\nboot();\n})();", "\ninitTheme();\nboot();\n})();")

# любой вопрос — несколько вариантов + свой ответ (решение владельца 31.10): выбора «только один» нет
rep("  var one = q.mode === 'one';", "  var one = false;")
s = s.replace("m: 'one'", "m: 'many'")

# карточка сотрудника: выдать новую ссылку для продолжения (если сотрудник потерял свою)
rep("  stableUrl: '', stableOrigin: '',", "  stableUrl: '', stableOrigin: '', resumeLinks: {}, confirmResume: '',")
rep("    x.summary ? summaryView(x.summary, L) : h('p', { class: 'muted' }, 'Резюме ещё нет. '",
    """    S.confirmResume === x.id
      ? h('div', { class: 'actions' }, h('span', null, 'Выдать новую ссылку? Прежняя ссылка сотрудника перестанет работать.'),
          h('button', { class: 'btn small primary', onclick: function () { issueResume(x.id); } }, 'Выдать'),
          h('button', { class: 'btn small', onclick: function () { S.confirmResume = ''; render(); } }, 'Отмена'))
      : h('div', { class: 'actions' }, h('button', { class: 'btn small', onclick: function () { S.confirmResume = x.id; render(); } }, 'Ссылка для продолжения'),
          h('span', { class: 'muted', style: 'font-size:12.5px' }, 'если сотрудник потерял свою или сменил устройство')),
    S.resumeLinks[x.id] && h('div', { class: 'invite-text', style: 'font-family:var(--f-mono);font-size:12.5px;overflow-wrap:anywhere;margin:0' }, S.resumeLinks[x.id]),
    S.resumeLinks[x.id] && h('div', { class: 'actions' }, copyBtn(S.resumeLinks[x.id], null), h('span', { class: 'muted', style: 'font-size:12.5px' }, 'Отправьте её только этому сотруднику: по ней открывается его интервью.')),
    x.summary ? summaryView(x.summary, L) : h('p', { class: 'muted' }, 'Резюме ещё нет. '""")
rep("function extractMany(ids) {", """function issueResume(id) {
  API.req('POST', '/api/admin/interviews/' + id + '/resume-link', {}, { admin: true }).then(function (res) {
    S.resumeLinks[id] = res.url; S.confirmResume = ''; render();
  }, function (e) { S.confirmResume = ''; toast('Не удалось выдать ссылку: ' + errText(e)); render(); });
}
function extractMany(ids) {""")

# остатки слоя claude.ai
s = s.replace('S.sample', 'S.ai')
s = s.replace("if (S.ctl) S.ctl.abort();", '')
for bad in ('S.ai.json', 'S.ai(', 'claude.use', 'S.db', 'S.user', 'S.downloads', 'S.isOwner', 'S.ownerMode', 'docPath', 'subscribeCol'):
    assert bad not in s, bad
open(out_path, 'w', encoding='utf-8').write(s)
print('ok', out_path, len(s))
