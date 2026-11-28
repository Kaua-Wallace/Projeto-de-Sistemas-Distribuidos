# testes de autenticação, regras de negocio e codigos de erro da Galeria 

import hashlib
import io
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from urllib.parse import unquote
import httpx

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from PIL import Image

from common import constantes
from gallery_service import main as galeria
from processing_service import main as processamento
from processing_service.main import app as app_proc

gal = None

def png() -> bytes:
    b = io.BytesIO()
    Image.new("RGB", (800, 600), "blue").save(b, "PNG")
    return b.getvalue()


def enviar(headers, nome="foto.png", dados=None, tipo="image/png"):
    return gal.post(
        "/images",
        headers=headers,
        files={"file": (nome, dados if dados is not None else png(), tipo)},
    )


def arquivos_no_disco(raiz):
    return [p for p in raiz.rglob("*") if p.is_file()]


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


# constantes centralizadas

def test_constantes_vem_do_modulo_comum():
    assert galeria.TAMANHO_MAX == constantes.TAMANHO_MAX == 5 * 1024 * 1024
    assert processamento.TAMANHO_MAX == constantes.TAMANHO_MAX
    assert galeria.TIPOS_ACEITOS is constantes.TIPOS_ACEITOS
    assert processamento.TIPOS_ACEITOS is constantes.TIPOS_ACEITOS
    assert processamento.FORMATO_PARA_MIME is constantes.FORMATO_PARA_MIME


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


# username

@pytest.mark.parametrize(
    "username",
    ["ana", "bruno123", "joao_silva", "maria.santos", "usuario-teste"],
)
def test_username_valido_aceito(username):
    r = gal.post("/auth/register", json={"username": username, "password": "segredo"})
    assert r.status_code == 201


@pytest.mark.parametrize(
    "username",
    [
        "ab",
        "usuário@teste",
        "../../pasta",
        "/etc",
        ".usuario",
        "nome com espaços",
        "a" * 31,
        "ana\n",
        "..\\..\\pasta",
        "C:\\Windows",
    ],
)
def test_username_invalido_422(username):
    r = gal.post("/auth/register", json={"username": username, "password": "segredo"})
    assert r.status_code == 422
    assert galeria.usuarios == {}


@pytest.mark.parametrize(
    "usuario",
    [
        "../../pasta",
        "..",
        ".",
        "a/b",
        "/etc",
        "../outro",
        "",
        "..\\..\\pasta",
        "a\\b",
        "C:\\Windows",
        "/tmp/absoluto",
    ],
)
def test_caminho_no_storage_rejeita_fuga(usuario):
    with pytest.raises(HTTPException) as erro:
        galeria.caminho_no_storage("originals", usuario, "x.png")
    assert erro.value.status_code == 422


@pytest.mark.parametrize(
    "nome_arquivo",
    ["../x.png", "..\\x.png", "/etc/passwd", "sub/x.png", "", "..", "."],
)
def test_caminho_no_storage_rejeita_nome_de_arquivo_malicioso(nome_arquivo):
    with pytest.raises(HTTPException) as erro:
        galeria.caminho_no_storage("originals", "ana", nome_arquivo)
    assert erro.value.status_code == 422


def test_caminho_no_storage_valido(tmp_path):
    caminho = galeria.caminho_no_storage("originals", "ana", "x.png")
    assert caminho == (tmp_path / "originals" / "ana" / "x.png").resolve()


