import io
import os
import tempfile
import httpx
import pytest

os.environ["STORAGE_ROOT"] = tempfile.mkdtemp()

from fastapi.testclient import TestClient
from PIL import Image
from gallery_service import main as galeria
from processing_service.main import app as app_proc


@pytest.fixture
def gal(monkeypatch):
    # Limpa os estados antes de cada teste
    galeria.usuarios.clear()
    galeria.tokens.clear()
    galeria.imagens.clear()
    galeria.historico.clear()

    # Cria um AsyncClient que chama o Processamento diretamente
    def cliente_processamento_teste():

        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app_proc),
            base_url=galeria.PROCESSING_URL,
            timeout=galeria.PROCESSING_TIMEOUT_SECONDS
        )

    # Substitui a fábrica do cliente de produção pela versão de teste

    monkeypatch.setattr(
        galeria,
        "criar_cliente_processamento",
        cliente_processamento_teste
    )
    # O contexto inicia e encerra o lifespan da Galeria

    with TestClient(galeria.app) as cliente:
        yield cliente


def png():
    b = io.BytesIO()
    Image.new(
        "RGB",
        (800, 600),
        "blue"
    ).save(b, "PNG")
    return b.getvalue()


def logar(gal):
    cred = {
        "username": "ana",
        "password": "segredo"
    }
    gal.post("/auth/register", json=cred)
    token = gal.post(
        "/auth/login",
        json=cred
    ).json()["token"]
    return {
        "Authorization": f"Bearer {token}"
    }

def test_health(gal):
    assert gal.get("/health").status_code == 200

def test_cadastro_validacoes(gal):
    cad = {
        "username": "ab",
        "password": "segredo"
    }
    assert gal.post(
        "/auth/register",
        json=cad
    ).status_code == 422
    cad = {
        "username": "ana",
        "password": "123"
    }
    assert gal.post(
        "/auth/register",
        json=cad
    ).status_code == 422
    cad = {
        "username": "ana",
        "password": "segredo"
    }
    gal.post("/auth/register", json=cad)
    assert gal.post(
        "/auth/register",
        json=cad
    ).status_code == 409

def test_login(gal):
    cred = {
        "username": "bia",
        "password": "segredo"
    }
    gal.post("/auth/register", json=cred)
    ok = gal.post(
        "/auth/login",
        json=cred
    )
    assert ok.status_code == 200
    assert "token" in ok.json()
    erro = gal.post(
        "/auth/login",
        json={
            "username": "bia",
            "password": "errada1"
        }
    )
    assert erro.status_code == 401

def test_fluxo_completo(gal):
    h = logar(gal)
    r = gal.post(
        "/images",
        headers=h,
        files={
            "file": (
                "foto.png",
                png(),
                "image/png"
            )
        }
    )
    assert r.status_code == 201
    iid = r.json()["id"]
    lista = gal.get(
        "/images",
        headers=h
    ).json()
    assert lista[0]["autor"] == "ana"
    assert lista[0]["url_miniatura"].endswith("/thumbnail")
    previa = gal.get(
        f"/images/{iid}/thumbnail",
        headers=h
    )
    assert previa.headers["content-type"] == "image/jpeg"
    original = gal.get(
        f"/images/{iid}/download",
        headers=h
    )
    assert original.content == png()
    historico = gal.get(
        "/history",
        headers=h
    ).json()
    assert historico[0]["image_id"] == iid

def test_upload_validacoes(gal, monkeypatch):

    h = logar(gal)

    arq = {
        "file": (
            "a.png",
            png(),
            "image/png"
        )
    }

    # Sem autenticação

    assert gal.post(
        "/images",
        files=arq
    ).status_code == 401

    # Tipo inválido

    txt = {
        "file": (
            "a.txt",
            b"oi",
            "text/plain"
        )
    }

    assert gal.post(
        "/images",
        headers=h,
        files=txt
    ).status_code == 415

    # Arquivo vazio

    vazio = {
        "file": (
            "a.png",
            b"",
            "image/png"
        )
    }

    assert gal.post(
        "/images",
        headers=h,
        files=vazio
    ).status_code == 400

    # Arquivo não enviado

    assert gal.post(
        "/images",
        headers=h
    ).status_code == 422

    # Arquivo maior que o permitido

    monkeypatch.setattr(
        galeria,
        "TAMANHO_MAX",
        10
    )

    assert gal.post(
        "/images",
        headers=h,
        files=arq
    ).status_code == 413