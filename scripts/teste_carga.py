"""Teste de carga da Galeria: N usuários x M ciclos (upload, listagem, prévia, download).

Uso:  python scripts/teste_carga.py --usuarios 20 --ciclos 5 --concorrencia 20
Gera um relatório em Markdown (padrão: docs/relatorio_carga.md).
"""

import argparse
import asyncio
import io
import math
import platform
import time
import uuid
from datetime import datetime

import httpx
from PIL import Image

SENHA = "SenhaTeste123"
OPERACOES = ("upload", "listagem", "previa", "download")

def gerar_imagem() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (800, 600), "blue").save(buf, "PNG")
    return buf.getvalue()

def percentil(valores: list[float], p: float) -> float:
    if not valores:
        return 0.0
    ordenados = sorted(valores)
    return ordenados[max(0, math.ceil(p / 100 * len(ordenados)) - 1)]


async def medir(cliente, sem, lat, erros, op, metodo, url, **kw):
    async with sem:
        ini = time.perf_counter()
        try:
            r = await cliente.request(metodo, url, **kw)
            ok = r.status_code in (200, 201)
            status = r.status_code
        except httpx.RequestError as e:
            r, ok, status = None, False, type(e).__name__
        lat[op].append((time.perf_counter() - ini) * 1000)
    if not ok:
        erros.append((op, status))
    return r if ok else None


async def usuario_virtual(cliente, sem, base, n, ciclos, imagem, lat, erros):
    nome = f"carga_{base}_{n:03d}"
    cred = {"username": nome, "password": SENHA}
    if (await cliente.post("/auth/register", json=cred)).status_code != 201:
        erros.append(("cadastro", nome))
        return
    r = await cliente.post("/auth/login", json=cred)
    if r.status_code != 200:
        erros.append(("login", nome))
        return
    h = {"Authorization": f"Bearer {r.json()['token']}"}
    for c in range(ciclos):
        up = await medir(cliente, sem, lat, erros, "upload", "POST", "/images", headers=h,
                         files={"file": (f"{nome}_{c}.png", imagem, "image/png")})
        await medir(cliente, sem, lat, erros, "listagem", "GET", "/images?limit=50", headers=h)
        if up:
            iid = up.json()["id"]
            await medir(cliente, sem, lat, erros, "previa", "GET", f"/images/{iid}/thumbnail", headers=h)
            await medir(cliente, sem, lat, erros, "download", "GET", f"/images/{iid}/download", headers=h)

async def executar(args):
    lat = {op: [] for op in OPERACOES}
    erros = []
    sem = asyncio.Semaphore(args.concorrencia)
    base = uuid.uuid4().hex[:6]
    imagem = gerar_imagem()
    limites = httpx.Limits(max_connections=args.concorrencia * 2)
    async with httpx.AsyncClient(base_url=args.url, timeout=args.timeout, limits=limites) as cli:
        ini = time.perf_counter()
        await asyncio.gather(*[
            usuario_virtual(cli, sem, base, n, args.ciclos, imagem, lat, erros)
            for n in range(args.usuarios)
        ])
        total = time.perf_counter() - ini
    return lat, erros, total

def relatorio(args, lat, erros, total) -> str:
    n_req = sum(len(v) for v in lat.values())
    linhas = [
        "# Relatório de teste de carga", "",
        f"- Data: {datetime.now():%d/%m/%Y %H:%M}",
        f"- Máquina: {platform.system()} {platform.release()}, Python {platform.python_version()}",
        f"- Parâmetros: {args.usuarios} usuários x {args.ciclos} ciclos, concorrência {args.concorrencia}",
        f"- Requisições medidas: {n_req} em {total:.2f} s ({n_req / total:.1f} req/s)",
        f"- Erros: {len(erros)}", "",
        "| Operação | Qtd | Média (ms) | p50 (ms) | p95 (ms) | Máx (ms) |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for op, v in lat.items():
        if v:
            linhas.append(f"| {op} | {len(v)} | {sum(v) / len(v):.1f} | {percentil(v, 50):.1f} "
                          f"| {percentil(v, 95):.1f} | {max(v):.1f} |")
    if erros:
        linhas += ["", "Erros (operação, status):", ""]
        linhas += [f"- {e}" for e in sorted(set(map(str, erros)))[:20]]
    return "\n".join(linhas) + "\n"


def main():
    p = argparse.ArgumentParser(description="Teste de carga da Galeria")
    p.add_argument("--url", default="http://localhost:8001")
    p.add_argument("--usuarios", type=int, default=20)
    p.add_argument("--ciclos", type=int, default=5)
    p.add_argument("--concorrencia", type=int, default=20)
    p.add_argument("--timeout", type=float, default=60)
    p.add_argument("--saida", default="docs/relatorio_carga.md")
    args = p.parse_args()
    if min(args.usuarios, args.ciclos, args.concorrencia) < 1:
        p.error("usuarios, ciclos e concorrencia devem ser >= 1")
    lat, erros, total = asyncio.run(executar(args))
    texto = relatorio(args, lat, erros, total)
    print(texto)
    with open(args.saida, "w", encoding="utf-8") as f:
        f.write(texto)
    print(f"Relatório salvo em {args.saida}")
    raise SystemExit(1 if erros else 0)

if __name__ == "__main__":
    main()