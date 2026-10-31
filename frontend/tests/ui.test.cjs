const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const code = fs.readFileSync('frontend/index.html', 'utf8').match(/<script>([\s\S]*?)<\/script>/)[1];
class Element {
  constructor() { this.children = []; this.handlers = {}; this.classes = new Set(); this.classList = {toggle:(name, value) => value ? this.classes.add(name) : this.classes.delete(name)}; }
  append(...children) { this.children.push(...children); }
  replaceChildren() { this.children = []; }
  addEventListener(name, handler) { this.handlers[name] = handler; }
  setAttribute() {}
  querySelectorAll() { return this.children.flatMap(li => li.children[0].children.filter(child => child.type === 'checkbox')); }
}
const tick = () => new Promise(resolve => setImmediate(resolve));
function setup() {
  let now = Date.now(), lostWrite = false, transientFailures = 0;
  const waits = [];
  class Clock extends Date { static now() { return now; } }
  const elements = new Map();
  const element = id => { if (!elements.has(id)) elements.set(id, new Element()); return elements.get(id); };
  let day = '2026-10-31', saved = false, failure = false, interval;
  const requests = [];
  const redirects = [];
  const context = vm.createContext({Intl, Date:Clock, Object, JSON, Error, TypeError, AbortController, clearTimeout,
    setTimeout: (fn, ms) => { if ([5000,10000,15000].includes(ms)) { waits.push(ms); return setTimeout(() => { now += ms; fn(); }, 0); } return setTimeout(fn, ms); },
    window: {location: {assign: url => redirects.push(url)}},
    setInterval: fn => {interval = fn;},
    document: {getElementById:element, createElement:() => new Element(), querySelector:() => element('section'), addEventListener() {}},
    fetch:async (url, options) => {
      requests.push({url, options});
      if (transientFailures-- > 0) return {ok:false, status:503, json:async () => ({error:'reactivando', transitorio:true})};
      if (failure) return {ok:false, status:failure === true ? 503 : failure, json:async () => ({error:'SQL no disponible'})};
      if (url.endsWith('check')) { saved = JSON.parse(options.body).completado; if (lostWrite) {lostWrite=false; throw new TypeError('response lost');} }
      return {ok:true, json:async () => url.endsWith('check') ? {fecha:day, completado:saved} : {fecha:day, tareas:Array.from({length:13}, (_, i) => ({id_tarea:i+1, hora:`${String(i+5).padStart(2,'0')}:00`, nombre:`Tarea ${i+1}`, duracion_minutos:null, completado:i===0 && saved}))}};
    }});
  vm.runInContext(code, context);
  return {element, context, requests, redirects, waits, loseWrite:() => lostWrite=true, transient:n => transientFailures=n, fail:value => failure=value, day:value => {day=value; saved=false;}, interval:() => interval()};
}
test('carga, confirmación, recarga, desmarcado, fallo y reintento', async () => {
  const ui = setup(); await tick();
  assert.equal(ui.element('tareas').children.length, 13);
  const checkbox = ui.element('tareas').querySelectorAll()[0];
  checkbox.checked = true;
  const save = checkbox.handlers.change();
  assert.equal(checkbox.disabled, true);
  assert.equal(checkbox.checked, false);
  await save;
  assert.equal(checkbox.checked, true);
  assert.match(ui.element('progreso').textContent, /^1 \/ 13/);
  await vm.runInContext('load()', ui.context);
  let current = ui.element('tareas').querySelectorAll()[0];
  assert.equal(current.checked, true);
  current.checked = false; await current.handlers.change();
  assert.equal(current.checked, false);
  ui.fail(true); current.checked = true; await current.handlers.change();
  assert.equal(current.checked, false);
  assert.equal(ui.element('reintentar').hidden, false);
  ui.fail(false); await ui.element('reintentar').handlers.click();
  assert.equal(ui.element('reintentar').hidden, true);
});
test('cambio de día vuelve a consultar y reinicia estado', async () => {
  const ui = setup(); await tick();
  const current = ui.element('tareas').querySelectorAll()[0];
  current.checked = true; await current.handlers.change();
  ui.day('2026-11-01');
  vm.runInContext("madridDay = () => '2026-11-01'", ui.context);
  ui.interval(); await tick();
  assert.equal(ui.element('tareas').querySelectorAll()[0].checked, false);
  assert.equal(ui.requests.filter(r => r.url.endsWith('tareas')).length, 2);
});

