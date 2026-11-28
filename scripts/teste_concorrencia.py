import argparse
import asyncio
import io
import sys
import time
import uuid
from pathlib import Path

import httpx
from PIL import Image


SENHA = "SenhaTeste123"


def gerar_imagem():
    """
    Gera uma imagem PNG para utilizar nos uploads
    """

    arquivo = io.BytesIO()

    Image.new(
        "RGB",
        (800, 600),
        "blue"
    ).save(arquivo, "PNG")

    return arquivo.getvalue()


async def preparar_usuario(cliente, base, numero):
    """
    Cadastra um usuário e realiza seu login

    Cada usuário possui um username diferente
    """

    username = f"carga_{base}_{numero:03d}"

    cadastro = await cliente.post(
        "/auth/register",
        json={
            "username": username,
            "password": SENHA
        }
    )

    if cadastro.status_code != 201:

        return {
            "username": username,
            "token": None,
            "erro": f"Cadastro HTTP {cadastro.status_code}: {cadastro.text[:200]}"
        }

    login = await cliente.post(
        "/auth/login",
        json={
            "username": username,
            "password": SENHA
        }
    )

    if login.status_code != 200:

        return {
            "username": username,
            "token": None,
            "erro": f"Login HTTP {login.status_code}: {login.text[:200]}"
        }

    return {
        "username": username,
        "token": login.json()["token"],
        "erro": None
    }


async def realizar_upload(cliente, usuario, imagem):
    """
    Realiza um upload utilizando o token do usuário

    Cada chamada representa um upload independente
    """

    username = usuario["username"]

    headers = {
        "Authorization": f"Bearer {usuario['token']}"
    }

    arquivos = {
        "file": (
            f"{username}.png",
            imagem,
            "image/png"
        )
    }

    try:

        resposta = await cliente.post(
            "/images",
            headers=headers,
            files=arquivos
        )

        sucesso = resposta.status_code == 201

        return {
            "usuario": username,
            "sucesso": sucesso,
            "status": resposta.status_code,
            "erro": None if sucesso else resposta.text[:300]
        }

    except httpx.RequestError as erro:

        return {
            "usuario": username,
            "sucesso": False,
            "status": None,
            "erro": str(erro)
        }


async def executar_teste(total, url, timeout):

    inicio = time.perf_counter()

    imagem = gerar_imagem()

    base = uuid.uuid4().hex[:8]

    limites = httpx.Limits(
        max_connections=total,
        max_keepalive_connections=total
    )

    async with httpx.AsyncClient(
        base_url=url,
        timeout=timeout,
        limits=limites
    ) as cliente:

        print(f"\nCriando {total} usuários...")

        # Cadastro e login dos usuários.
        usuarios = await asyncio.gather(
            *[
                preparar_usuario(cliente, base, i)
                for i in range(total)
            ]
        )

        preparados = [
            usuario
            for usuario in usuarios
            if usuario["token"] is not None
        ]

        falhas_preparacao = [
            usuario
            for usuario in usuarios
            if usuario["token"] is None
        ]

        print(f"Usuários preparados: {len(preparados)}")

        print("\nDisparando uploads simultâneos...")

        # Dispara todos os uploads sem aguardar um terminar para iniciar outro.
        resultados = await asyncio.gather(
            *[
                realizar_upload(cliente, usuario, imagem)
                for usuario in preparados
            ]
        )

    duracao = time.perf_counter() - inicio

    sucessos = sum(
        1 for r in resultados
        if r["sucesso"]
    )

    falhas_upload = [
        r for r in resultados
        if not r["sucesso"]
    ]

    falhas = len(falhas_upload) + len(falhas_preparacao)

    print("\n========== RESULTADO DO TESTE ==========")

    print(f"Uploads solicitados: {total}")

    print(f"Uploads executados: {len(resultados)}")

    print(f"Sucessos: {sucessos}")

    print(f"Falhas: {falhas}")

    print(f"Tempo total: {duracao:.2f} segundos")

    if duracao > 0:

        print(
            f"Vazão aproximada: {sucessos / duracao:.2f} uploads/s"
        )

    if falhas > 0:

        print("\nDetalhamento das falhas:")

        for usuario in falhas_preparacao:

            print(
                f"[PREPARAÇÃO] {usuario['username']}: "
                f"{usuario['erro']}"
            )

        for resultado in falhas_upload:

            print(
                f"[UPLOAD] {resultado['usuario']}: "
                f"HTTP {resultado['status']} - {resultado['erro']}"
            )

    print("\n========================================")

    return falhas == 0


