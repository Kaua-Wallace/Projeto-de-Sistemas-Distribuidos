import io
import os
import tempfile
import httpx
import pytest

from common import logging_config

os.environ["STORAGE_ROOT"] = tempfile.mkdtemp()

from fastapi.testclient import TestClient
from PIL import Image
from gallery_service import main as galeria
from processing_service import main as processamento
from processing_service.main import app as app_proc


@pytest.fixture
def gal(monkeypatch):
    # Limpa os estados antes de cada teste
    (galeria.STORAGE / "galeria.db").unlink(missing_ok=True)
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


def test_listagem_filtra_ordena_e_pagina_imagens(gal):
    headers = logar(gal)
    imagens = [
        ("ana-antiga", "ana", "2026-01-01T10:00:00"),
        ("bia-meio", "bia", "2026-01-02T10:00:00"),
        ("ana-nova", "ana", "2026-01-03T10:00:00"),
    ]
    for img_id, autor, data in imagens:
        galeria.imagens[img_id] = {
            "id": img_id,
            "autor": autor,
            "data": data,
            "nome": f"{img_id}.png",
            "tamanho": 123,
            "url_miniatura": f"/images/{img_id}/thumbnail",
        }

    ascendente = gal.get(
        "/images?autor=ana&ordem=data_asc",
        headers=headers,
    ).json()
    assert [imagem["id"] for imagem in ascendente] == ["ana-antiga", "ana-nova"]

    descendente = gal.get("/images?ordem=data_desc", headers=headers).json()
    assert [imagem["id"] for imagem in descendente] == [
        "ana-nova", "bia-meio", "ana-antiga"
    ]

    pagina = gal.get(
        "/images?ordem=data_asc&limit=1&offset=1",
        headers=headers,
    ).json()
    assert [imagem["id"] for imagem in pagina] == ["bia-meio"]
    assert pagina[0]["nome"] == "bia-meio.png"
    assert pagina[0]["tamanho"] == 123

    sem_resultados = gal.get("/images?autor=desconhecido", headers=headers).json()
    assert sem_resultados == []


def test_historico_ordenado_com_url_e_isolado_por_usuario(gal):
    headers = logar(gal)
    galeria.historico.extend([
        {
            "usuario": "ana",
            "image_id": "ana-antiga",
            "nome": "antiga.png",
            "data": "2026-01-01T10:00:00",
        },
        {
            "usuario": "bia",
            "image_id": "bia-imagem",
            "nome": "bia.png",
            "data": "2026-01-03T10:00:00",
        },
        {
            "usuario": "ana",
            "image_id": "ana-nova",
            "nome": "nova.png",
            "data": "2026-01-02T10:00:00",
        },
    ])

    historico = gal.get("/history", headers=headers).json()
    assert [envio["image_id"] for envio in historico] == [
        "ana-nova", "ana-antiga"
    ]
    assert [envio["url_miniatura"] for envio in historico] == [
        "/images/ana-nova/thumbnail",
        "/images/ana-antiga/thumbnail",
    ]


def test_upload_inclui_usuario_no_log_do_processamento(gal, monkeypatch):
    eventos = []

    def capturar_evento(evento, **campos):
        eventos.append({"evento": evento, **campos})
    monkeypatch.setattr(
        logging_config,
        "log_evento",
        capturar_evento,
    )
    monkeypatch.setattr(
        processamento,
        "log_evento",
        capturar_evento,
    )
    h = logar(gal)
    resposta = gal.post(
        "/images",
        headers=h,
        files={"file": ("foto.png", png(), "image/png")},
    )

    assert resposta.status_code == 201
    eventos_processamento = [
        evento for evento in eventos if evento.get("servico") == "processing"
    ]
    assert {
        evento["evento"] for evento in eventos_processamento
    } >= {"http_request", "thumbnail_entrada", "thumbnail_resultado"}
    assert all(evento.get("usuario") == "ana" for evento in eventos_processamento)


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

def test_dados_sobrevivem_ao_reinicio(gal):
    headers = logar(gal)
    r = gal.post("/images", headers=headers,
                 files={"file": ("foto.png", png(), "image/png")})
    assert r.status_code == 201
    iid = r.json()["id"]

    # Reinício simulado: memória zerada, banco preservado
    galeria.usuarios.clear(); galeria.tokens.clear()
    galeria.imagens.clear(); galeria.historico.clear()
    with TestClient(galeria.app) as novo:
        assert [i["id"] for i in novo.get("/images", headers=headers).json()] == [iid]
        assert novo.get("/history", headers=headers).json()[0]["image_id"] == iid
        assert novo.post("/auth/login", json={"username": "ana", "password": "segredo"}).status_code == 200

def test_logout_invalida_token(gal):
    headers = logar(gal)
    assert gal.post("/auth/logout", headers=headers).status_code == 204
    assert gal.get("/images", headers=headers).status_code == 401

def test_token_expirado_e_rejeitado(gal):
    headers = logar(gal)
    for t in galeria.tokens_expira:
        galeria.tokens_expira[t] = 0
    assert gal.get("/images", headers=headers).status_code == 401