from pathlib import Path
import json,shutil,hashlib
import sys
r=Path(__file__).resolve().parents[1];up=Path(sys.argv[1]);dest=r/'app/www/haloflux';dest.mkdir(parents=True,exist_ok=True)
assert hashlib.sha256((up/'wallpaper/index.html').read_bytes()).hexdigest()=='8650361386bcc230b7349ea0ec32a4044b39e17aa13d53bd115c0f1471a590fa'
s=(up/'wallpaper/index.html').read_text();core=s[s.index('const TAU ='):s.index('/* ---------- callout box')]
assert core.count('  drawCallout();')==1
core=core.replace('  drawCallout();','  drawTelemetryArcs();')
core=core.replace('const C = { ...(PRESETS.MINE || PRESETS.B) };','const C = {...BASE, camera:0,camZoom:0,runnerCount:100,hazeCount:4,flyerCount:.6,bokeh:0,beamGlow:1.2,depthBlur:0,webBlur:0};')
core=core.replace('Math.min(window.devicePixelRatio || 1, 2)','Math.min(window.devicePixelRatio || 1, 1.25)')
notice='''/*! HALOFLUX by Ryder191 (RYDER CODE / Ms MAIKEBAIs CAT)
 * Source: https://github.com/Ryder191/haloflux
 * Required Notice: Copyright (c) 2026 Ryder191 (RYDER CODE / Ms MAIKEBAIs CAT) - https://github.com/Ryder191/haloflux
 * Required Notice: Noncommercial use only. Any commercial use is strictly prohibited. No commercial licenses are offered.
 * PolyForm Noncommercial 1.0.0; full terms in LICENSE.txt.
 * Modified for private fnMonitor use: canvas core extracted from wallpaper/index.html,
 * example dashboards/music removed; telemetry mapping, bounded rendering and gauges added.
 */
(()=>{'use strict';
let T=0;
'''
(dest/'engine.js').write_text(notice+core+(r/'tools/halo_engine_tail.js').read_text() if (r/'tools/halo_engine_tail.js').exists() else notice+core)
shutil.copy2(up/'LICENSE',dest/'LICENSE.txt')
(r/'HALOFLUX-SOURCE.json').write_text(json.dumps({'repository':'https://github.com/Ryder191/haloflux','commit':json.loads((up/'commit.json').read_text())['sha'],'input':'wallpaper/index.html','sha256':hashlib.sha256((up/'wallpaper/index.html').read_bytes()).hexdigest(),'license':'PolyForm Noncommercial 1.0.0 with Required Notices','modifications':'canvas-only extraction; real NAS telemetry; no audio, fonts, third-party requests or example data panels'},indent=2))
