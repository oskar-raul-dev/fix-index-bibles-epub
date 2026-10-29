# Diagnostic: check note links round-trip (verse -> note -> back to the same verse anchor).
import os, re, collections
from lxml import etree
os.chdir(os.path.dirname(os.path.abspath(__file__)))  # read unpacked/ next to this script
def parse(p):
    raw=open(p,encoding='utf-8').read().replace('&nbsp;','&#160;')
    return etree.fromstring(raw.encode('utf-8'))
for b in sorted(os.listdir('unpacked')):
    text=f'unpacked/{b}/OEBPS/Text'; docs={f:parse(os.path.join(text,f)) for f in os.listdir(text)}
    byid={}
    for f,d in docs.items():
        for el in d.iter():
            if el.get('id'): byid[(f,el.get('id'))]=el
    def links_in(el):
        return [a for a in el.iter() if isinstance(a.tag,str) and a.tag.endswith('}a') and a.get('href')]
    def resolve(f,h):
        p,_,fr=h.partition('#'); return (os.path.basename(p) if p else f, fr)
    stats=collections.Counter(); ex=[]
    for f,d in docs.items():
        for a in links_in(d):
            if not a.get('id'): continue
            tf,tid=resolve(f,a.get('href'))
            tgt=byid.get((tf,tid))
            if tgt is None: stats['fwd_missing']+=1; continue
            # the note container: the element with that id, or its parent <p> if it is an empty <a id>
            box=tgt if len(tgt) or (tgt.text or '').strip() else tgt.getparent()
            backs=[resolve(tf,x.get('href')) for x in links_in(box)]
            if not backs: stats['no_back']+=1; ex.append(('noback',f,a.get('href'))) if len(ex)<6 else 0; continue
            if (f,a.get('id')) in backs: stats['ok']+=1
            else:
                stats['back_mismatch']+=1
                if len(ex)<8: ex.append(('mismatch',f,a.get('id'),a.get('href'),backs))
    print(b,dict(stats)); [print('   ',e) for e in ex]
