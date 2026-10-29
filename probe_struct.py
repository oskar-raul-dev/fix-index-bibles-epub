# Diagnostic: per bible, which tags/classes mark book titles, chapters and verses.
import os, re, collections
os.chdir(os.path.dirname(os.path.abspath(__file__)))  # read unpacked/ next to this script
for b in sorted(os.listdir('unpacked')):
    text=f'unpacked/{b}/OEBPS/Text'
    h=collections.Counter(); sup=collections.Counter(); books=0
    for f in sorted(os.listdir(text)):
        s=open(os.path.join(text,f),encoding='utf-8').read()
        nv=len(re.findall(r'<sup[^>]*>\d+</sup>',s))
        if nv<20: continue
        books+=1
        for m in re.finditer(r'<(h\d)([^>]*)>(.*?)</\1>',s): 
            txt=re.sub('<[^>]+>','',m.group(3))
            h[(m.group(1),re.sub(r'id="[^"]*"','id=*',re.sub(r'title="[^"]*"','title=*',m.group(2))).strip(), 'NUM' if re.fullmatch(r'\s*\d+\s*',txt) else re.sub(r'\d+','N',txt)[:25])]+=1
        for m in re.finditer(r'<sup([^>]*)>(\d+)</sup>',s): sup[m.group(1).strip()]+=1
        for m in re.finditer(r'<(p|span)( class="[^"]*")?>\s*(<[^>]+>)*\s*(\d+)\s*<',s):
            pass
    print('==',b,'bookfiles',books); 
    for k,v in h.most_common(12): print('   ',v,k)
    print('   sup:',sup.most_common(4))
