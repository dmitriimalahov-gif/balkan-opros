"""Собирает статическую mindmap из обезличенного ответа ERP2."""

import json
from pathlib import Path

DATA = Path(__file__).parent / "exports" / "factory-map-ru.json"
TARGET = Path("/Users/brandbox/Library/Application Support/kimi-desktop/daimon-share/daimon/agents/main/blueprint/widgets/widget_f67a84a0-b5aa-464b-a1c9-5f170434318b/workspace/index.html")

payload = json.loads(DATA.read_text(encoding="utf-8"))
assert set(payload) == {"root", "totals", "functions", "unmapped_interviews"}
assert payload["totals"]["functions"] == len(payload["functions"]) == 16
assert payload["totals"]["steps"] == sum(f["step_count"] for f in payload["functions"])

template = r'''<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Карта функций завода</title>
<style>
  * { box-sizing: border-box; }
  html, body { margin: 0; padding: 0; background: transparent; }
  body { color: var(--kimi-color-text-primary); }
  button, input, select, textarea { font: inherit; }
  .factory-map {
    width: 100%; padding: var(--kimi-space-4) var(--kimi-space-4) var(--kimi-space-5);
    font-family: var(--kimi-font-sans); background: transparent;
  }
  .map-header { display: flex; align-items: flex-start; justify-content: space-between; gap: var(--kimi-space-3); }
  .map-title { margin: 0; font-size: 20px; line-height: 28px; font-weight: 500; }
  .map-subtitle { margin: var(--kimi-space-1) 0 0; color: var(--kimi-color-text-secondary); font-size: 14px; line-height: 20px; }
  .canon-badge { flex: none; padding: var(--kimi-space-1) var(--kimi-space-2); border: 1px solid var(--kimi-color-border); border-radius: var(--kimi-radius-chip); color: var(--kimi-color-text-secondary); font-size: 12px; line-height: 16px; }
  .totals { display: flex; flex-wrap: wrap; gap: var(--kimi-space-4); margin: var(--kimi-space-3) 0; color: var(--kimi-color-text-secondary); font-size: 14px; }
  .totals strong { color: var(--kimi-color-text-primary); font-weight: 500; font-variant-numeric: tabular-nums; }
  .search { width: 100%; min-height: 44px; margin-bottom: var(--kimi-space-4); }
  .mindmap { position: relative; }
  .root-node { width: min(280px, 100%); margin: 0 auto; padding: var(--kimi-space-3); border: 1px solid var(--kimi-color-text-primary); border-radius: var(--kimi-radius-panel); text-align: center; }
  .root-name { display: block; font-size: 17px; line-height: 24px; font-weight: 500; }
  .root-meta { display: block; color: var(--kimi-color-text-secondary); font-size: 12px; line-height: 16px; }
  .trunk { width: 1px; height: var(--kimi-space-5); margin: 0 auto; background: var(--kimi-color-border); }
  .function-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: var(--kimi-space-3) var(--kimi-space-2); position: relative; padding-top: var(--kimi-space-3); }
  .function-grid::before { content: ""; position: absolute; top: 0; left: 12.5%; right: 12.5%; height: 1px; background: var(--kimi-color-border); }
  .function-node { position: relative; min-width: 0; }
  .function-node::before { content: ""; position: absolute; top: calc(-1 * var(--kimi-space-3)); left: 50%; width: 1px; height: var(--kimi-space-3); background: var(--kimi-color-border); }
  .function-button { width: 100%; min-height: 68px; height: 100%; padding: var(--kimi-space-2); border: 1px solid var(--kimi-color-border); border-radius: var(--kimi-radius-input); background: transparent; color: var(--kimi-color-text-primary); cursor: pointer; text-align: left; transition: border-color var(--t-fast) var(--ease-out), background var(--t-fast) var(--ease-out); }
  .function-button:hover { background: var(--kimi-color-surface-muted); border-color: var(--kimi-color-text-tertiary); }
  .function-button:focus-visible, .back-button:focus-visible, .search:focus-visible, summary:focus-visible { outline: 2px solid var(--kimi-color-text-primary); outline-offset: 2px; }
  .function-name { display: block; font-size: 14px; line-height: 20px; font-weight: 500; overflow-wrap: anywhere; }
  .function-meta { display: block; margin-top: var(--kimi-space-1); color: var(--kimi-color-text-secondary); font-size: 12px; line-height: 16px; font-variant-numeric: tabular-nums; }
  .empty { padding: var(--kimi-space-6); text-align: center; color: var(--kimi-color-text-secondary); }
  .detail[hidden], .mindmap[hidden], .empty[hidden] { display: none; }
  .detail-head { display: flex; align-items: center; gap: var(--kimi-space-3); padding-bottom: var(--kimi-space-3); border-bottom: 1px solid var(--kimi-color-border); }
  .back-button { min-height: 44px; flex: none; }
  .detail-title { margin: 0; font-size: 17px; line-height: 24px; font-weight: 500; }
  .detail-role { color: var(--kimi-color-text-secondary); font-size: 12px; line-height: 16px; overflow-wrap: anywhere; }
  .stages { max-height: 430px; overflow-y: auto; overscroll-behavior: contain; padding-right: var(--kimi-space-1); }
  .stage { border-bottom: 1px solid var(--kimi-color-border); }
  .stage summary { min-height: 44px; padding: var(--kimi-space-3) 0; cursor: pointer; font-size: 15px; line-height: 20px; font-weight: 500; }
  .step { padding: 0 0 var(--kimi-space-4) var(--kimi-space-3); }
  .step-code { color: var(--kimi-color-text-tertiary); font-family: var(--kimi-font-mono); font-size: 12px; }
  .step-action { margin: var(--kimi-space-1) 0; font-size: 15px; line-height: 22px; }
  .step-next { margin: 0; color: var(--kimi-color-text-secondary); font-size: 14px; line-height: 20px; }
  .map-footer { margin: var(--kimi-space-4) 0 0; color: var(--kimi-color-text-tertiary); font-size: 12px; line-height: 18px; }
  @media (max-width: 700px) {
    .function-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); max-height: 390px; overflow-y: auto; padding-bottom: var(--kimi-space-2); }
    .function-grid::before, .function-node::before { display: none; }
    .canon-badge { display: none; }
    .detail-head { align-items: flex-start; flex-wrap: wrap; }
  }
  @media (prefers-reduced-motion: reduce) { .function-button { transition: none; } }
</style>
</head>
<body>
<main class="factory-map" aria-label="Карта функционала завода">
  <header class="map-header">
    <div><h1 class="map-title">Карта функций завода</h1><p class="map-subtitle">От функции к этапу и конкретному шагу</p></div>
    <span class="canon-badge">Канон ERP2</span>
  </header>
  <div class="totals" id="totals"></div>
  <input class="kimi-input search" id="search" type="search" placeholder="Найти функцию, этап или действие" aria-label="Поиск по карте процессов">
  <section class="mindmap" id="mindmap" aria-label="Функции завода">
    <div class="root-node"><span class="root-name" id="root-name"></span><span class="root-meta">Единая карта процессов</span></div>
    <div class="trunk"></div>
    <div class="function-grid" id="functions"></div>
    <div class="empty" id="empty" hidden>Ничего не найдено. Измените запрос.</div>
  </section>
  <section class="detail" id="detail" hidden aria-live="polite">
    <div class="detail-head"><button class="kimi-button kimi-button--secondary back-button" id="back">← Все функции</button><div><h2 class="detail-title" id="detail-title"></h2><div class="detail-role" id="detail-role"></div></div></div>
    <div class="stages" id="stages"></div>
  </section>
  <p class="map-footer">Карта содержит регламент и обезличенные счётчики. Тексты ответов сотрудников сюда не включены.</p>
</main>
<script id="map-data" type="application/json">__DATA__</script>
<script>
(() => {
  const data = JSON.parse(document.getElementById('map-data').textContent);
  const functionsEl = document.getElementById('functions');
  const emptyEl = document.getElementById('empty');
  const mindmapEl = document.getElementById('mindmap');
  const detailEl = document.getElementById('detail');
  const searchEl = document.getElementById('search');
  const normalize = value => String(value || '').toLocaleLowerCase('ru');
  const stepText = step => [step.canon_id, step.stage, step.action_ru, step.next_text, step.sees_ru, step.confirms_ru].join(' ');
  const matches = (fn, query) => !query || normalize([fn.title, fn.erp2_role, ...fn.stages.flatMap(stage => [stage.title, ...stage.steps.map(stepText)])].join(' ')).includes(query);
  document.getElementById('root-name').textContent = data.root.title;
  document.getElementById('totals').innerHTML = `<span><strong>${data.totals.functions}</strong> функций</span><span><strong>${data.totals.stages}</strong> этапов</span><span><strong>${data.totals.steps}</strong> шагов</span><span>Завершённых интервью: <strong>${data.totals.completed_interviews}</strong></span>`;
  function renderFunctions() {
    const query = normalize(searchEl.value.trim());
    const visible = data.functions.filter(fn => matches(fn, query));
    functionsEl.replaceChildren();
    visible.forEach(fn => {
      const wrapper = document.createElement('div');
      wrapper.className = 'function-node';
      const button = document.createElement('button');
      button.className = 'function-button';
      button.type = 'button';
      button.setAttribute('aria-label', `${fn.title}: открыть ${fn.step_count} шагов`);
      const name = document.createElement('span'); name.className = 'function-name'; name.textContent = fn.title;
      const meta = document.createElement('span'); meta.className = 'function-meta'; meta.textContent = `${fn.step_count} шагов · интервью ${fn.survey.completed}`;
      button.append(name, meta); button.addEventListener('click', () => showFunction(fn));
      wrapper.append(button); functionsEl.append(wrapper);
    });
    emptyEl.hidden = visible.length > 0;
  }
  function showFunction(fn) {
    const query = normalize(searchEl.value.trim());
    document.getElementById('detail-title').textContent = fn.title;
    document.getElementById('detail-role').textContent = `Роль ERP2: ${fn.erp2_role} · ${fn.step_count} шагов`;
    const stagesEl = document.getElementById('stages'); stagesEl.replaceChildren();
    fn.stages.filter(stage => !query || normalize([stage.title, ...stage.steps.map(stepText)].join(' ')).includes(query) || matches(fn, query) && normalize(fn.title).includes(query)).forEach((stage, index) => {
      const details = document.createElement('details'); details.className = 'stage'; if (index === 0 || query) details.open = true;
      const summary = document.createElement('summary'); summary.textContent = stage.title;
      details.append(summary);
      stage.steps.forEach(step => {
        const item = document.createElement('article'); item.className = 'step';
        const code = document.createElement('span'); code.className = 'step-code'; code.textContent = step.canon_id;
        const action = document.createElement('p'); action.className = 'step-action'; action.textContent = step.action_ru;
        const next = document.createElement('p'); next.className = 'step-next'; next.textContent = step.next_text ? `Далее: ${step.next_text}` : 'Завершающий шаг';
        item.append(code, action, next); details.append(item);
      });
      stagesEl.append(details);
    });
    mindmapEl.hidden = true; detailEl.hidden = false;
    document.getElementById('back').focus();
  }
  document.getElementById('back').addEventListener('click', () => { detailEl.hidden = true; mindmapEl.hidden = false; searchEl.focus(); });
  searchEl.addEventListener('input', () => { if (!detailEl.hidden) { detailEl.hidden = true; mindmapEl.hidden = false; } renderFunctions(); });
  document.addEventListener('keydown', event => { if (event.key === 'Escape' && !detailEl.hidden) document.getElementById('back').click(); });
  renderFunctions();
})();
</script>
</body>
</html>
'''
TARGET.write_text(template.replace("__DATA__", json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")), encoding="utf-8")
print(f"Создана карта: {TARGET}")
