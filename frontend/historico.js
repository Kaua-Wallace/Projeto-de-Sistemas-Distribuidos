// Histórico pessoal de uploads.

import { baixarMiniatura, listarHistorico } from "./api.js";
import { formatarData } from "./galeria.js";

let estado = null;

export function iniciarHistorico(container) {
  pararHistorico();
  container.innerHTML = `
    <section class="historico" aria-labelledby="titulo-historico">
      <div class="historico-cabecalho">
        <h2 id="titulo-historico">Meus envios</h2>
        <button class="botao historico-atualizar" type="button">Atualizar</button>
      </div>
      <p class="historico-estado" role="status">Carregando histórico…</p>
      <ul class="historico-lista"></ul>
    </section>`;
  estado = {
    container,
    lista: container.querySelector(".historico-lista"),
    textoEstado: container.querySelector(".historico-estado"),
    urls: new Set(),
    carregando: false,
  };
  container.querySelector(".historico-atualizar").addEventListener("click", atualizarHistorico);
  atualizarHistorico();
}

export function pararHistorico() {
  if (!estado) return;
  for (const url of estado.urls) URL.revokeObjectURL(url);
  estado.urls.clear();
  estado = null;
}

export async function atualizarHistorico() {
  const atual = estado;
  if (!atual || atual.carregando) return;
  atual.carregando = true;
  atual.textoEstado.hidden = false;
  atual.textoEstado.textContent = "Carregando histórico…";
  try {
    const envios = await listarHistorico();
    if (atual !== estado) return;
    limparMiniaturas(atual);
    atual.lista.replaceChildren();
    if (!envios.length) {
      atual.textoEstado.textContent = "Você ainda não enviou imagens.";
      return;
    }
    atual.textoEstado.hidden = true;
    for (const envio of envios) {
      const item = document.createElement("li");
      item.className = "historico-item";
      const miniatura = document.createElement("div");
      miniatura.className = "historico-miniatura carregando";
      const imagem = document.createElement("img");
      imagem.alt = "";
      imagem.hidden = true;
      miniatura.append(imagem);

      const detalhes = document.createElement("div");
      detalhes.className = "historico-detalhes";
      const nome = document.createElement("strong");
      nome.className = "historico-nome";
      nome.textContent = envio.nome || "Imagem sem nome";
      const data = document.createElement("time");
      data.dateTime = envio.data;
      data.textContent = formatarData(envio.data);
      detalhes.append(nome, data);
      item.append(miniatura, detalhes);
      atual.lista.append(item);
      carregarMiniatura(atual, envio, miniatura, imagem);
    }
  } catch (erro) {
    if (atual !== estado || erro.status === 401) return;
    atual.textoEstado.textContent = erro.status === 0
      ? "Sem conexão com o servidor. Tente atualizar novamente."
      : `Não foi possível carregar o histórico: ${erro.mensagem}`;
  } finally {
    if (atual === estado) atual.carregando = false;
  }
}

function limparMiniaturas(atual) {
  for (const url of atual.urls) URL.revokeObjectURL(url);
  atual.urls.clear();
}

async function carregarMiniatura(atual, envio, moldura, imagem) {
  try {
    const blob = await baixarMiniatura(envio.url_miniatura);
    if (atual !== estado || !moldura.isConnected) return;
    const url = URL.createObjectURL(blob);
    atual.urls.add(url);
    imagem.src = url;
    imagem.hidden = false;
    moldura.classList.remove("carregando");
  } catch (erro) {
    if (atual !== estado) return;
    moldura.classList.remove("carregando");
    moldura.classList.add("falhou");
    moldura.setAttribute("aria-label", erro.status === 404
      ? "Miniatura não encontrada"
      : "Miniatura indisponível");
  }
}
