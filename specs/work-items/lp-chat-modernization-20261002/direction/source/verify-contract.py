from pathlib import Path
import json,hashlib,re
from pypdf import PdfReader
D=Path(__file__).resolve().parents[1]; workspace=D.parents[3]
headings=['Visual Theme & Atmosphere','Color','Typography','Spacing & Grid','Layout & Composition','Components','Motion & Interaction','Voice & Brand','Anti-patterns']
assert re.findall(r'^## \d\. (.+)$',(D/'DESIGN.md').read_text(),re.M)==headings
R=json.loads((D/'source/token-contract.report.json').read_text())['tokens'];css=(D/'tokens.css').read_text().splitlines();J=json.loads((D/'design-tokens.json').read_text())
for t in R:
 assert t['confidence'] in ['provided','observed','inferred'] and t['source']
 assert f"{t['cssVariable']}: {t['value']};" in css[t['line']-1]
 assert J[t['layer']][t['name']]['$value']==t['value']
assert (D/'tokens.css').read_bytes()==(D/'design-tokens.css').read_bytes()
refs=['dust','glean','claude','notebook']
for sid in refs:
 a=json.loads((D/f'source/references/{sid}-desktop.json').read_text());m=json.loads((D/f'source/references/{sid}-mobile.json').read_text())
 assert a['capturedAt'] and a['url'].startswith('https://') and 'Just a moment' not in a['title']
 assert a['elements'] and m['viewport']['width']==390
 for f in ['hero','full','mobile']:assert (D/f'screenshots/references/{sid}-{f}.png').stat().st_size>10000
lock=json.loads((D/'source/preservation-lock.json').read_text())
for f in lock['files']:assert hashlib.sha256((workspace/f['path']).read_bytes()).hexdigest()==f['sha256'],f['path']
fixture=json.loads((D/'source/fixture-proof.json').read_text());assert not fixture['externalRequests'] and not fixture['errors'] and fixture['protectedUnchanged'];assert any(s.get('reducedMotion')=='0s' for s in fixture['proof'])
reader=PdfReader(D/'STYLEBOARD.pdf');assert len(reader.pages)==10
for p in reader.pages:assert len(p.extract_text())>300
assert all(p['pass'] for p in json.loads((D/'source/contrast-report.json').read_text()))
report={'status':'pass','references':4,'tokens':len(R),'pdfPages':10,'contrastPairs':11,'protectedFiles':len(lock['files']),'h2':'pending','motionReference':'partial 53/70, see source/motion-preview-proof/report.json','skills':'inline [oc-design-dna, oc-browser]'}
(D/'source/final-verification.json').write_text(json.dumps(report,indent=2));print(json.dumps(report))
