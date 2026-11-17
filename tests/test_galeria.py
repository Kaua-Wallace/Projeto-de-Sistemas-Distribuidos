import io
import os
import tempfile

os.environ["STORAGE_ROOT"] = tempfile.mkdtemp() # testes não sujam a pasta storage/

from fastapi.testclient import TestClient
from PIL import Image

from gallery_service import main as galeria

gal = TestClient(galeria.app)

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