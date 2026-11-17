import { test, expect } from '@playwright/test';

const KEY = 'todos-vanillajs';

async function add(page, ...titles) {
  const input = page.locator('.new-todo');
  for (const t of titles) {
    await input.fill(t);
    await input.press('Enter');
  }
}
const items = (page) => page.locator('.todo-list li');
const stored = (page) => page.evaluate((k) => JSON.parse(localStorage.getItem(k)), KEY);

test.beforeEach(async ({ page }) => {
  await page.goto('/');
});

test.describe('R2/R3 structure', () => {
  test('standard elements exist', async ({ page }) => {
    for (const sel of ['.todoapp', '.new-todo', '.main', '.toggle-all', '.todo-list', '.footer',
      '.todo-count', '.filters', '.clear-completed']) {
      await expect(page.locator(sel)).toHaveCount(1);
    }
    await expect(page.locator('.new-todo')).toHaveAttribute('placeholder', 'What needs to be done?');
    const hrefs = await page.locator('.filters a').evaluateAll((as) => as.map((a) => a.getAttribute('href')));
    expect(hrefs).toEqual(['#/', '#/active', '#/completed']);
    await add(page, 'a');
    await expect(page.locator('.todo-list li > .view > input.toggle[type=checkbox]')).toHaveCount(1);
    await expect(page.locator('.todo-list li .view label')).toHaveText('a');
    await expect(page.locator('.todo-list li .view .destroy')).toHaveCount(1);
  });
  test('R1 no external requests', async ({ page }) => {
    const external = [];
    page.on('request', (r) => { if (!r.url().startsWith('http://127.0.0.1')) external.push(r.url()); });
    await page.reload();
    expect(external).toEqual([]);
  });
});

test.describe('R4 empty state', () => {
  test('main and footer hidden with no todos', async ({ page }) => {
    await expect(page.locator('.main')).toBeHidden();
    await expect(page.locator('.footer')).toBeHidden();
    await add(page, 'x');
    await expect(page.locator('.main')).toBeVisible();
    await expect(page.locator('.footer')).toBeVisible();
    await items(page).first().hover();
    await page.locator('.destroy').click();
    await expect(page.locator('.main')).toBeHidden();
    await expect(page.locator('.footer')).toBeHidden();
  });
});

test.describe('R5 new todo', () => {
  test('input focused on load', async ({ page }) => {
    await expect(page.locator('.new-todo')).toBeFocused();
  });
  test('creates, appends in order, clears input, trims', async ({ page }) => {
    await add(page, '  first  ', 'second', 'third');
    await expect(items(page).locator('label')).toHaveText(['first', 'second', 'third']);
    await expect(page.locator('.new-todo')).toHaveValue('');
  });
  test('empty and whitespace input are ignored', async ({ page }) => {
    await add(page, '', '    ');
    await expect(items(page)).toHaveCount(0);
    expect(await stored(page)).toBeNull();
  });
  test('titles are escaped as text', async ({ page }) => {
    await add(page, '<img src=x onerror="window.__xss=1"><b>hi</b>');
    await expect(items(page).locator('label')).toHaveText('<img src=x onerror="window.__xss=1"><b>hi</b>');
    expect(await page.evaluate(() => window.__xss)).toBeUndefined();
  });
});

test.describe('R6 toggle', () => {
  test('checkbox toggles completed class and counter', async ({ page }) => {
    await add(page, 'a', 'b');
    await items(page).nth(0).locator('.toggle').check();
    await expect(items(page).nth(0)).toHaveClass(/completed/);
    await expect(page.locator('.todo-count')).toHaveText('1 item left');
    await items(page).nth(0).locator('.toggle').uncheck();
    await expect(items(page).nth(0)).not.toHaveClass(/completed/);
    await expect(page.locator('.todo-count')).toHaveText('2 items left');
  });
});

