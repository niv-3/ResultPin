const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('store/static/store/js/install-app.js', 'utf8');

function setup({standalone = false, ios = false} = {}) {
  const events = {};
  const nodes = Object.fromEntries(['payvict-install', 'payvict-install-button', 'payvict-install-help', 'payvict-install-instructions'].map(id => [id, {
    hidden: true, open: false, disabled: false,
    addEventListener(type, fn) { this[type] = fn; },
    showModal() { this.open = true; }, close() { this.open = false; }
  }]));
  const window = {matchMedia: () => ({matches: standalone, addEventListener() {}}), addEventListener(type, fn) { events[type] = fn; }};
  const document = {getElementById: id => nodes[id], addEventListener(type, fn) { events[type] = fn; }};
  vm.runInNewContext(source, {window, document, navigator: {userAgent: ios ? 'iPhone' : 'Android', platform: '', maxTouchPoints: 0}});
  events.DOMContentLoaded();
  return {events, nodes, button: nodes['payvict-install-button'], help: nodes['payvict-install-help']};
}

(async () => {
  const app = setup();
  assert.equal(app.nodes['payvict-install'].hidden, false);
  await app.button.click();
  assert.equal(app.help.open, true);
  app.help.close();
  let prompted = 0, prevented = 0;
  app.events.beforeinstallprompt({preventDefault() { prevented++; }, async prompt() { prompted++; }, userChoice: Promise.resolve({outcome: 'dismissed'})});
  assert.equal(prompted, 0, 'Never prompt without a customer tap');
  await app.button.click();
  assert.equal(prompted, 1);
  assert.equal(prevented, 1);
  await app.button.click();
  assert.equal(prompted, 1, 'A dismissed prompt must not be reused');
  assert.equal(app.help.open, true);
  app.events.appinstalled();
  assert.equal(app.nodes['payvict-install'].hidden, true);
  assert.equal(app.help.open, false);
  assert.equal(setup({standalone: true}).nodes['payvict-install'].hidden, true);
  assert.match(setup({ios: true}).nodes['payvict-install-instructions'].textContent, /Safari.*Add to Home Screen/);
  console.log('Install controls passed: tap-only prompt, cancellation, one-use prompt, installed state and iPhone instructions.');
})().catch(error => { console.error(error); process.exitCode = 1; });
