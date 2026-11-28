"""Persistência SQLite da Galeria.

Toda escrita vai para o banco na hora; a leitura acontece uma vez, na
inicialização (carregar). Os dicionários do main.py funcionam como cache.
"""

import sqlite3
import threading
from pathlib import Path

_lock = threading.RLock()
_conn: sqlite3.Connection | None = None

ESQUEMA = """
CREATE TABLE IF NOT EXISTS usuarios (
    username   TEXT PRIMARY KEY,
    senha_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tokens (
    token   TEXT PRIMARY KEY,
    usuario TEXT NOT NULL,
    expira  REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS imagens (
    id                TEXT PRIMARY KEY,
    autor             TEXT NOT NULL,
    data              TEXT NOT NULL,
    nome              TEXT NOT NULL,
    tipo              TEXT NOT NULL,
    tamanho           INTEGER NOT NULL,
    caminho_original  TEXT NOT NULL,
    caminho_miniatura TEXT NOT NULL,
    url_miniatura     TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS historico (
    seq      INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario  TEXT NOT NULL,
    image_id TEXT NOT NULL,
    nome     TEXT NOT NULL,
    data     TEXT NOT NULL
);
"""

COLUNAS_IMAGEM = (
    "id", "autor", "data", "nome", "tipo", "tamanho",
    "caminho_original", "caminho_miniatura", "url_miniatura",
)


def iniciar(caminho) -> None:
    global _conn
    fechar()
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        _conn = sqlite3.connect(caminho, check_same_thread=False, timeout=10)
        _conn.row_factory = sqlite3.Row
        _conn.executescript(ESQUEMA)
        _conn.commit()


def fechar() -> None:
    global _conn
    with _lock:
        if _conn is not None:
            _conn.close()
            _conn = None


def _con() -> sqlite3.Connection:
    if _conn is None:
        raise RuntimeError("Banco não iniciado (db.iniciar)")
    return _conn


def salvar_usuario(username: str, senha_hash: str) -> bool:
    """False se o usuário já existe (restrição PRIMARY KEY, atômica)."""
    with _lock:
        try:
            with _con():
                _con().execute(
                    "INSERT INTO usuarios VALUES (?, ?)", (username, senha_hash)
                )
            return True
        except sqlite3.IntegrityError:
            return False


def salvar_token(token: str, usuario: str, expira: float) -> None:
    with _lock, _con():
        _con().execute("INSERT INTO tokens VALUES (?, ?, ?)", (token, usuario, expira))


def remover_token(token: str) -> None:
    with _lock, _con():
        _con().execute("DELETE FROM tokens WHERE token = ?", (token,))


def salvar_imagem(img: dict, envio: dict) -> None:
    """Grava metadados e histórico na mesma transação."""
    with _lock, _con():
        c = _con()
        c.execute(
            f"INSERT INTO imagens VALUES ({','.join('?' * len(COLUNAS_IMAGEM))})",
            [img[k] for k in COLUNAS_IMAGEM],
        )
        c.execute(
            "INSERT INTO historico (usuario, image_id, nome, data) VALUES (?, ?, ?, ?)",
            (envio["usuario"], envio["image_id"], envio["nome"], envio["data"]),
        )


def carregar(agora: float):
    """Devolve (usuarios, tokens, imagens, historico) para repovoar a memória."""
    with _lock, _con():
        c = _con()
        c.execute("DELETE FROM tokens WHERE expira < ?", (agora,))
        usuarios = {r["username"]: r["senha_hash"] for r in c.execute("SELECT * FROM usuarios")}
        tokens = {r["token"]: (r["usuario"], r["expira"]) for r in c.execute("SELECT * FROM tokens")}
        imagens = {r["id"]: dict(r) for r in c.execute("SELECT * FROM imagens")}
        historico = [
            {k: r[k] for k in ("usuario", "image_id", "nome", "data")}
            for r in c.execute("SELECT * FROM historico ORDER BY seq")
        ]
    return usuarios, tokens, imagens, historico