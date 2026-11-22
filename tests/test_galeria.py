import io
import os
import tempfile

os.environ["STORAGE_ROOT"] = tempfile.mkdtemp() # testes não sujam a pasta storage/

from fastapi.testclient import TestClient
from PIL import Image

from gallery_service import main as galeria
from processing_service.main import app as app_proc

gal = TestClient(galeria.app)
proc = TestClient(app_proc)

def test_health():
    assert gal.get("/health").status_code == 200

def test_cadastro_validacoes():
    cad = {"username": "ab", "password": "segredo"}
    assert gal.post("/auth/register", json=cad).status_code == 422
    cad = {"username": "ana", "password": "123"}
    assert gal.post("/auth/register", json=cad).status_code == 422
    cad = {"username": "ana", "password": "segredo"}
    gal.post("/auth/register", json=cad)
    assert gal.post("/auth/register", json=cad).status_code == 409

def test_login():
    cred = {"username": "bia", "password": "segredo"}
    gal.post("/auth/register", json=cred)
    ok = gal.post("/auth/login", json=cred)
    assert ok.status_code == 200 and "token" in ok.json()
    erro = gal.post("/auth/login", json={"username": "bia", "password": "errada1"})
    assert erro.status_code == 401


def png():
    b = io.BytesIO()
    Image.new("RGB", (800, 600), "blue").save(b, "PNG")
    return b.getvalue()


class RespostaFake:
    """Faz a Galeria "chamar" o Processamento sem rede, usando o TestClient dele."""

    def __init__(self, r):
        self.status_code, self.content = r.status_code, r.content


def fake_post(url, files, timeout):
    return RespostaFake(proc.post("/internal/thumbnail", files=files))


def logar():
    cred = {"username": "ana", "password": "segredo"}
    gal.post("/auth/register", json=cred)
    token = gal.post("/auth/login", json=cred).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def test_fluxo_completo(monkeypatch):
    monkeypatch.setattr(galeria.httpx, "post", fake_post)
    h = logar()
    r = gal.post("/images", headers=h, files={"file": ("foto.png", png(), "image/png")})
    assert r.status_code == 201
    iid = r.json()["id"]
    lista = gal.get("/images", headers=h).json()
    assert lista[0]["autor"] == "ana"
    assert lista[0]["url_miniatura"].endswith("/thumbnail")
    previa = gal.get(f"/images/{iid}/thumbnail", headers=h)
    assert previa.headers["content-type"] == "image/jpeg"
    assert gal.get(f"/images/{iid}/download", headers=h).content == png()
    assert gal.get("/history", headers=h).json()[0]["image_id"] == iid


def test_upload_validacoes(monkeypatch):
    monkeypatch.setattr(galeria.httpx, "post", fake_post)
    h = logar()
    arq = {"file": ("a.png", png(), "image/png")}
    assert gal.post("/images", files=arq).status_code == 401
    txt = {"file": ("a.txt", b"oi", "text/plain")}
    assert gal.post("/images", headers=h, files=txt).status_code == 415
    vazio = {"file": ("a.png", b"", "image/png")}
    assert gal.post("/images", headers=h, files=vazio).status_code == 400
    assert gal.post("/images", headers=h).status_code == 422
    monkeypatch.setattr(galeria, "TAMANHO_MAX", 10)
    assert gal.post("/images", headers=h, files=arq).status_code == 413
