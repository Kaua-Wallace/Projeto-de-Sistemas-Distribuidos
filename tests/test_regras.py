# testes de autenticação, regras de negocio e codigos de erro da Galeria 

import hashlib
import io
import os
import uuid
from datetime import datetime
from urllib.parse import unquote
import httpx

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from gallery_service import main as galeria
from processing_service.main import app as app_proc

gal = None

def png() -> bytes:
    b = io.BytesIO()
    Image.new("RGB", (800, 600), "blue").save(b, "PNG")
    return b.getvalue()


# isolamento e utilitarios

def _limpar_estado():
    galeria.usuarios.clear()
    galeria.tokens.clear()
    galeria.imagens.clear()
    galeria.historico.clear()


@pytest.fixture(autouse=True)
def estado_limpo(monkeypatch, tmp_path):
    global gal
    _limpar_estado()
    monkeypatch.setattr(
        galeria,
        "STORAGE",
        tmp_path
    )
    # Cliente de teste que comunica com o Processamento via ASGI
    def cliente_processamento_teste():

        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app_proc),
            base_url=galeria.PROCESSING_URL,
            timeout=galeria.PROCESSING_TIMEOUT_SECONDS
        )
    monkeypatch.setattr(
        galeria,
        "criar_cliente_processamento",
        cliente_processamento_teste
    )
    # Inicia o lifespan e disponibiliza o TestClient aos testes

    with TestClient(galeria.app) as cliente:
        gal = cliente
        yield
    _limpar_estado()

def cadastrar_e_logar(username: str, senha: str = "segredo") -> dict:
    cred = {"username": username, "password": senha}
    assert gal.post("/auth/register", json=cred).status_code == 201
    token = gal.post("/auth/login", json=cred).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def inserir_imagem(autor: str, nome: str = "foto.png") -> str:
    """Cria uma imagem direto no estado e no disco (sem passar pelo Processamento)."""
    img_id = str(uuid.uuid4())
    pasta_o = galeria.STORAGE / "originals" / autor
    pasta_t = galeria.STORAGE / "thumbnails" / autor
    pasta_o.mkdir(parents=True, exist_ok=True)
    pasta_t.mkdir(parents=True, exist_ok=True)
    caminho_o = pasta_o / f"{img_id}.png"
    caminho_t = pasta_t / f"{img_id}.jpg"
    caminho_o.write_bytes(png())
    caminho_t.write_bytes(b"miniatura-fake")
    agora = datetime.now().isoformat(timespec="seconds")
    galeria.imagens[img_id] = {
        "id": img_id, "autor": autor, "data": agora, "nome": nome,
        "tipo": "image/png", "tamanho": len(png()),
        "caminho_original": str(caminho_o), "caminho_miniatura": str(caminho_t),
        "url_miniatura": f"/images/{img_id}/thumbnail",
    }
    galeria.historico.append(
        {"usuario": autor, "image_id": img_id, "nome": nome, "data": agora}
    )
    return img_id


# hash de senha

def test_hash_tem_salt_e_nao_guarda_senha():
    h1, h2 = galeria.hash_senha("segredo"), galeria.hash_senha("segredo")
    assert h1 != h2                              # salt aleatorio
    assert h1.startswith("pbkdf2_sha256$")
    assert "segredo" not in h1
    assert h1 != hashlib.sha256(b"segredo").hexdigest()


def test_verificar_senha():
    h = galeria.hash_senha("segredo")
    assert galeria.verificar_senha("segredo", h)
    assert not galeria.verificar_senha("errada1", h)
    assert not galeria.verificar_senha("segredo", None)
    assert not galeria.verificar_senha("segredo", "lixo-sem-formato")


def test_cadastro_guarda_hash_e_login_funciona():
    cadastrar_e_logar("ana")
    assert galeria.usuarios["ana"].startswith("pbkdf2_sha256$")
    assert "segredo" not in galeria.usuarios["ana"]


def test_mesma_senha_gera_hashes_diferentes():
    cadastrar_e_logar("ana")
    cadastrar_e_logar("bruno")
    assert galeria.usuarios["ana"] != galeria.usuarios["bruno"]


def test_login_usuario_inexistente_401():
    r = gal.post("/auth/login", json={"username": "fantasma", "password": "segredo"})
    assert r.status_code == 401


def test_cadastro_duplicado_409():
    cadastrar_e_logar("ana")
    r = gal.post("/auth/register", json={"username": "ana", "password": "outra123"})
    assert r.status_code == 409


# token invalido (401)

ROTAS_PROTEGIDAS = [
    ("get", "/images"),
    ("get", "/images/xyz/thumbnail"),
    ("get", "/images/xyz/download"),
    ("get", "/history"),
]


@pytest.mark.parametrize("metodo,rota", ROTAS_PROTEGIDAS)
@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer token-falso"}])
def test_rotas_protegidas_exigem_token_valido(metodo, rota, headers):
    assert gal.request(metodo, rota, headers=headers).status_code == 401


def test_upload_com_token_falso_401():
    arq = {"file": ("a.png", png(), "image/png")}
    r = gal.post("/images", headers={"Authorization": "Bearer falso"}, files=arq)
    assert r.status_code == 401


