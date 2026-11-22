import argparse
import asyncio
import io
import time
import uuid

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


def main():

    parser = argparse.ArgumentParser(
        description="Teste de concorrência da API de Galeria"
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

    args = parser.parse_args()

    if args.total < 1:
        parser.error("--total deve ser maior que zero")

    if args.timeout <= 0:
        parser.error("--timeout deve ser maior que zero")

    asyncio.run(
        executar_teste(
            args.total,
            args.url,
            args.timeout
        )
    )


if __name__ == "__main__":
    main()