test('sesión caducada y cuenta sin permiso redirigen antes de leer JSON', async () => {
  for (const [status, destination] of [[401, '/login.html'], [403, '/acceso-denegado.html']]) {
    const ui = setup(); await tick();
    ui.fail(status);
    await vm.runInContext('load()', ui.context);
    assert.equal(ui.redirects.at(-1), destination);
  }
});

test('503 transitorio usa esperas progresivas y recupera la carga', async () => {
  const ui = setup(); await tick();
  ui.transient(3);
  await vm.runInContext('load()', ui.context);
  assert.deepEqual(ui.waits, [5000,10000,15000]);
  assert.equal(ui.element('tareas').children.length, 13);
  assert.equal(ui.element('reintentar').hidden, true);
});
test('503 sin señal transitoria no se repite', async () => {
  const ui = setup(); await tick();
  ui.fail(503); const before = ui.requests.length;
  await vm.runInContext('load()', ui.context);
  assert.equal(ui.requests.length - before, 1);
  assert.equal(ui.waits.length, 0);
});
test('respuesta de marcado perdida se reconcilia sin reenviar POST', async () => {
  const ui = setup(); await tick(); ui.loseWrite();
  const checkbox = ui.element('tareas').querySelectorAll()[0];
  checkbox.checked = true; await checkbox.handlers.change();
  assert.equal(ui.element('tareas').querySelectorAll()[0].checked, true);
  assert.equal(ui.requests.filter(r => r.url.endsWith('check')).length, 1);
  assert.equal(ui.requests.at(-1).url, '/api/tareas');
});
test('agota intentos y ofrece reintento sin bucle', async () => {
  const ui = setup(); await tick(); ui.transient(50);
  const before = ui.requests.length;
  await vm.runInContext('load()', ui.context);
  assert.equal(ui.requests.length - before, 4);
  assert.equal(ui.element('reintentar').hidden, false);
});
test('presupuesto global impide esperar o lanzar otra petición', async () => {
  const ui = setup(); await tick(); ui.transient(5);
  const before = ui.requests.length;
  await vm.runInContext('load(Date.now() + 4000)', ui.context);
  assert.equal(ui.requests.length - before, 1);
  assert.equal(ui.waits.length, 0);
});
test('no repite un marcado de un día anterior', async () => {
  const ui = setup(); await tick();
  const before = ui.requests.length;
  await assert.rejects(vm.runInContext("request('/api/check', {}, Date.now()+90000, '1999-01-01')", ui.context));
  assert.equal(ui.requests.length, before);
});

test('respuesta de desmarcado perdida recupera el estado desmarcado', async () => {
  const ui = setup(); await tick();
  let checkbox = ui.element('tareas').querySelectorAll()[0];
  checkbox.checked = true; await checkbox.handlers.change();
  ui.loseWrite(); checkbox.checked = false; await checkbox.handlers.change();
  assert.equal(ui.element('tareas').querySelectorAll()[0].checked, false);
  assert.equal(ui.requests.filter(r => r.url.endsWith('check')).length, 2);
});
test('marcado con 503 reintenta exactamente el mismo estado deseado', async () => {
  const ui = setup(); await tick(); ui.transient(2);
  const checkbox = ui.element('tareas').querySelectorAll()[0];
  checkbox.checked = true; await checkbox.handlers.change();
  const writes = ui.requests.filter(r => r.url.endsWith('check'));
  assert.equal(writes.length, 3);
  assert.equal(new Set(writes.map(r => r.options.body)).size, 1);
  assert.equal(checkbox.checked, true);
});
