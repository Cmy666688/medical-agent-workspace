"""Native Chinese character-bigram BM25; no LangChain dependency."""
import math,re
from collections import Counter,defaultdict

def tokens(text):
    parts=re.findall(r'[\u4e00-\u9fff]+|[a-z0-9]+',text.lower())
    result=[]
    for part in parts:
        result.extend([part] if not re.search(r'[\u4e00-\u9fff]',part) or len(part)<2 else [part[i:i+2] for i in range(len(part)-1)])
    return result

class KeywordIndex:
    def __init__(self,records):
        self.postings=defaultdict(dict); self.lengths={}; self.names={}
        for row in records:
            key=row['_id']['$oid']; name=row.get('name',''); self.names[key]=name
            counts=Counter(tokens((name+' ')*3+' '.join(row.get('symptom',[]))+' '+row.get('desc','')[:160]))
            self.lengths[key]=sum(counts.values())
            for token,count in counts.items(): self.postings[token][key]=count
        self.average=sum(self.lengths.values())/max(1,len(self.lengths))
    def search(self,query,k=20):
        scores=defaultdict(float); count=len(self.lengths)
        for term in set(tokens(query)):
            found=self.postings.get(term,{})
            idf=math.log(1+(count-len(found)+.5)/(len(found)+.5))
            for key,tf in found.items():
                scores[key]+=idf*tf*2.5/(tf+1.5*(.25+.75*self.lengths[key]/max(1,self.average)))
        for key,name in self.names.items():
            if name and name in query: scores[key]+=100
        return sorted(scores,key=scores.get,reverse=True)[:k]

def fuse(*rankings):
    scores=defaultdict(float)
    for ranking in rankings:
        for rank,key in enumerate(ranking,1): scores[key]+=1/(60+rank)
    return sorted(scores,key=scores.get,reverse=True)
