"""Serviço de Galeria (porta 8001): autenticação, metadados, armazenamento e histórico."""

import hashlib
import os
import secrets
import uuid
from datetime import datetime
from pathlib import Path

import httpx
from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

app = FastAPI(title="Serviço de Galeria")

PROCESSING_URL = os.getenv("PROCESSING_URL", "http://localhost:8002")
RAIZ = Path(__file__).resolve().parents[1]
STORAGE = Path(os.getenv("STORAGE_ROOT", RAIZ / "storage"))
TIPOS_ACEITOS = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/gif": "gif",
    "image/webp": "webp",
}
TAMANHO_MAX = 5 * 1024 * 1024 # 5 MB

@app.get("/health")
def health():
    return {"status": "ok", "service": "gallery"}

# Estado central (em memória)

usuarios = {} # username -> hash da senha
tokens = {} # token -> username
imagens = {} # id -> metadados da imagem (ver rota de upload)
historico = [] # uploads: {usuario, image_id, nome, data}

class Credenciais(BaseModel):
    username: str
    password: str

def hash_senha(senha: str) -> str:
    return hashlib.sha256(senha.encode()).hexdigest()

def usuario_logado(authorization: str = Header(default="")) -> str:
    """Dependência: devolve o usuário do token Bearer ou responde 401."""
    token = authorization.removeprefix("Bearer ").strip()
    if token not in tokens:
        raise HTTPException(401, "Não autenticado")
    return tokens[token]

# Autenticação

@app.post("/auth/register", status_code=201)
def cadastrar(c: Credenciais):
    if not (3 <= len(c.username) <= 30) or len(c.password) < 6:
        raise HTTPException(422, "username: 3-30 caracteres; password: mínimo 6")
    if c.username in usuarios:
        raise HTTPException(409, "Usuário já existe")
    usuarios[c.username] = hash_senha(c.password)
    return {"username": c.username}

