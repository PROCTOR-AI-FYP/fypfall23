// Optional browser verification. Uses Playwright from the supplied module path
// and an installed Edge browser; it does not download a browser or model.
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require(process.env.PROCTORAI_PLAYWRIGHT_MODULE || 'playwright');

(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const page = await browser.newPage({ viewport: { width: 1280, height: 1000 } });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const output = path.resolve('ai-engine/validation-output');
  fs.mkdirSync(output, { recursive: true });
  try {
    await page.goto('http://127.0.0.1:5173/', { waitUntil: 'domcontentloaded', timeout: 30000 });
    await page.getByRole('heading', { name: 'Live phone and book detection' }).waitFor();
    await page.getByRole('button', { name: 'Start monitoring', exact: true }).waitFor();
    await page.waitForFunction(() => [...document.querySelectorAll('button')]
      .some(b => b.textContent.includes('Start monitoring') && !b.disabled));
    console.log('Website loaded and backend connected.');
    const before = await (await page.request.get('http://127.0.0.1:8000/cases')).json();
    await page.getByRole('button', { name: 'Start monitoring', exact: true }).click();
    await page.getByRole('button', { name: 'Stop monitoring', exact: true }).waitFor();
    await page.waitForFunction(() => {
      const image = document.querySelector('img[alt="Live webcam with phone and book detection boxes"]');
      return image && image.naturalWidth > 0;
    }, { timeout: 30000 });
    console.log('Live annotated MJPEG image rendered in the browser.');
    const samples = [];
    let positiveScreenshot = false;
    for (let i=0; i<35; i++) {
      const status = await (await page.request.get('http://127.0.0.1:8000/object-monitor/status')).json();
      samples.push(status);
      if (status.error) throw Error(status.error);
      if (status.objects.length) {
        console.log(JSON.stringify({ second:i, objects:status.objects, fps:status.fps }));
        if (!positiveScreenshot) {
          await page.screenshot({ path:path.join(output,'website-positive.png'), fullPage:true });
          positiveScreenshot = true;
        }
      }
      await new Promise(resolve => setTimeout(resolve,1000));
    }
    await page.screenshot({ path:path.join(output,'website-live.png'), fullPage:true });
    const after = await (await page.request.get('http://127.0.0.1:8000/cases')).json();
    const newCases = after.filter(c => !before.some(old => old.id===c.id));
    const body = await page.locator('body').innerText();
    const summary = {
      cameraRendered:true, samplesWithObjects:samples.filter(s => s.objects.length).length,
      samplesWithBoth:samples.filter(s => new Set(s.objects.map(o=>o.label)).size===2).length,
      newCases, socketConnected:body.includes('System Status:\nLive'),
      objectAlertsVisible:newCases.every(c => body.includes(c.type.replace(/_/g,' '))), errors,
      stopped:false,
    };
    await page.getByRole('button', { name: 'Stop monitoring', exact: true }).click();
    await page.getByRole('button', { name:'Start monitoring', exact:true }).waitFor();
    const stopped = await (await page.request.get('http://127.0.0.1:8000/object-monitor/status')).json();
    summary.stopped = !stopped.running;
    await page.setViewportSize({ width:390, height:844 });
    await page.screenshot({ path:path.join(output,'website-mobile.png'), fullPage:true });
    summary.mobileOverflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
    fs.writeFileSync(path.join(output,'website-integration.json'),JSON.stringify({summary,samples},null,2));
    console.log(JSON.stringify(summary,null,2));
    if (errors.length || !summary.stopped || summary.mobileOverflow || !summary.objectAlertsVisible) {
      throw Error('Website verification reported a UI or lifecycle error.');
    }
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode=1; });