test.describe('R7/R15 toggle-all', () => {
  test('marks all complete then all active', async ({ page }) => {
    await add(page, 'a', 'b', 'c');
    await page.locator('.toggle-all').check();
    await expect(page.locator('.todo-list li.completed')).toHaveCount(3);
    await page.locator('.toggle-all').uncheck();
    await expect(page.locator('.todo-list li.completed')).toHaveCount(0);
  });
  test('reflects single item changes', async ({ page }) => {
    await add(page, 'a', 'b');
    await items(page).nth(0).locator('.toggle').check();
    await expect(page.locator('.toggle-all')).not.toBeChecked();
    await items(page).nth(1).locator('.toggle').check();
    await expect(page.locator('.toggle-all')).toBeChecked();
    await items(page).nth(1).locator('.toggle').uncheck();
    await expect(page.locator('.toggle-all')).not.toBeChecked();
  });
  test('unchecked after adding a todo and after clear completed', async ({ page }) => {
    await add(page, 'a');
    await page.locator('.toggle-all').check();
    await expect(page.locator('.toggle-all')).toBeChecked();
    await add(page, 'b');
    await expect(page.locator('.toggle-all')).not.toBeChecked();
    await page.locator('.toggle-all').check();
    await page.locator('.clear-completed').click();
    await expect(page.locator('.toggle-all')).not.toBeChecked();
  });
  test('R15 applies to all todos under a filter', async ({ page }) => {
    await add(page, 'a', 'b');
    await items(page).nth(0).locator('.toggle').check();
    await page.goto('/#/active');
    await expect(items(page)).toHaveCount(1);
    await page.locator('.toggle-all').check();
    await expect(items(page)).toHaveCount(0);
    await page.goto('/#/completed');
    await expect(items(page)).toHaveCount(2);
    await page.locator('.toggle-all').uncheck();
    await expect(items(page)).toHaveCount(0);
  });
});

test.describe('R8/R9 editing', () => {
  test('double click enters edit mode with focused input and hidden view', async ({ page }) => {
    await add(page, 'a', 'b');
    await items(page).nth(0).locator('label').dblclick();
    await expect(items(page).nth(0)).toHaveClass(/editing/);
    await expect(items(page).nth(0).locator('.edit')).toHaveValue('a');
    await expect(items(page).nth(0).locator('.edit')).toBeFocused();
    await expect(items(page).nth(0).locator('.view')).toBeHidden();
    await expect(items(page).nth(1)).not.toHaveClass(/editing/);
  });
  test('Enter saves trimmed text', async ({ page }) => {
    await add(page, 'a');
    await items(page).first().locator('label').dblclick();
    await items(page).first().locator('.edit').fill('  changed  ');
    await page.keyboard.press('Enter');
    await expect(items(page).first()).not.toHaveClass(/editing/);
    await expect(items(page).first().locator('label')).toHaveText('changed');
    expect((await stored(page))[0].title).toBe('changed');
  });
  test('blur saves', async ({ page }) => {
    await add(page, 'a');
    await items(page).first().locator('label').dblclick();
    await items(page).first().locator('.edit').fill('blurred');
    await page.locator('.new-todo').click();
    await expect(items(page).first().locator('label')).toHaveText('blurred');
    await expect(items(page).first()).not.toHaveClass(/editing/);
  });
  test('empty title destroys the todo (Enter and blur)', async ({ page }) => {
    await add(page, 'a', 'b', 'c');
    await items(page).nth(0).locator('label').dblclick();
    await items(page).nth(0).locator('.edit').fill('   ');
    await page.keyboard.press('Enter');
    await expect(items(page).locator('label')).toHaveText(['b', 'c']);
    await items(page).nth(0).locator('label').dblclick();
    await items(page).nth(0).locator('.edit').fill('');
    await page.locator('.new-todo').click();
    await expect(items(page).locator('label')).toHaveText(['c']);
  });
  test('Escape discards changes, and later blur does not save', async ({ page }) => {
    await add(page, 'a');
    await items(page).first().locator('label').dblclick();
    await items(page).first().locator('.edit').fill('nope');
    await page.keyboard.press('Escape');
    await expect(items(page).first()).not.toHaveClass(/editing/);
    await expect(items(page).first().locator('label')).toHaveText('a');
    await page.locator('.new-todo').click();
    await expect(items(page).first().locator('label')).toHaveText('a');
    expect((await stored(page))[0].title).toBe('a');
  });
  test('leaving edit by clicking another control still triggers that control', async ({ page }) => {
    await add(page, 'a', 'b');
    await items(page).nth(0).locator('label').dblclick();
    await items(page).nth(1).locator('.toggle').click();
    await expect(items(page).nth(1)).toHaveClass(/completed/);
    await expect(items(page).nth(0)).not.toHaveClass(/editing/);
  });
  test('editing state is not persisted', async ({ page }) => {
    await add(page, 'a');
    await items(page).first().locator('label').dblclick();
    await page.reload();
    await expect(page.locator('.todo-list li.editing')).toHaveCount(0);
    await expect(items(page)).toHaveCount(1);
  });
});

