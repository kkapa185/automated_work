// Usage: node explorer_check.js <base_url> <title1> <title2>
const { chromium } = require('playwright');
(async () => {
  const [base, beginnerCount] = [process.argv[2], parseInt(process.argv[3], 10)];
  const out = { load: false, cards: 0, errors: [], filtered_cards: null, search_cards: null };
  const browser = await chromium.launch();
  const page = await browser.newPage();
  page.on('pageerror', e => out.errors.push(String(e)));
  try {
    await page.goto(base + '/', { waitUntil: 'networkidle', timeout: 30000 });
    await page.waitForSelector('[data-project-id]', { timeout: 15000 });
    out.load = true;
    out.cards = await page.locator('[data-project-id]:visible').count();
    await page.goto(base + '/?difficulty=Beginner', { waitUntil: 'networkidle', timeout: 30000 });
    await page.waitForTimeout(1000);
    out.filtered_cards = await page.locator('[data-project-id]:visible').count();
    await page.goto(base + '/', { waitUntil: 'networkidle' });
    const box = page.locator('input[type=search], input[type=text]').first();
    await box.fill('drone');
    await page.waitForTimeout(1000);
    out.search_cards = await page.locator('[data-project-id]:visible').count();
  } catch (e) { out.errors.push(String(e)); }
  await browser.close();
  console.log(JSON.stringify(out));
})();
