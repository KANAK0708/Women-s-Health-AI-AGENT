from pathlib import Path
import re, html
import markdown

ROOT=Path(__file__).resolve().parent
# Coordinates are columns and rows; edges show the main execution/data paths.
D=[
('System architecture',[
('u','Patient interface',1,0),('a','API and consent',1,1),('o','Bounded orchestrator',1,2),('s','Safety engine',1,3),('e','Urgent template',0,4),('c','Context and scope',1,4),('r','Evidence retrieval',1,5),('k','Approved evidence',2,5),('g','Grounded generator',1,6),('v','Policy and citation checks',1,7),('b','Safe abstention',0,8),('f','Final answer to user',1,9),('t','Redacted telemetry',2,3),('p','Restricted patient store',2,1)],
[('u','a',''),('a','o',''),('a','p',''),('o','s',''),('o','t',''),('s','e','urgent'),('s','c','proceed'),('c','r',''),('k','r',''),('r','g',''),('g','v',''),('v','g','repair once'),('v','b','fail'),('e','f',''),('b','f',''),('v','f','pass')]),
('Patient workflow',[
('a','Purpose and consent',1,0),('b','New question',1,1),('c','Safety check each turn',1,2),('d','Immediate guidance',0,3),('e','Validated scope check',1,3),('f','Out of scope route',2,4),('g','Enough relevant context?',1,4),('h','Focused clarification',0,5),('i','Retrieve evidence',1,5),('j','Applicable and adequate?',1,6),('k','Abstain and next step',0,7),('l','Generate and verify',1,7),('m','Answer and feedback',1,8)],
[('a','b',''),('b','c',''),('c','d','urgent'),('c','e','continue'),('e','f','no'),('e','g','yes'),('g','h','no'),('h','b','new turn'),('g','i','yes'),('i','j',''),('j','k','no'),('j','l','yes'),('l','m','')]),
('Safety and escalation',[
('i','Input and session context',1,0),('r','Approved clinical rules',0,1),('s','Semantic danger detection',2,1),('a','Combine conservatively',1,2),('d','Protocol disposition',1,3),('e','Emergency guidance',0,4),('p','Prompt clinical review',1,4),('n','Education workflow',2,4),('x','Unable to assess safely',0,5),('l','Minimal safety audit',1,6)],
[('i','r',''),('i','s',''),('r','a',''),('s','a',''),('a','d',''),('d','e','urgent'),('d','p','prompt'),('d','n','routine'),('d','x','uncertain'),('e','l',''),('p','l',''),('x','l','')]),
('Evidence publishing lifecycle',[
('a','Discover candidate source',1,0),('b','Authority, rights, locale',1,1),('c','Extract text and tables',1,2),('d','Clinical applicability review',1,3),('e','Versioned registry',1,4),('f','Context-preserving chunks',1,5),('g','Build hybrid index',1,6),('h','Retrieval regression tests',1,7),('i','Clinical and test approval',1,8),('j','Atomic evidence release',1,9),('k','Change and expiry checks',2,9)],
[('a','b',''),('b','c',''),('c','d',''),('d','e',''),('e','f',''),('f','g',''),('g','h',''),('h','i',''),('i','j','pass'),('i','d','fail'),('j','k',''),('k','b','review updates')]),
('Request sequence and failures',[
('a','1  User sends question',1,0),('b','2  API validates and checks safety',1,1),('c','Urgent reviewed response',0,2),('d','3  Retrieve scoped evidence',1,2),('e','Evidence failure fallback',2,3),('f','4  Generate typed claims',1,3),('g','5  Verify exact candidate',1,4),('h','6  Deliver on pass',0,5),('i','Repair once if time remains',2,5),('j','7  Revalidate full answer',2,6),('k','Deliver pass or fallback',1,7)],
[('a','b',''),('b','c','urgent'),('b','d','supported'),('d','e','insufficient'),('d','f','adequate'),('f','g',''),('g','h','pass'),('g','i','fail'),('i','j',''),('j','k','')]),
('Conceptual data relationships',[
('s','Session',1,0),('m','Message',1,1),('c','Consent event',0,1),('a','Answer',1,2),('r','System release',2,2),('h','Claim',1,3),('f','Safety event',0,3),('v','Evaluation run',2,3),('ce','Claim evidence link',1,4),('p','Versioned passage',1,5),('sv','Source version',1,6)],
[('s','m','1 to many'),('s','c','1 to many'),('m','a','0 or 1'),('r','a','1 to many'),('a','h','1 to many'),('a','f','0 to many'),('r','v','1 to many'),('h','ce','1 to many'),('p','ce','1 to many'),('sv','p','1 to many')]),
('Privacy boundaries and deletion',[
('u','User',1,0),('c','Consent and minimal intake',1,1),('p','Restricted patient store',1,2),('m','Minimized model request',1,3),('k','Approved evidence registry',2,3),('a','Restricted audit events',0,3),('o','Validated response',1,4),('d','Export or deletion request',2,4),('w','Delete records and copies',2,5),('b','Track backup expiry',2,6),('r','Access controls and audit',0,4)],
[('u','c',''),('c','p',''),('p','m',''),('k','m',''),('p','a',''),('m','o',''),('p','d',''),('d','w',''),('w','b',''),('a','r','')]),
('Release and incident workflow',[
('a','Versioned system change',1,0),('b','Engineering and security tests',1,1),('c','Locked clinical evaluation',1,2),('d','Clinical and engineering signoff',1,3),('e','Internal then supervised pilot',1,4),('f','Limited consented rollout',1,5),('g','Safety and stability review',1,6),('h','Expand validated scope',0,7),('i','Disable path and rollback',2,7),('j','Investigate and re-evaluate',2,8)],
[('a','b',''),('b','c',''),('c','d',''),('d','a','fail'),('d','e','pass'),('e','f',''),('f','g',''),('g','h','pass'),('g','i','incident'),('i','j',''),('j','a','new candidate')])]

