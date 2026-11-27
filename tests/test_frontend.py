# Testes da interface web estática servida pela Galeria em /app

import os
import tempfile

# Igual ao test_galeria.py: o storage precisa ser temporário antes de importar a Galeria
os.environ.setdefault("STORAGE_ROOT", tempfile.mkdtemp())

from fastapi.testclient import TestClient

from gallery_service import main as galeria

cliente = TestClient(galeria.app)


def test_app_serve_index_html():
    r = cliente.get("/app/")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert 'id="tela-auth"' in r.text


def test_app_sem_barra_redireciona():
    r = cliente.get("/app", follow_redirects=False)
    assert r.status_code in (307, 308)
    assert r.headers["location"].endswith("/app/")


def test_app_serve_modulos_js():
    for arquivo in ("api.js", "app.js"):
        r = cliente.get(f"/app/{arquivo}")
        assert r.status_code == 200, arquivo
        assert "javascript" in r.headers["content-type"], arquivo


def test_api_continua_respondendo_fora_de_app():
    assert cliente.get("/health").json()["service"] == "gallery"
    assert cliente.get("/images").status_code == 401