# listagem, previa, download, historico

def test_listagem_tem_so_os_campos_publicos():
    h = cadastrar_e_logar("ana")
    inserir_imagem("ana")
    lista = gal.get("/images", headers=h).json()
    assert len(lista) == 1
    assert set(lista[0]) == {
        "id", "autor", "data", "nome", "tamanho", "url_miniatura"
    }


def test_listagem_mostra_imagens_de_todos_os_usuarios():
    h = cadastrar_e_logar("ana")
    inserir_imagem("ana")
    inserir_imagem("bruno")
    autores = {i["autor"] for i in gal.get("/images", headers=h).json()}
    assert autores == {"ana", "bruno"}


def test_previa_e_download_ok():
    h = cadastrar_e_logar("ana")
    iid = inserir_imagem("ana", nome="minha foto.png")
    previa = gal.get(f"/images/{iid}/thumbnail", headers=h)
    assert previa.status_code == 200
    assert previa.headers["content-type"] == "image/jpeg"
    down = gal.get(f"/images/{iid}/download", headers=h)
    assert down.status_code == 200
    assert down.content == png()
    assert "minha foto.png" in unquote(down.headers["content-disposition"])


def test_imagem_inexistente_404():
    h = cadastrar_e_logar("ana")
    assert gal.get("/images/nao-existe/thumbnail", headers=h).status_code == 404
    assert gal.get("/images/nao-existe/download", headers=h).status_code == 404


def test_miniatura_removida_do_disco_404():
    h = cadastrar_e_logar("ana")
    iid = inserir_imagem("ana")
    os.remove(galeria.imagens[iid]["caminho_miniatura"])
    assert gal.get(f"/images/{iid}/thumbnail", headers=h).status_code == 404


def test_original_removido_do_disco_404():
    h = cadastrar_e_logar("ana")
    iid = inserir_imagem("ana")
    os.remove(galeria.imagens[iid]["caminho_original"])
    assert gal.get(f"/images/{iid}/download", headers=h).status_code == 404


def test_historico_isolado_por_usuario():
    h_ana = cadastrar_e_logar("ana")
    h_bruno = cadastrar_e_logar("bruno")
    id_ana = inserir_imagem("ana")
    id_bruno = inserir_imagem("bruno")
    hist_ana = gal.get("/history", headers=h_ana).json()
    hist_bruno = gal.get("/history", headers=h_bruno).json()
    assert [x["image_id"] for x in hist_ana] == [id_ana]
    assert [x["image_id"] for x in hist_bruno] == [id_bruno]
    assert all(x["usuario"] == "ana" for x in hist_ana)


# path traversal

def test_nome_malicioso_nao_escapa_do_storage(tmp_path):
    h = cadastrar_e_logar("ana")
    arq = {"file": ("../../fuga.png", png(), "image/png")}
    r = gal.post("/images", headers=h, files=arq)
    assert r.status_code == 201
    assert "/" not in r.json()["nome"]
    # nada foi gravado fora da pasta de storage
    assert not (tmp_path.parent / "fuga.png").exists()
    assert not (tmp_path.parent.parent / "fuga.png").exists()
    # tudo foi gravado em storage/<originals|thumbnails>/ana/<uuid>.<ext>
    for arquivo in tmp_path.rglob("*"):
        if arquivo.is_file() and not arquivo.name.startswith("galeria.db"):
            assert arquivo.parent.parent.name in ("originals", "thumbnails")
            assert arquivo.parent.name == "ana"
    down = gal.get(f"/images/{r.json()['id']}/download", headers=h)
    assert ".." not in down.headers["content-disposition"]


# codigos de erro do upload

def test_upload_413_arquivo_grande(monkeypatch):
    h = cadastrar_e_logar("ana")
    monkeypatch.setattr(galeria, "TAMANHO_MAX", 10)
    arq = {"file": ("a.png", png(), "image/png")}
    assert gal.post("/images", headers=h, files=arq).status_code == 413


def test_upload_415_tipo_invalido():
    h = cadastrar_e_logar("ana")
    arq = {"file": ("a.txt", b"oi", "text/plain")}
    assert gal.post("/images", headers=h, files=arq).status_code == 415


def test_upload_422_sem_arquivo():
    h = cadastrar_e_logar("ana")
    assert gal.post("/images", headers=h).status_code == 422


def test_upload_422_imagem_corrompida_repassado():
    h = cadastrar_e_logar("ana")
    arq = {"file": ("a.png", b"nao-e-png", "image/png")}
    assert gal.post("/images", headers=h, files=arq).status_code == 422
    assert galeria.imagens == {} and galeria.historico == []


def test_upload_503_processamento_fora(monkeypatch):
    h = cadastrar_e_logar("ana")
    async def falha_conexao(*args, **kwargs):
        raise httpx.ConnectError("Falha simulada")
    monkeypatch.setattr(
        galeria.app.state.processing_client,
        "post",
        falha_conexao
    )
    arq = {
        "file": (
            "a.png",
            png(),
            "image/png"
        )
    }
    assert gal.post(
        "/images",
        headers=h,
        files=arq
    ).status_code == 503
    assert galeria.imagens == {}
    assert galeria.historico == []