def svg(title,nodes,edges):
    W=1050; bw=260; bh=56; step=100; top=30
    pos={n:(35+col*350,top+row*step) for n,t,col,row in nodes}
    H=max(y for x,y in pos.values())+bh+35
    out=[f'<svg role="img" aria-label="{html.escape(title)}" viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg"><defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8" fill="#64748b"/></marker></defs>']
    for a,b,label in edges:
        x,y=pos[a]; xx,yy=pos[b]
        if xx==x:
            if yy>y: sx,sy,ex,ey=x+bw/2,y+bh,xx+bw/2,yy
            else: sx,sy,ex,ey=x+bw,y+bh/2,xx+bw,yy+bh/2
            if yy>y: path=f'M{sx} {sy} L{ex} {ey}'; lx,ly=sx+8,(sy+ey)/2
            else:
                bend=x+bw+24
                path=f'M{sx} {sy} H{bend} V{ey} H{ex}'; lx,ly=bend+3,(sy+ey)/2
        elif yy==y:
            sx=x+bw if xx>x else x; ex=xx if xx>x else xx+bw
            sy=ey=y+bh/2; path=f'M{sx} {sy} L{ex} {ey}'; lx,ly=(sx+ex)/2,sy-9
        else:
            sx=x+bw/2; sy=y+bh if yy>y else y; ex=xx+bw/2; ey=yy if yy>y else yy+bh
            mid=(sy+ey)/2; path=f'M{sx} {sy} V{mid} H{ex} V{ey}'; lx,ly=(sx+ex)/2,mid-7
        out.append(f'<path d="{path}" stroke="#64748b" stroke-width="1.7" fill="none" marker-end="url(#arrow)"/>')
        if label: out.append(f'<text x="{lx}" y="{ly}" font-size="12" fill="#334155" style="paint-order:stroke;stroke:white;stroke-width:4">{html.escape(label)}</text>')
    for n,t,col,row in nodes:
        x,y=pos[n]; fill='#ecfdf5' if any(w in t.lower() for w in ['approved','verified','validated','pass']) else '#f1f5f9'
        out.append(f'<rect x="{x}" y="{y}" width="{bw}" height="{bh}" rx="9" fill="{fill}" stroke="#94a3b8"/><text x="{x+bw/2}" y="{y+bh/2+5}" text-anchor="middle" font-size="15" fill="#0f172a">{html.escape(t)}</text>')
    return ''.join(out)+'</svg>'

