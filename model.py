"""AutoBrillo AI v2 - motor de decisión algorítmica local.

No contiene secretos ni realiza llamadas externas. Combina aprendizaje textual
ligero con un motor de evaluación para comparar candidatos y elegir acciones.
"""
from __future__ import annotations
import json, math, os, re, tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

MODEL_PATH = Path(os.environ.get("AUTOBRILLO_MODEL", "model_data.json"))
TOKEN_RE = re.compile(r"[\wáéíóúüñ]+", re.IGNORECASE)

class AutoBrilloBrain:
    def __init__(self, path: Optional[str] = None):
        self.path = Path(path or MODEL_PATH)
        self.examples: List[Dict[str, str]] = []
        self.labels = Counter(); self.words = defaultdict(Counter); self.total_words = Counter()
        self.outcomes: List[Dict[str, Any]] = []
        self._load()

    @property
    def ready(self) -> bool:
        return bool(self.examples and self.labels)

    @staticmethod
    def _tokens(text: str) -> List[str]:
        return [x.lower() for x in TOKEN_RE.findall(str(text)) if len(x) > 1]

    def _load(self) -> None:
        if not self.path.exists(): return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.examples = list(data.get("examples", []))[-5000:]
            self.outcomes = list(data.get("outcomes", []))[-2000:]
            self._rebuild()
        except (OSError, ValueError, TypeError):
            self.examples=[]; self.outcomes=[]; self._rebuild()

    def _rebuild(self):
        self.labels.clear(); self.words.clear(); self.total_words.clear()
        for item in self.examples:
            text=str(item.get("text","")); label=str(item.get("label","" )).strip()
            if not text or not label: continue
            self.labels[label]+=1
            for token in self._tokens(text):
                self.words[label][token]+=1; self.total_words[label]+=1

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload={"version":2,"examples":self.examples[-5000:],"outcomes":self.outcomes[-2000:]}
        fd,tmp=tempfile.mkstemp(prefix=self.path.name+".",dir=str(self.path.parent))
        try:
            with os.fdopen(fd,"w",encoding="utf-8") as f: json.dump(payload,f,ensure_ascii=False,indent=2)
            os.replace(tmp,self.path)
        finally:
            if os.path.exists(tmp): os.unlink(tmp)

    def add_examples(self, examples: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
        added=0
        for item in examples:
            text=str(item.get("text","")).strip(); label=str(item.get("label","")).strip()
            if text and label: self.examples.append({"text":text,"label":label}); added+=1
        self.examples=self.examples[-5000:]; self._rebuild()
        if added: self._save()
        return {"added":added,"total":len(self.examples),"labels":len(self.labels)}

    def predict(self, text: str, top_k: int=3) -> List[Dict[str, Any]]:
        if not self.ready: return []
        tokens=self._tokens(text); vocab=set()
        for c in self.words.values(): vocab.update(c)
        vs=max(1,len(vocab)); total=sum(self.labels.values()); results=[]
        for label,count in self.labels.items():
            logp=math.log(count/total); denom=self.total_words[label]+vs
            for t in tokens: logp += math.log((self.words[label][t]+1)/denom)
            results.append((label,logp))
        mx=max(s for _,s in results); ex=[(l,math.exp(s-mx)) for l,s in results]; z=sum(p for _,p in ex) or 1
        return [{"label":l,"confidence":round(p/z,6)} for l,p in sorted(ex,key=lambda x:x[1],reverse=True)[:max(1,int(top_k))]]

    def predict_label(self,text:str)->Optional[str]:
        r=self.predict(text,1); return r[0]["label"] if r else None

    @staticmethod
    def _clamp(x: float, lo: float=0.0, hi: float=1.0)->float:
        return max(lo,min(hi,float(x)))

    def evaluate_candidate(self, candidate: Dict[str, Any]) -> Dict[str, Any]:
        price=max(0.0,float(candidate.get("price",0) or 0)); profit=max(0.0,float(candidate.get("estimated_profit",candidate.get("commission",0)) or 0))
        clicks=max(0,float(candidate.get("clicks",0) or 0)); sales=max(0,float(candidate.get("sales",0) or 0))
        conversion=self._clamp(sales/clicks) if clicks else 0.0
        commission=max(0.0,float(candidate.get("commission_value",candidate.get("commission",0)) or 0))
        margin=self._clamp(profit/max(price,1.0)); revenue=self._clamp(commission/1000.0)
        trend=self._clamp(candidate.get("trend",0.5)); risk=self._clamp(candidate.get("risk",0.2)); confidence=self._clamp(candidate.get("confidence",0.5))
        # Explotación + exploración: la falta de datos reduce el castigo por riesgo.
        data_conf=self._clamp(math.log1p(clicks)/math.log1p(100)) if clicks else 0.0
        exploration=0.12*(1-data_conf)
        score=(0.30*margin + 0.25*conversion + 0.18*revenue + 0.12*trend + 0.10*confidence + exploration - 0.15*risk)
        score=self._clamp(score)
        reasons=[]
        if margin>=0.15: reasons.append("margen/beneficio atractivo")
        if conversion>=0.05: reasons.append("conversión favorable")
        if commission>0: reasons.append("comisión con valor económico")
        if trend>=0.65: reasons.append("tendencia positiva")
        if clicks<10: reasons.append("pocos datos: conviene probar antes de escalar")
        if risk>=0.6: reasons.append("riesgo elevado")
        return {"name":candidate.get("name"),"score":round(score,6),"metrics":{"conversion":round(conversion,6),"margin":round(margin,6),"revenue":round(revenue,6),"trend":round(trend,6),"risk":round(risk,6),"confidence":round(confidence,6),"data_confidence":round(data_conf,6)},"reasons":reasons}

    def think(self, context: Dict[str, Any]) -> Dict[str, Any]:
        candidates=context.get("candidates",[]) or []
        evaluated=[self.evaluate_candidate(c) for c in candidates]
        evaluated.sort(key=lambda x:x["score"],reverse=True)
        best=evaluated[0] if evaluated else None
        confidence=0.0
        if best:
            gap=best["score"]-(evaluated[1]["score"] if len(evaluated)>1 else 0)
            confidence=self._clamp(0.45*best["score"]+0.35*self._clamp(gap*4)+0.20*best["metrics"]["data_confidence"])
        decision="test" if best and best["metrics"]["data_confidence"]<0.25 else ("prioritize" if best else "wait")
        return {"decision":decision,"confidence":round(confidence,6),"selected":best,"alternatives":evaluated[:5],"reasons":best["reasons"] if best else ["no hay candidatos suficientes"],"policy":"decision algorítmica auditable; no ejecución financiera automática"}

    def learn_outcome(self, context: Dict[str, Any], action: str, reward: float, details: Optional[Dict[str, Any]]=None)->Dict[str,Any]:
        record={"action":str(action),"reward":float(reward),"context":context,"details":details or {}}
        self.outcomes.append(record); self.outcomes=self.outcomes[-2000:]; self._save()
        return {"stored":True,"outcomes":len(self.outcomes)}

    def stats(self)->Dict[str,Any]:
        return {"ready":self.ready,"examples":len(self.examples),"labels":dict(self.labels),"outcomes":len(self.outcomes),"model_path":str(self.path),"engine":"Naive Bayes + scoring + exploration/exploitation"}