def verificar(descricao, condicao, detalhe=""):
    marca = "OK   " if condicao else "FALHA"
    sufixo = f" ({detalhe})" if detalhe and not condicao else ""
    print(f"[{marca}] {descricao}{sufixo}")
    return condicao


def contar_arquivos_no_disco(storage, username):
    base = Path(storage)
    pasta_o = base / "originals" / username
    pasta_t = base / "thumbnails" / username

    originais = [p for p in pasta_o.glob("*") if p.is_file()] if pasta_o.exists() else []
    miniaturas = [p for p in pasta_t.glob("*") if p.is_file()] if pasta_t.exists() else []
    return originais, miniaturas

#executa uploads simultaneos do mesmo arquivo por um unico usuario e verifica a integridade dos resultados
async def executar_mesmo_usuario(total, url, timeout, storage):

    imagem = gerar_imagem()

    base = uuid.uuid4().hex[:8]

    limites = httpx.Limits(
        max_connections=total,
        max_keepalive_connections=total
    )

    print(f"\nEnviando {total} uploads simultâneos do mesmo arquivo pelo mesmo usuário...")

    async with httpx.AsyncClient(
        base_url=url,
        timeout=timeout,
        limits=limites
    ) as cliente:

        usuario = await preparar_usuario(cliente, base, 0)

        if usuario["token"] is None:
            print(f"Não foi possível preparar o usuário: {usuario['erro']}")
            return False

        headers = {"Authorization": f"Bearer {usuario['token']}"}

        async def enviar():
            try:
                resposta = await cliente.post(
                    "/images",
                    headers=headers,
                    files={"file": ("foto.png", imagem, "image/png")}
                )
                corpo = resposta.json() if resposta.status_code == 201 else None
                return resposta.status_code, corpo
            except httpx.RequestError:
                return None, None

        resultados = await asyncio.gather(*[enviar() for _ in range(total)])

        lista = (await cliente.get("/images", headers=headers)).json()
        historico = (await cliente.get("/history", headers=headers)).json()

    codigos = [codigo for codigo, _ in resultados]
    corpos = [corpo for _, corpo in resultados if corpo]
    ids_resposta = {c["id"] for c in corpos}
    nomes_resposta = {c["nome"] for c in corpos}
    esperados = {"foto.png"} | {f"foto ({n}).png" for n in range(2, total + 1)}
    ids_listados = {i["id"] for i in lista if i["autor"] == usuario["username"]}
    nomes_historico = [h["nome"] for h in historico]

    print("\n========== MESMO USUÁRIO, MESMO ARQUIVO ==========")

    ok = True
    ok &= verificar(f"{total} uploads com HTTP 201", codigos.count(201) == total, str(sorted(set(codigos), key=str)))
    ok &= verificar(f"{total} IDs diferentes", len(ids_resposta) == total)
    ok &= verificar(f"{total} registros na listagem", len(ids_listados) == total, str(len(ids_listados)))
    ok &= verificar("nomes de exibição únicos e esperados", nomes_resposta == esperados)
    ok &= verificar("histórico com um item por upload", len(nomes_historico) == total and set(nomes_historico) == esperados)

    if storage:
        originais, miniaturas = contar_arquivos_no_disco(storage, usuario["username"])
        base_o = {p.stem for p in originais}
        base_t = {p.stem for p in miniaturas}
        temporarios = [
            p for p in Path(storage).rglob("*")
            if p.is_file() and p.name.endswith(".tmp")
        ]
        ok &= verificar(f"{total} originais no disco", len(originais) == total, str(len(originais)))
        ok &= verificar(f"{total} miniaturas no disco", len(miniaturas) == total, str(len(miniaturas)))
        ok &= verificar("cada original possui sua miniatura", base_o == base_t)
        ok &= verificar("arquivos no disco correspondem aos registros", base_o == ids_listados)
        ok &= verificar("nenhum arquivo temporário restante", not temporarios)
    else:
        print("(use --storage CAMINHO para conferir também os arquivos no disco)")

    print("\n==================================================")

    return bool(ok)

