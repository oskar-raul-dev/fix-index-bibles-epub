# Quick diagnostic: list broken internal links (missing file or missing anchor) per unpacked EPUB.
import sys, os, re, collections
from lxml import etree
os.chdir(os.path.dirname(os.path.abspath(__file__)))  # read unpacked/ next to this script
NS={'x':'http://www.w3.org/1999/xhtml'}
for b in sorted(os.listdir('unpacked')):
    text=f'unpacked/{b}/OEBPS/Text'
    ids={}; links=[]; dup=0; parse_err=[]
    for f in sorted(os.listdir(text)):
        try: t=etree.parse(os.path.join(text,f))
        except Exception as e: parse_err.append((f,str(e)[:80])); continue
        s=set()
        for el in t.iter():
            i=el.get('id')
            if i:
                if i in s: dup+=1
                s.add(i)
            if el.tag.endswith('}a') and el.get('href'): links.append((f,el.get('href')))
        ids[f]=s
    broken=collections.Counter(); ex=collections.defaultdict(list)
    for f,h in links:
        if re.match(r'^[a-z]+:',h): continue
        path,_,frag=h.partition('#')
        tgt=os.path.basename(path) if path else f
        if tgt not in ids: kind='nofile'
        elif frag and frag not in ids[tgt]: kind='noanchor'
        else: continue
        broken[kind]+=1
        if len(ex[kind])<4: ex[kind].append(f'{f} -> {h}')
    print(b,'links',len(links),'dupIds',dup,'broken',dict(broken),'parseErr',parse_err[:3])
    for k,v in ex.items(): print('   ',k,v)
