"""AutoBrillo AI HTTP API for Render."""
from __future__ import annotations

import os
from typing import Any, Dict, List

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from model import AutoBrilloBrain
from mercadolibre_oauth import MercadoLibreOAuth

app = FastAPI(title="AutoBrillo AI", version="3.1.0")
brain = AutoBrilloBrain()
ml = MercadoLibreOAuth()


class Example(BaseModel):
    text: str = Field(min_length=1)
    label: str = Field(min_length=1)


class LearnRequest(BaseModel):
    examples: List[Example] = Field(default_factory=list)


class PredictRequest(BaseModel):
    text: str = Field(min_length=1)
    top_k: int = Field(default=3, ge=1, le=10)


class OutcomeRequest(BaseModel):
    context: Dict[str, Any] = Field(default_factory=dict)
    action: str = Field(min_length=1)
    reward: float
    details: Dict[str, Any] = Field(default_factory=dict)


class ThinkRequest(BaseModel):
    candidates: List[Dict[str, Any]] = Field(default_factory=list)


@app.get("/")
def root():
    return {"name": "AutoBrillo AI", "version": "3.1.0", "status": "online"}


@app.get("/health")
def health():
    return {"status": "ok", "brain": brain.stats(), "mercadolibre": ml.status()}


@app.get("/stats")
def stats():
    return brain.stats()


@app.post("/predict")
def predict(payload: PredictRequest):
    return {"text": payload.text, "predictions": brain.predict(payload.text, payload.top_k)}


@app.post("/learn")
def learn(payload: LearnRequest):
    return brain.add_examples([x.model_dump() for x in payload.examples])


@app.post("/think")
def think(payload: ThinkRequest):
    return brain.think(payload.model_dump())


@app.post("/learn/outcome")
def learn_outcome(payload: OutcomeRequest):
    return brain.learn_outcome(payload.context, payload.action, payload.reward, payload.details)


@app.get("/mercadolibre/status")
def mercado_status():
    try:
        return ml.status()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/mercadolibre/authorize")
def mercado_authorize():
    try:
        return {"authorization_url": ml.start()}
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/mercadolibre/callback")
def mercado_callback(code: str, state: str):
    try:
        ml.exchange(code, state)
        # Never return OAuth tokens to the browser/client.
        return {"authorized": True, "message": "Mercado Libre autorizado correctamente"}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