src=(ROOT/'IMPLEMENTATION_PLAN.md').read_text()
blocks=re.findall(r'```mermaid\n(.*?)```',src,re.S)
assert len(blocks)==len(D),(len(blocks),len(D))
figures=[]
for i,((title,nodes,edges),block) in enumerate(zip(D,blocks),1):
    fig=svg(title,nodes,edges)
    (ROOT/f'diagram-{i:02d}.svg').write_text(fig)
    figures.append(f'<figure><figcaption>Figure {i} · {html.escape(title)}</figcaption>{fig}<details><summary>Editable Mermaid source</summary><pre>{html.escape(block)}</pre></details></figure>')
index=iter(range(len(D)))
src=re.sub(r'```mermaid\n.*?```',lambda m:f'\n\nDIAGRAMPLACEHOLDER{next(index)}END\n\n',src,flags=re.S)
body=markdown.markdown(src,extensions=['tables','fenced_code','toc'])
for i,fig in enumerate(figures):body=body.replace(f'<p>DIAGRAMPLACEHOLDER{i}END</p>',fig)
css='''body{margin:0;background:#f3f5f8;color:#172033;font:16px/1.65 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}main{max-width:1080px;margin:40px auto;padding:56px 64px;background:white;box-shadow:0 5px 30px #132b4510}h1{font-size:38px;line-height:1.18;letter-spacing:-1px}h2{margin-top:52px;font-size:27px;line-height:1.3;border-top:1px solid #dbe2ec;padding-top:24px}h3{margin-top:30px;font-size:20px}a{color:#096b70}table{border-collapse:collapse;width:100%;font-size:14px;margin:24px 0}th,td{border:1px solid #d6dee8;padding:11px 13px;text-align:left;vertical-align:top}th{background:#e8f0f6}tr:nth-child(even){background:#f8fafc}pre{overflow:auto;white-space:pre-wrap;background:#f1f5f9;border-radius:8px;padding:20px;font:13px/1.6 ui-monospace,monospace}code{font-size:.9em}figure{margin:28px 0;padding:20px;border:1px solid #d6dee8;border-radius:12px;break-inside:avoid}figcaption{font-weight:650;margin-bottom:12px}svg{display:block;width:100%;height:auto;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}details{font-size:13px;margin-top:16px;color:#475569}summary{cursor:pointer}nav{background:#eff7f7;padding:18px 24px;border-radius:10px}button{border:0;background:#096b70;color:white;padding:10px 18px;border-radius:7px;cursor:pointer}@media(max-width:800px){main{margin:0;padding:24px}h1{font-size:30px}table{display:block;overflow:auto}figure{padding:8px}}@media print{body{background:white;font-size:10pt}main{margin:0;padding:0;box-shadow:none;max-width:none}h2{break-before:page}figure{max-height:none}details,nav{display:none}table{font-size:8pt}a{color:inherit}svg{max-height:230mm}}'''
page=f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Women’s Health AI Agent Implementation Plan</title><style>{css}</style></head><body><main><nav>Team handoff · 5 November 2026 · Offline document with eight rendered diagrams</nav>{body}</main></body></html>'
(ROOT/'IMPLEMENTATION_PLAN.html').write_text(page)
print(f'Created HTML with {len(D)} inline SVG diagrams; {len(src.split())} words in plan')