test.describe('R10 destroy', () => {
  test('hover shows destroy, click removes', async ({ page }) => {
    await add(page, 'a', 'b');
    const li = items(page).first();
    await expect(li.locator('.destroy')).toBeHidden();
    await li.hover();
    await expect(li.locator('.destroy')).toBeVisible();
    await li.locator('.destroy').click();
    await expect(items(page).locator('label')).toHaveText(['b']);
  });
});

test.describe('R11 counter', () => {
  test('pluralisation 0/1/2 items with strong count', async ({ page }) => {
    await add(page, 'a');
    await expect(page.locator('.todo-count')).toHaveText('1 item left');
    await expect(page.locator('.todo-count > strong')).toHaveText('1');
    await add(page, 'b');
    await expect(page.locator('.todo-count')).toHaveText('2 items left');
    await expect(page.locator('.todo-count > strong')).toHaveText('2');
    await page.locator('.toggle-all').check();
    await expect(page.locator('.todo-count')).toHaveText('0 items left');
    await expect(page.locator('.todo-count > strong')).toHaveText('0');
  });
});

test.describe('R12 clear completed', () => {
  test('hidden when none completed; removes completed', async ({ page }) => {
    await add(page, 'a', 'b', 'c');
    await expect(page.locator('.clear-completed')).toBeHidden();
    await items(page).nth(1).locator('.toggle').check();
    await expect(page.locator('.clear-completed')).toBeVisible();
    await page.locator('.clear-completed').click();
    await expect(items(page).locator('label')).toHaveText(['a', 'c']);
    await expect(page.locator('.clear-completed')).toBeHidden();
  });
});

test.describe('R13 persistence', () => {
  test('stored format and reload', async ({ page }) => {
    await add(page, 'a', 'b');
    await items(page).nth(1).locator('.toggle').check();
    const data = await stored(page);
    expect(data.map((t) => [t.title, t.completed])).toEqual([['a', false], ['b', true]]);
    expect(new Set(data.map((t) => t.id)).size).toBe(2);
    await page.reload();
    await expect(items(page).locator('label')).toHaveText(['a', 'b']);
    await expect(items(page).nth(1)).toHaveClass(/completed/);
    await expect(page.locator('.todo-count')).toHaveText('1 item left');
  });
  test('deletions persist', async ({ page }) => {
    await add(page, 'a', 'b');
    await items(page).first().hover();
    await items(page).first().locator('.destroy').click();
    await page.reload();
    await expect(items(page).locator('label')).toHaveText(['b']);
  });
  test('loads pre-seeded storage', async ({ page }) => {
    await page.evaluate((k) => localStorage.setItem(k, JSON.stringify([
      { id: 1, title: 'seed', completed: true }, { id: 2, title: 'two', completed: false }])), KEY);
    await page.reload();
    await expect(items(page).locator('label')).toHaveText(['seed', 'two']);
    await expect(items(page).first()).toHaveClass(/completed/);
  });
  for (const bad of ['{not json', '{"a":1}', 'null', '"str"']) {
    test(`corrupt storage ${bad} is tolerated`, async ({ page }) => {
      await page.evaluate(([k, v]) => localStorage.setItem(k, v), [KEY, bad]);
      await page.reload();
      await expect(items(page)).toHaveCount(0);
      await add(page, 'ok');
      await expect(items(page)).toHaveCount(1);
    });
  }
});

