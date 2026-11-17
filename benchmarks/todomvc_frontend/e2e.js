// Playwright port of the official TodoMVC Cypress suite (test names preserved). Usage: node e2e.js <baseUrl>
const { chromium } = require('playwright');
const T1 = 'buy some cheese', T2 = 'feed the cat', T3 = 'book a doctors appointment';
const results = [];
async function run() {
  const base = process.argv[2];
  const browser = await chromium.launch();
  const tests = [];
  const it = (name, fn) => tests.push([name, fn]);
  const items = p => p.locator('.todo-list li');
  const add = async (p, ...ts) => { for (const t of ts) { await p.locator('.new-todo').fill(t); await p.locator('.new-todo').press('Enter'); } };
  const texts = async p => (await items(p).locator('label').allTextContents()).map(s => s.trim());
  const visible = async (p, sel) => { const l = p.locator(sel); return (await l.count()) > 0 && await l.first().isVisible(); };
  const expect = (c, msg) => { if (!c) throw new Error(msg || 'assertion failed'); };
  const eq = (a, b, m) => expect(JSON.stringify(a) === JSON.stringify(b), `${m || ''} expected ${JSON.stringify(b)} got ${JSON.stringify(a)}`);
  const three = async p => add(p, T1, T2, T3);
  // Users toggle-all through the visible control: the <label for="toggle-all"> in the official markup.
  const toggleAll = async p => { const lab = p.locator('label[for="toggle-all"], .toggle-all-label').first();
    if ((await lab.count()) && await lab.isVisible()) await lab.click(); else await p.locator('.toggle-all').click({ force: true });
    await p.waitForTimeout(50); };
  // Filters re-render on hashchange; wait for the route to apply before reading the list.
  const nav = async (p, text) => { await p.locator('.filters a', { hasText: new RegExp('^' + text + '$') }).click();
    await p.waitForFunction(t => { const a = document.querySelector('.filters a.selected'); return a && a.textContent.trim() === t; }, text, { timeout: 3000 }).catch(() => {});
    await p.waitForTimeout(50); };
  const edit = async (p, i) => { await items(p).nth(i).locator('label').dblclick(); return items(p).nth(i).locator('.edit'); };

  it('should focus on the todo input field', async p => { eq(await p.evaluate(() => document.activeElement && document.activeElement.classList.contains('new-todo')), true); });
  it('starts with nothing', async p => { eq(await items(p).count(), 0); });
  it('should hide #main and #footer', async p => { expect(!(await visible(p, '.main')), 'main visible'); expect(!(await visible(p, '.footer')), 'footer visible'); });
  it('should allow me to add todo items', async p => { await add(p, T1); eq(await texts(p), [T1]); await add(p, T2); eq(await texts(p), [T1, T2]); });
  it('should clear text input field when an item is added', async p => { await add(p, T1); eq(await p.locator('.new-todo').inputValue(), ''); });
  it('should append new items to the bottom of the list', async p => { await three(p); eq(await texts(p), [T1, T2, T3]); eq((await p.locator('.todo-count').textContent()).trim(), '3 items left'); });
  it('should trim text input', async p => { await add(p, `    ${T1}    `); eq(await texts(p), [T1]); });
  it('should show #main and #footer when items added', async p => { await add(p, T1); expect(await visible(p, '.main')); expect(await visible(p, '.footer')); });
  it('should allow me to mark all items as completed', async p => { await three(p); await toggleAll(p); eq(await p.locator('.todo-list li.completed').count(), 3); });
  it('should allow me to clear the complete state of all items', async p => { await three(p); await toggleAll(p); await toggleAll(p); eq(await p.locator('.todo-list li.completed').count(), 0); });
  it('complete all checkbox should update state when items are completed / cleared', async p => {
    await three(p); await toggleAll(p); eq(await p.locator('.toggle-all').isChecked(), true);
    await items(p).first().locator('.toggle').uncheck(); eq(await p.locator('.toggle-all').isChecked(), false);
    await items(p).first().locator('.toggle').check(); eq(await p.locator('.toggle-all').isChecked(), true); });
  it('should allow me to mark items as complete', async p => { await add(p, T1, T2); await items(p).nth(0).locator('.toggle').check(); eq(await items(p).nth(0).getAttribute('class').then(c => /completed/.test(c || '')), true); eq(await items(p).nth(1).getAttribute('class').then(c => /completed/.test(c || '')), false); await items(p).nth(1).locator('.toggle').check(); eq(await p.locator('.todo-list li.completed').count(), 2); });
  it('should allow me to un-mark items as complete', async p => { await add(p, T1, T2); await items(p).nth(0).locator('.toggle').check(); await items(p).nth(0).locator('.toggle').uncheck(); eq(await p.locator('.todo-list li.completed').count(), 0); });
  it('should allow me to edit an item', async p => { await three(p); const e = await edit(p, 1); await e.fill('buy some sausages'); await e.press('Enter'); eq(await texts(p), [T1, 'buy some sausages', T3]); });
  it('should hide other controls when editing', async p => { await three(p); await edit(p, 1); expect(!(await items(p).nth(1).locator('.toggle').isVisible()), 'toggle visible'); expect(!(await items(p).nth(1).locator('label').isVisible()), 'label visible'); });
  it('should save edits on blur', async p => { await three(p); const e = await edit(p, 1); await e.fill('buy some sausages'); await e.evaluate(el => el.blur()); await p.waitForTimeout(100); eq(await texts(p), [T1, 'buy some sausages', T3]); });
  it('should trim entered text', async p => { await three(p); const e = await edit(p, 1); await e.fill('    buy some sausages    '); await e.press('Enter'); eq(await texts(p), [T1, 'buy some sausages', T3]); });
  it('should remove the item if an empty text string was entered', async p => { await three(p); const e = await edit(p, 1); await e.fill(''); await e.press('Enter'); eq(await texts(p), [T1, T3]); });
  it('should cancel edits on escape', async p => { await three(p); const e = await edit(p, 1); await e.fill('foo'); await e.press('Escape'); eq(await texts(p), [T1, T2, T3]); });
  it('should display the current number of todo items', async p => { await add(p, T1); eq((await p.locator('.todo-count').textContent()).trim(), '1 item left'); await add(p, T2); eq((await p.locator('.todo-count').textContent()).trim(), '2 items left'); });
  it('should display the correct text', async p => { await three(p); await items(p).first().locator('.toggle').check(); eq((await p.locator('.clear-completed').textContent()).trim(), 'Clear completed'); });
  it('should remove completed items when clicked', async p => { await three(p); await items(p).nth(1).locator('.toggle').check(); await p.locator('.clear-completed').click(); eq(await texts(p), [T1, T3]); });
  it('should be hidden when there are no items that are completed', async p => { await three(p); await items(p).first().locator('.toggle').check(); expect(await visible(p, '.clear-completed')); await p.locator('.clear-completed').click(); expect(!(await visible(p, '.clear-completed')), 'still visible'); });
  it('should persist its data', async p => { await add(p, T1, T2); await items(p).nth(0).locator('.toggle').check(); await p.reload(); await p.waitForSelector('.todo-list li', { timeout: 5000 }); eq(await texts(p), [T1, T2]); eq(await p.locator('.todo-list li.completed').count(), 1); });
  it('should allow me to display active items', async p => { await three(p); await items(p).nth(1).locator('.toggle').check(); await nav(p, 'Active'); eq(await texts(p), [T1, T3]); });
  it('should respect the back button', async p => { await three(p); await items(p).nth(1).locator('.toggle').check(); await nav(p, 'All'); await nav(p, 'Active'); await nav(p, 'Completed'); eq(await texts(p), [T2]); await p.goBack(); eq(await texts(p), [T1, T3]); await p.goBack(); eq(await texts(p), [T1, T2, T3]); });
  it('should allow me to display completed items', async p => { await three(p); await items(p).nth(1).locator('.toggle').check(); await nav(p, 'Completed'); eq(await texts(p), [T2]); });
  it('should allow me to display all items', async p => { await three(p); await items(p).nth(1).locator('.toggle').check(); await nav(p, 'Active'); await nav(p, 'Completed'); await nav(p, 'All'); eq(await texts(p), [T1, T2, T3]); });
  it('should highlight the currently applied filter', async p => { await three(p); const sel = async t => /selected/.test(await p.locator('.filters a', { hasText: new RegExp('^' + t + '$') }).getAttribute('class') || ''); expect(await sel('All'), 'All'); await nav(p, 'Active'); expect(await sel('Active'), 'Active'); await nav(p, 'Completed'); expect(await sel('Completed'), 'Completed'); });
  it('should not add empty items', async p => { await add(p, '   '); eq(await items(p).count(), 0); });

  for (const [name, fn] of tests) {
    const ctx = await browser.newContext();
    const page = await ctx.newPage();
    const errors = [];
    page.on('pageerror', e => errors.push(String(e)));
    try {
      await page.goto(base + '/', { waitUntil: 'load', timeout: 20000 });
      await page.waitForSelector('.new-todo', { timeout: 10000 });
      await fn(page);
      results.push({ name, passed: errors.length === 0, detail: errors.join('; ').slice(0, 200) });
    } catch (e) {
      results.push({ name, passed: false, detail: String(e).slice(0, 300) });
    }
    await ctx.close();
  }
  await browser.close();
  console.log(JSON.stringify(results));
}
run();