def test_caminho_no_storage_rejeita_symlink_para_fora(tmp_path):
    fora = tmp_path.parent / f"fora_{uuid.uuid4().hex}"
    fora.mkdir()
    (tmp_path / "originals").mkdir()
    try:
        (tmp_path / "originals" / "ana").symlink_to(fora, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("links simbólicos indisponíveis neste ambiente")

    with pytest.raises(HTTPException) as erro:
        galeria.caminho_no_storage("originals", "ana", "x.png")
    assert erro.value.status_code == 422

    h = cadastrar_e_logar("ana")
    assert enviar(h).status_code == 422
    assert list(fora.iterdir()) == []
    assert galeria.imagens == {} and galeria.historico == []


# verifica se somete uma requisição consegue cadastrar o mesmo username simultaneamente
def test_cadastros_simultaneos_mesmo_username():
    cred = {"username": "corrida", "password": "segredo"}

    def tentar(_):
        return gal.post("/auth/register", json=cred).status_code

    with ThreadPoolExecutor(max_workers=10) as pool:
        codigos = list(pool.map(tentar, range(10)))

    assert codigos.count(201) == 1
    assert codigos.count(409) == 9
    assert 500 not in codigos
    assert list(galeria.usuarios) == ["corrida"]


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
    assert set(lista[0]) == {"id", "autor", "data", "nome", "url_miniatura"}


def test_listagem_devolve_nome_de_exibicao_unico():
    h = cadastrar_e_logar("ana")
    enviar(h)
    enviar(h)
    nomes = sorted(i["nome"] for i in gal.get("/images", headers=h).json())
    assert nomes == ["foto (2).png", "foto.png"]


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


# verifica se nomes maliciosos não permitem gravar arquivos fora da pasta de armazenamento

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
        if arquivo.is_file():
            assert arquivo.parent.parent.name in ("originals", "thumbnails")
            assert arquivo.parent.name == "ana"
    down = gal.get(f"/images/{r.json()['id']}/download", headers=h)
    assert ".." not in down.headers["content-disposition"]


def test_nome_com_barra_invertida_nao_vira_caminho(tmp_path):
    h = cadastrar_e_logar("ana")
    r = enviar(h, "..\\..\\fuga.png")
    assert r.status_code == 201
    assert "\\" not in r.json()["nome"]
    assert "/" not in r.json()["nome"]
    for arquivo in tmp_path.rglob("*"):
        if arquivo.is_file():
            assert arquivo.parent.name == "ana"


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


def test_upload_pdf_declarado_como_png_422(tmp_path):
    h = cadastrar_e_logar("ana")
    pdf = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF"
    assert enviar(h, "a.png", pdf).status_code == 422
    assert galeria.imagens == {} and galeria.historico == []
    assert arquivos_no_disco(tmp_path) == []


def test_upload_formato_diferente_do_declarado_422():
    h = cadastrar_e_logar("ana")
    b = io.BytesIO()
    Image.new("RGB", (50, 50), "red").save(b, "JPEG")
    assert enviar(h, "a.png", b.getvalue(), "image/png").status_code == 422


def test_upload_content_length_declarado_acima_do_limite_413(tmp_path):
    h = cadastrar_e_logar("ana")
    cabecalhos = {**h, "Content-Length": str(galeria.TAMANHO_MAX + 10 * 1024 * 1024)}
    r = gal.post(
        "/images",
        headers=cabecalhos,
        files={"file": ("a.png", png(), "image/png")},
    )
    assert r.status_code == 413
    assert galeria.imagens == {}
    assert arquivos_no_disco(tmp_path) == []


def test_upload_dentro_do_limite_aceito():
    h = cadastrar_e_logar("ana")
    assert enviar(h).status_code == 201


# persistencia atomica de arquivos

def caminhos_teste(raiz):
    return (
        raiz / "originals" / "ana" / "a.png",
        raiz / "thumbnails" / "ana" / "a.jpg",
    )


def test_persistir_grava_original_e_miniatura(tmp_path):
    original, miniatura = caminhos_teste(tmp_path)
    galeria.persistir_arquivos(original, miniatura, b"original", b"miniatura")
    assert original.read_bytes() == b"original"
    assert miniatura.read_bytes() == b"miniatura"


def test_persistir_nao_deixa_temporarios(tmp_path):
    original, miniatura = caminhos_teste(tmp_path)
    galeria.persistir_arquivos(original, miniatura, b"o", b"m")
    nomes = sorted(p.name for p in arquivos_no_disco(tmp_path))
    assert nomes == ["a.jpg", "a.png"]
    assert not any(p.name.endswith(".tmp") for p in tmp_path.rglob("*"))


def test_persistir_falha_ao_gravar_original_nao_deixa_arquivos(tmp_path, monkeypatch):
    original, miniatura = caminhos_teste(tmp_path)

    def falha(caminho, conteudo, criados):
        raise OSError("falha simulada")

    monkeypatch.setattr(galeria, "_gravar_exclusivo", falha)
    with pytest.raises(OSError):
        galeria.persistir_arquivos(original, miniatura, b"o", b"m")
    assert arquivos_no_disco(tmp_path) == []


def test_persistir_falha_ao_gravar_miniatura_limpa_original(tmp_path, monkeypatch):
    original, miniatura = caminhos_teste(tmp_path)
    real = galeria._gravar_exclusivo
    contador = {"chamadas": 0}

    def gravar(caminho, conteudo, criados):
        contador["chamadas"] += 1
        if contador["chamadas"] == 2:
            raise OSError("falha simulada")
        return real(caminho, conteudo, criados)

    monkeypatch.setattr(galeria, "_gravar_exclusivo", gravar)
    with pytest.raises(OSError):
        galeria.persistir_arquivos(original, miniatura, b"o", b"m")
    assert arquivos_no_disco(tmp_path) == []

# verifica se os arquivos ja publicados sao removidos quando a segunda publicaçao falha
def test_persistir_falha_na_publicacao_faz_rollback(tmp_path, monkeypatch):
    original, miniatura = caminhos_teste(tmp_path)
    real = os.replace
    contador = {"chamadas": 0}

    def replace_falho(origem, destino):
        contador["chamadas"] += 1
        if contador["chamadas"] == 2:
            raise OSError("falha simulada")
        return real(origem, destino)

    monkeypatch.setattr(galeria.os, "replace", replace_falho)
    with pytest.raises(OSError):
        galeria.persistir_arquivos(original, miniatura, b"o", b"m")
    assert arquivos_no_disco(tmp_path) == []


def test_persistir_nunca_sobrescreve_temporario_existente(tmp_path, monkeypatch):
    original, miniatura = caminhos_teste(tmp_path)

    class Fixo:
        hex = "fixo"

    monkeypatch.setattr(galeria.uuid, "uuid4", lambda: Fixo())
    original.parent.mkdir(parents=True)
    temporario = original.with_name(f".{original.name}.fixo.tmp")
    temporario.write_bytes(b"de-outra-operacao")

    with pytest.raises(FileExistsError):
        galeria.persistir_arquivos(original, miniatura, b"o", b"m")

    assert temporario.read_bytes() == b"de-outra-operacao"
    assert arquivos_no_disco(tmp_path) == [temporario]


# nomes duplicados

def test_nomes_duplicados_geram_nomes_de_exibicao_unicos(tmp_path):
    h = cadastrar_e_logar("ana")
    nomes = [enviar(h).json()["nome"] for _ in range(3)]
    assert nomes == ["foto.png", "foto (2).png", "foto (3).png"]
    assert len(galeria.imagens) == 3
    originais = [p for p in (tmp_path / "originals" / "ana").iterdir()]
    assert len(originais) == 3


def test_nome_duplicado_e_por_usuario():
    h_ana = cadastrar_e_logar("ana")
    h_bruno = cadastrar_e_logar("bruno")
    assert enviar(h_ana).json()["nome"] == "foto.png"
    assert enviar(h_bruno).json()["nome"] == "foto.png"
    assert enviar(h_ana).json()["nome"] == "foto (2).png"


def test_historico_registra_nomes_unicos():
    h = cadastrar_e_logar("ana")
    enviar(h)
    enviar(h)
    nomes = [x["nome"] for x in gal.get("/history", headers=h).json()]
    assert nomes == ["foto.png", "foto (2).png"]


def test_nome_com_parenteses_e_extensao_preservada():
    h = cadastrar_e_logar("ana")
    assert enviar(h, "foto (2).png").json()["nome"] == "foto (2).png"
    assert enviar(h, "foto (2).png").json()["nome"] == "foto (3).png"
    assert enviar(h, "relatorio.v2.final.png").json()["nome"] == "relatorio.v2.final.png"
    assert enviar(h, "relatorio.v2.final.png").json()["nome"] == "relatorio.v2.final (2).png"


def test_download_usa_nome_de_exibicao_unico():
    h = cadastrar_e_logar("ana")
    enviar(h)
    segundo = enviar(h).json()
    down = gal.get(f"/images/{segundo['id']}/download", headers=h)
    assert "foto (2).png" in unquote(down.headers["content-disposition"])


# verifica se os arquivos sao removidos quando o registro dos metadados falha

def test_falha_no_registro_remove_arquivos(tmp_path, monkeypatch):
    h = cadastrar_e_logar("ana")

    def falha(*args, **kwargs):
        raise RuntimeError("falha simulada")

    monkeypatch.setattr(galeria, "registrar_upload", falha)
    assert enviar(h).status_code == 500
    assert galeria.imagens == {}
    assert galeria.historico == []
    assert arquivos_no_disco(tmp_path) == []


def test_falha_no_historico_desfaz_metadados_e_arquivos(tmp_path, monkeypatch):
    h = cadastrar_e_logar("ana")

    class HistoricoQuebrado(list):
        def append(self, item):
            raise RuntimeError("falha simulada")

    monkeypatch.setattr(galeria, "historico", HistoricoQuebrado())
    assert enviar(h).status_code == 500
    assert galeria.imagens == {}
    assert list(galeria.historico) == []
    assert arquivos_no_disco(tmp_path) == []


def test_falha_ao_persistir_nao_registra_metadados(tmp_path, monkeypatch):
    h = cadastrar_e_logar("ana")

    def falha(*args, **kwargs):
        raise OSError("disco cheio simulado")

    monkeypatch.setattr(galeria, "persistir_arquivos", falha)
    assert enviar(h).status_code == 500
    assert galeria.imagens == {} and galeria.historico == []


# verifica a integridade dos arquivos e a geraçao de nomes unicos em uploads simultaneos

def test_uploads_simultaneos_mesmo_arquivo_sem_sobrescrita(tmp_path):
    h = cadastrar_e_logar("ana")
    total = 30
    dados = png()

    def tentar(_):
        return enviar(h, "foto.png", dados)

    with ThreadPoolExecutor(max_workers=10) as pool:
        respostas = list(pool.map(tentar, range(total)))

    assert [r.status_code for r in respostas] == [201] * total

    ids = {r.json()["id"] for r in respostas}
    nomes = {r.json()["nome"] for r in respostas}
    esperados = {"foto.png"} | {f"foto ({n}).png" for n in range(2, total + 1)}
    assert len(ids) == total
    assert nomes == esperados

    assert len(galeria.imagens) == total
    assert len(galeria.historico) == total
    assert {h_["nome"] for h_ in galeria.historico} == esperados

    originais = list((tmp_path / "originals" / "ana").iterdir())
    miniaturas = list((tmp_path / "thumbnails" / "ana").iterdir())
    assert len(originais) == total
    assert len(miniaturas) == total
    assert not any(p.name.endswith(".tmp") for p in tmp_path.rglob("*"))

    for img in galeria.imagens.values():
        assert os.path.isfile(img["caminho_original"])
        assert os.path.isfile(img["caminho_miniatura"])