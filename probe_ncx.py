# Diagnostic: validate NCX and OPF references, list non-note links, html TOC files.
import os, re, collections
from lxml import etree
os.chdir(os.path.dirname(os.path.abspath(__file__)))  # read unpacked/ next to this script
for b in sorted(os.listdir('unpacked')):
    o=f'unpacked/{b}/OEBPS'; text=o+'/Text'
    ids={f:set() for f in os.listdir(text)}
    for f in os.listdir(text):
        for m in re.finditer(r'\bid="([^"]+)"',open(os.path.join(text,f),encoding='utf-8').read()): ids[f].add(m.group(1))
    ncx=open(o+'/toc.ncx',encoding='utf-8').read()
    bad=[s for s in re.findall(r'<content src="([^"]+)"',ncx) if (lambda p,fr:(os.path.basename(p) not in ids) or (fr and fr not in ids[os.path.basename(p)]))(*s.partition('#')[::2])]
    po=re.findall(r'playOrder="(\d+)"',ncx); dupPO=len(po)-len(set(po))
    opf=open(o+'/content.opf',encoding='utf-8').read()
    hrefs=re.findall(r'href="([^"]+)"',opf); missing=[h for h in hrefs if not os.path.exists(os.path.join(o,h.split('#')[0]))]
    unlisted=[f for f in os.listdir(text) if 'Text/'+f not in hrefs]
    guide=re.findall(r'<reference[^>]*>',opf)
    other=collections.Counter()
    for f in os.listdir(text):
        for h in re.findall(r'<a [^>]*href="([^"]+)"',open(os.path.join(text,f),encoding='utf-8').read()):
            if not re.search(r'nota|nt\d|#rf|#nt',h): other[re.sub(r'\d+','N',h)]+=1
    print(f'== {b}: ncx bad={bad[:5]} dupPlayOrder={dupPO} opf missing={missing} unlisted={unlisted} guide={guide}')
    print('   other links:',other.most_common(8))