test.describe('R14/R16 routing', () => {
  test.beforeEach(async ({ page }) => {
    await add(page, 'a', 'b', 'c');
    await items(page).nth(1).locator('.toggle').check();
  });
  const selected = (page) => page.locator('.filters a.selected');

  test('default route is all', async ({ page }) => {
    await expect(selected(page)).toHaveCount(1);
    await expect(selected(page)).toHaveText('All');
    await expect(items(page)).toHaveCount(3);
  });
  test('active and completed filters', async ({ page }) => {
    await page.locator('.filters a', { hasText: 'Active' }).click();
    await expect(page).toHaveURL(/#\/active$/);
    await expect(items(page).locator('label')).toHaveText(['a', 'c']);
    await expect(selected(page)).toHaveText('Active');
    await expect(selected(page)).toHaveCount(1);
    await page.locator('.filters a', { hasText: 'Completed' }).click();
    await expect(items(page).locator('label')).toHaveText(['b']);
    await expect(selected(page)).toHaveText('Completed');
    await page.locator('.filters a', { hasText: 'All' }).click();
    await expect(items(page)).toHaveCount(3);
  });
  test('#!/ variants accepted', async ({ page }) => {
    await page.goto('/#!/active');
    await expect(items(page)).toHaveCount(2);
    await expect(selected(page)).toHaveText('Active');
  });
  test('checking an item in Active hides it; unchecking in Completed hides it', async ({ page }) => {
    await page.goto('/#/active');
    await items(page).first().locator('.toggle').click(); // item leaves the filtered view
    await expect(items(page).locator('label')).toHaveText(['c']);
    await page.goto('/#/completed');
    await expect(items(page).locator('label')).toHaveText(['a', 'b']);
    await items(page).first().locator('.toggle').click();
    await expect(items(page).locator('label')).toHaveText(['b']);
  });
  test('filter persists on reload', async ({ page }) => {
    await page.goto('/#/completed');
    await page.reload();
    await expect(items(page).locator('label')).toHaveText(['b']);
    await expect(selected(page)).toHaveText('Completed');
  });
  test('back button returns to previous filter', async ({ page }) => {
    await page.locator('.filters a', { hasText: 'Active' }).click();
    await page.locator('.filters a', { hasText: 'Completed' }).click();
    await page.goBack();
    await expect(page).toHaveURL(/#\/active$/);
    await expect(items(page)).toHaveCount(2);
    await expect(selected(page)).toHaveText('Active');
    await page.goForward();
    await expect(items(page)).toHaveCount(1);
  });
  test('counter counts all active todos regardless of filter', async ({ page }) => {
    await page.goto('/#/completed');
    await expect(page.locator('.todo-count')).toHaveText('2 items left');
  });
  test('clear completed in Completed view empties list, footer stays', async ({ page }) => {
    await page.goto('/#/completed');
    await page.locator('.clear-completed').click();
    await expect(items(page)).toHaveCount(0);
    await expect(page.locator('.footer')).toBeVisible();
  });
  test('adding a todo under Completed filter does not show it', async ({ page }) => {
    await page.goto('/#/completed');
    await add(page, 'new');
    await expect(items(page).locator('label')).toHaveText(['b']);
    await page.goto('/#/');
    await expect(items(page)).toHaveCount(4);
  });
});

test.describe('R1 server', () => {
  test('serves index and ES modules with proper MIME types', async ({ request }) => {
    const index = await request.get('/');
    expect(index.status()).toBe(200);
    expect(index.headers()['content-type']).toContain('text/html');
    const js = await request.get('/js/app.js');
    expect(js.headers()['content-type']).toContain('javascript');
    const css = await request.get('/css/index.css');
    expect(css.headers()['content-type']).toContain('text/css');
    expect((await request.get('/package.json')).status()).toBe(404);
    expect((await request.get('/nope.html')).status()).toBe(404);
  });
});
