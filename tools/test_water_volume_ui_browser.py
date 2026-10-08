#!/usr/bin/env python3
"""Литры и отдельные строки датчика воды на четырёх страницах."""
import test_mode_logic_ui_browser as gate
from test_stale_telemetry_dimming_browser import FIXTURE_ON


gate.BROWSER_TEST = r'''async page => {
  const baseUrl = __BASE_URL__;
  const telemetry = __TELEMETRY__;
  Object.assign(telemetry, {sessionId: 'water-test', useDetector: false,
    BoilingEvidence: 0, BoilingPrecisionSensorConfigured: 0});
  await page.addInitScript(() => { window.Audio = function() {
    this.play = () => Promise.resolve(); this.pause = () => {};
  }; });
  await page.route('**/ajax*', route => route.fulfill({status: 200,
    contentType: 'application/json', body: JSON.stringify(telemetry)}));
  const failures = [];
  for (const width of [320, 390, 1440]) {
    await page.setViewportSize({width, height: 900});
    for (const name of ['index', 'distiller', 'bk', 'nbk']) {
      for (const [ml, litres] of [[107591, '107.59'], [12345, '12.35']]) {
        telemetry.WFtotalMl = ml;
        telemetry.WFflowRate = 0.84;
        await page.goto(baseUrl + '/' + name + '.htm');
        await page.waitForFunction(() => document.getElementById('WFflowRate').textContent === '0.84');
        if (name !== 'distiller') await page.locator('input[value="Дополнительно"]').click();
        const result = await page.locator('#flowsensor').evaluate(el => {
          const rows = [...el.children];
          const a = rows[0].getBoundingClientRect(), b = rows[1].getBoundingClientRect();
          const range = document.createRange();
          range.selectNodeContents(rows[1]);
          const valueRange = document.createRange();
          valueRange.selectNodeContents(rows[0]);
          return {value: document.getElementById('WFtotalMl').textContent,
            text: rows[0].textContent.trim(), separate: b.top >= a.bottom,
            fits: [...range.getClientRects(), ...valueRange.getClientRects()].every(r =>
              r.left >= 0 && r.right <= window.innerWidth + 1)};
        });
        if (result.value !== litres || result.text !== 'Расход воды: ' + litres + ' л')
          failures.push(name + '/' + width + ': ожидаются литры ' + litres + ', ' + JSON.stringify(result));
        if (!result.separate || !result.fits)
          failures.push(name + '/' + width + ': строки расхода воды перекрываются или выходят за экран');
        if (name === 'distiller' && width === 390 && ml === 107591)
          await page.locator('.sec-pressure').screenshot({path: '/tmp/samovar-water-litres.png'});
      }
    }
  }
  return '__U05_RESULT__' + JSON.stringify({failures});
}'''.replace('__TELEMETRY__', FIXTURE_ON)

if __name__ == '__main__':
    raise SystemExit(gate.main())
