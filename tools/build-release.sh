#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
: "${FNPACK:=fnpack}"
python3 - <<'PY'
from pathlib import Path
import shutil
for p in Path('app').rglob('__pycache__'):
    shutil.rmtree(p)
for p in Path('app').rglob('*'):
    if p.is_file() and (p.suffix in ('.db', '.pyc') or p.name in ('sessions.json', 'config.json', 'display-scene.json', 'display-output.json')):
        raise SystemExit('Refusing to package runtime data: ' + str(p))
PY
"$FNPACK" build
mkdir -p dist
version=$(sed -n "s/^version[[:space:]]*=[[:space:]]*//p" manifest)
cp fnmonitor.fpk "dist/fnhdmi-monitor-${version}-x86.fpk"
python3 - <<'PY'
from pathlib import Path
import hashlib
import re
v = re.search(r'(?m)^version\s*=\s*(\S+)', Path('manifest').read_text()).group(1)
p = Path('dist')/('fnhdmi-monitor-'+v+'-x86.fpk')
(p.parent/'SHA256SUMS').write_text(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.name+'\n')
PY
