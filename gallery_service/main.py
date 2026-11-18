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

@app.post("/auth/login")
def login(c: Credenciais):
    if usuarios.get(c.username) != hash_senha(c.password):
        raise HTTPException(401, "Credenciais inválidas")
    token = secrets.token_urlsafe(24)
    tokens[token] = c.username
    return {"token": token}


# Imagens

@app.post("/images", status_code=201)
async def upload(file: UploadFile = File(...), usuario: str = Depends(usuario_logado)):
    if file.content_type not in TIPOS_ACEITOS:
        raise HTTPException(415, f"Tipo não aceito. Use: {list(TIPOS_ACEITOS)}")
    dados = await file.read()
    if not dados:
        raise HTTPException(400, "Arquivo vazio")
    if len(dados) > TAMANHO_MAX:
        raise HTTPException(413, "Arquivo maior que 5 MB")

    # chama o Serviço de Processamento para gerar a miniatura
    try:
        r = httpx.post(
            f"{PROCESSING_URL}/internal/thumbnail",
            files={"file": (file.filename, dados, file.content_type)},
            timeout=10,
        )
    except httpx.HTTPError:
        raise HTTPException(503, "Serviço de Processamento indisponível")
    if r.status_code != 200:
        codigo = r.status_code if r.status_code in (415, 422) else 502
        raise HTTPException(codigo, "Falha ao gerar miniatura")
    return {"nome": file.filename, "tipo": file.content_type, "tamanho": len(dados)}