# verifica se somente um cadastro e concluido quando varias requisiçoes usam o mesmo username
async def executar_cadastros(total, url, timeout):

    username = f"corrida_{uuid.uuid4().hex[:10]}"

    limites = httpx.Limits(
        max_connections=total,
        max_keepalive_connections=total
    )

    print(f"\nEnviando {total} cadastros simultâneos do username '{username}'...")

    async with httpx.AsyncClient(
        base_url=url,
        timeout=timeout,
        limits=limites
    ) as cliente:

        async def cadastrar():
            try:
                resposta = await cliente.post(
                    "/auth/register",
                    json={"username": username, "password": SENHA}
                )
                return resposta.status_code
            except httpx.RequestError:
                return None

        codigos = await asyncio.gather(*[cadastrar() for _ in range(total)])

        login = await cliente.post(
            "/auth/login",
            json={"username": username, "password": SENHA}
        )

    print("\n========== CADASTROS SIMULTÂNEOS ==========")

    ok = True
    ok &= verificar("exatamente um cadastro com HTTP 201", codigos.count(201) == 1, str(codigos.count(201)))
    ok &= verificar("os demais rejeitados com HTTP 409", codigos.count(409) == total - 1, str(codigos.count(409)))
    ok &= verificar("nenhum erro inesperado", all(c in (201, 409) for c in codigos), str(sorted(set(codigos), key=str)))
    ok &= verificar("login do usuário criado funciona", login.status_code == 200)

    print("\n===========================================")

    return bool(ok)


def main():

    parser = argparse.ArgumentParser(
        description="Teste de concorrência da API de Galeria"
    )

    parser.add_argument(
        "--modo",
        choices=["carga", "mesmo-usuario", "cadastro", "todos"],
        default="carga",
        help="carga: N usuários com um upload cada; mesmo-usuario: N uploads do "
             "mesmo arquivo pelo mesmo usuário; cadastro: N cadastros do mesmo "
             "username; todos: executa os três"
    )

    parser.add_argument(
        "--total",
        type=int,
        default=20,
        help="Quantidade de usuários e uploads simultâneos"
    )

    parser.add_argument(
        "--url",
        default="http://localhost:8001",
        help="URL do serviço de Galeria"
    )

    parser.add_argument(
        "--timeout",
        type=float,
        default=60,
        help="Timeout das requisições em segundos"
    )

    parser.add_argument(
        "--storage",
        default=None,
        help="Pasta storage da Galeria, para conferir os arquivos no disco"
    )

    args = parser.parse_args()

    if args.total < 1:
        parser.error("--total deve ser maior que zero")

    if args.timeout <= 0:
        parser.error("--timeout deve ser maior que zero")

    async def executar():
        resultados = []

        if args.modo in ("carga", "todos"):
            resultados.append(
                await executar_teste(args.total, args.url, args.timeout)
            )

        if args.modo in ("mesmo-usuario", "todos"):
            total = 30 if args.modo == "todos" else args.total
            resultados.append(
                await executar_mesmo_usuario(total, args.url, args.timeout, args.storage)
            )

        if args.modo in ("cadastro", "todos"):
            resultados.append(
                await executar_cadastros(args.total, args.url, args.timeout)
            )

        return all(resultados)

    sucesso = asyncio.run(executar())
    sys.exit(0 if sucesso else 1)


if __name__ == "__main__":
    main()