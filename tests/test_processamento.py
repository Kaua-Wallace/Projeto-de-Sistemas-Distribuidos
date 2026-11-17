
import io

from fastapi.testclient import TestClient
from PIL import Image

from processing_service.main import app

client = TestClient(app)

def png():
    b = io.BytesIO()
    Image.new("RGB", (800, 600), "blue").save(b, "PNG")
    return b.getvalue()

def test_health():
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"

def test_gera_miniatura():
    r = client.post("/internal/thumbnail", files={"file": ("a.png", png(), "image/png")})
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/jpeg"
    assert max(Image.open(io.BytesIO(r.content)).size) <= 256

def test_tipo_invalido():
    r = client.post("/internal/thumbnail", files={"file": ("a.txt", b"oi", "text/plain")})
    assert r.status_code == 415

def test_arquivo_vazio():
    r = client.post("/internal/thumbnail", files={"file": ("a.png", b"", "image/png")})
    assert r.status_code == 400

def test_imagem_corrompida():
    arq = {"file": ("a.png", b"nao-e-png", "image/png")}
    r = client.post("/internal/thumbnail", files=arq)
    assert r.status_code == 422

def test_sem_arquivo():
    assert client.post("/internal/thumbnail").status_code == 422
