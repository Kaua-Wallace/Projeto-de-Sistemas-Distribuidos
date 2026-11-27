// Galeria: grade com miniatura, autor e data de cada imagem enviada.

import { baixarMiniatura, listarImagens } from "./api.js";

// Atualização automática: outra pessoa envia e a imagem aparece sem F5.
const INTERVALO_ATUALIZACAO_MS = 5000;

const formatoData = new Intl.DateTimeFormat("pt-BR", {
  dateStyle: "short",
  timeStyle: "short",
});

// A API devolve datas ISO sem fuso ("2026-11-17T01:50:00"), no horário do servidor.
export function formatarData(iso) {
  const data = new Date(iso);
  return Number.isNaN(data.getTime()) ? iso : formatoData.format(data);
}

// Estado da galeria montada (null quando desmontada)
let estado = null;

export function iniciarGaleria(container) {
  pararGaleria();
  container.innerHTML = `
    <section class="galeria" aria-labelledby="titulo-galeria">
      <div class="galeria-cabecalho">
        <h2 id="titulo-galeria">Galeria</h2>
        <span class="contador"></span>
      </div>
      <p class="faixa-conexao" role="status" hidden></p>
      <p class="galeria-estado">Carregando imagens…</p>
      <ul class="grade"></ul>
    </section>
    <dialog class="previa" aria-labelledby="previa-titulo">
      <div class="previa-corpo">
        <button type="button" class="previa-fechar" aria-label="Fechar prévia">×</button>
        <div class="previa-imagem"><img alt=""></div>
        <h3 id="previa-titulo"></h3>
        <p class="previa-meta"></p>
        <div class="previa-acoes"></div>
      </div>
    </dialog>`;

  estado = {
    grade: container.querySelector(".grade"),
    contador: container.querySelector(".contador"),
    textoEstado: container.querySelector(".galeria-estado"),
    faixa: container.querySelector(".faixa-conexao"),
    cards: new Map(), // id -> <li>
    imagens: new Map(), // id -> metadados vindos da API
    miniaturas: new Map(), // id -> object URL da miniatura (null enquanto carrega ou se falhou)
    carregouUmaVez: false,
    buscando: false,
    pendente: false,
    timer: null,
    dialogo: container.querySelector(".previa"),
    idNaPrevia: null,
  };
  ligarPrevia(estado);
  estado.grade.addEventListener("click", (evento) => {
    const card = evento.target.closest(".card");
    if (card) abrirPrevia(card.dataset.id);
  });
  document.addEventListener("visibilitychange", aoMudarVisibilidade);
  atualizarGaleria();
}

export function pararGaleria() {
  if (!estado) return;
  clearTimeout(estado.timer);
  document.removeEventListener("visibilitychange", aoMudarVisibilidade);
  if (estado.dialogo.open) estado.dialogo.close();
  revogarTodas(estado);
  estado = null;
}

function revogarTodas(atual) {
  for (const url of atual.miniaturas.values()) {
    if (url) URL.revokeObjectURL(url);
  }
  atual.miniaturas.clear();
}

function revogarMiniatura(atual, id) {
  const url = atual.miniaturas.get(id);
  if (url) URL.revokeObjectURL(url);
  atual.miniaturas.delete(id);
}

// Polling: agenda a próxima busca, mas não gasta rede com a aba escondida.
function agendarProxima(atual) {
  clearTimeout(atual.timer);
  if (document.hidden) return;
  atual.timer = setTimeout(atualizarGaleria, INTERVALO_ATUALIZACAO_MS);
}

function aoMudarVisibilidade() {
  if (!estado) return;
  if (document.hidden) clearTimeout(estado.timer);
  else atualizarGaleria(); // voltou para a aba: atualiza na hora
}

// Busca a lista na API e sincroniza a grade. Chamadas simultâneas são
// agrupadas: se já há uma busca em andamento, outra roda logo depois dela.
export async function atualizarGaleria() {
  const atual = estado;
  if (!atual) return;
  if (atual.buscando) {
    atual.pendente = true;
    return;
  }
  atual.buscando = true;
  try {
    const lista = await listarImagens();
    if (atual !== estado) return; // a galeria foi desmontada enquanto esperava
    atual.faixa.hidden = true;
    atual.carregouUmaVez = true;
    renderizar(atual, lista);
  } catch (erro) {
    if (atual !== estado || erro.status === 401) return; // 401: o app.js volta ao login
    atual.faixa.textContent =
      erro.status === 0
        ? "Sem conexão com o servidor. Tentando de novo…"
        : `Não foi possível atualizar a galeria (${erro.mensagem}). Tentando de novo…`;
    atual.faixa.hidden = false;
    if (!atual.carregouUmaVez) atual.textoEstado.textContent = "Não foi possível carregar as imagens.";
  } finally {
    atual.buscando = false;
    if (atual === estado) {
      if (atual.pendente) {
        atual.pendente = false;
        atualizarGaleria();
      } else {
        agendarProxima(atual);
      }
    }
  }
}

function renderizar(atual, lista) {
  // Mais recentes primeiro (datas ISO comparam como texto)
  const ordenadas = [...lista].sort((a, b) => String(b.data).localeCompare(String(a.data)));
  const ids = new Set(ordenadas.map((img) => img.id));

  // Remove o que não existe mais
  for (const [id, card] of atual.cards) {
    if (!ids.has(id)) {
      card.remove();
      atual.cards.delete(id);
      atual.imagens.delete(id);
      revogarMiniatura(atual, id);
      if (atual.idNaPrevia === id) atual.dialogo.close(); // removida enquanto aberta
    }
  }

  // Adiciona as novas e mantém a ordem sem recriar os cards existentes
  ordenadas.forEach((img, indice) => {
    atual.imagens.set(img.id, img);
    let card = atual.cards.get(img.id);
    if (!card) {
      card = criarCard(img);
      atual.cards.set(img.id, card);
      carregarMiniatura(atual, img, card);
    } else if (card.dataset.miniatura === "sem-conexao") {
      carregarMiniatura(atual, img, card); // tenta de novo quando a rede volta
    }
    if (atual.grade.children[indice] !== card) {
      atual.grade.insertBefore(card, atual.grade.children[indice] ?? null);
    }
  });

  const total = ordenadas.length;
  atual.contador.textContent = total === 1 ? "1 imagem" : `${total} imagens`;
  atual.textoEstado.textContent = "Nenhuma imagem ainda. Envie a primeira!";
  atual.textoEstado.hidden = total > 0;
}

// Cards montados com textContent: nomes de usuário e de arquivo nunca viram HTML
function criarCard(img) {
  const card = document.createElement("li");
  card.className = "card";
  card.dataset.id = img.id;

  const botao = document.createElement("button");
  botao.type = "button";
  botao.className = "card-botao";
  botao.setAttribute(
    "aria-label",
    `Abrir prévia de ${img.nome ?? "imagem"} enviada por ${img.autor}`,
  );

  const moldura = document.createElement("div");
  moldura.className = "card-miniatura carregando";
  const imagem = document.createElement("img");
  imagem.alt = "";
  imagem.hidden = true;
  moldura.append(imagem);

  const info = document.createElement("div");
  info.className = "card-info";
  if (img.nome) {
    const nome = document.createElement("span");
    nome.className = "card-nome";
    nome.textContent = img.nome;
    info.append(nome);
  }
  const autor = document.createElement("span");
  autor.className = "card-autor";
  autor.textContent = img.autor;
  const data = document.createElement("time");
  data.className = "card-data";
  data.dateTime = img.data;
  data.textContent = formatarData(img.data);
  info.append(autor, data);

  botao.append(moldura, info);
  card.append(botao);
  return card;
}

// Cada miniatura é baixada uma única vez e fica em cache até sair da lista
// ou a galeria ser desmontada.
async function carregarMiniatura(atual, img, card) {
  const moldura = card.querySelector(".card-miniatura");
  const imagem = moldura.querySelector("img");
  card.dataset.miniatura = "carregando";
  atual.miniaturas.set(img.id, null);
  try {
    const blob = await baixarMiniatura(img.url_miniatura);
    if (atual !== estado || !atual.cards.has(img.id)) return; // card ou galeria já foram descartados
    const url = URL.createObjectURL(blob);
    atual.miniaturas.set(img.id, url);
    imagem.onerror = () => mostrarPlaceholder(card, "falhou");
    imagem.src = url;
    imagem.hidden = false;
    moldura.classList.remove("carregando", "falhou");
    moldura.querySelector(".placeholder-miniatura")?.remove();
    card.dataset.miniatura = "ok";
  } catch (erro) {
    if (atual !== estado) return;
    mostrarPlaceholder(card, erro.status === 0 ? "sem-conexao" : "falhou");
  }
}

function mostrarPlaceholder(card, motivo) {
  const moldura = card.querySelector(".card-miniatura");
  moldura.classList.remove("carregando");
  moldura.classList.add("falhou");
  moldura.querySelector("img").hidden = true;
  if (!moldura.querySelector(".placeholder-miniatura")) {
    const aviso = document.createElement("span");
    aviso.className = "placeholder-miniatura";
    aviso.textContent = "Miniatura indisponível";
    moldura.append(aviso);
  }
  card.dataset.miniatura = motivo;
}

// Prévia: abre num <dialog> a miniatura (já em cache) com autor e data.

function ligarPrevia(atual) {
  const { dialogo } = atual;
  dialogo.querySelector(".previa-fechar").addEventListener("click", () => dialogo.close());
  // Clique fora do conteúdo (no fundo escurecido) fecha; Esc é nativo do <dialog>
  dialogo.addEventListener("click", (evento) => {
    if (evento.target === dialogo) dialogo.close();
  });
  dialogo.addEventListener("close", () => {
    atual.idNaPrevia = null;
    dialogo.querySelector(".previa-imagem img").removeAttribute("src");
  });
}

function abrirPrevia(id) {
  const atual = estado;
  const img = atual?.imagens.get(id);
  if (!img) return;
  const { dialogo } = atual;
  const imagem = dialogo.querySelector(".previa-imagem img");
  const moldura = dialogo.querySelector(".previa-imagem");
  const url = atual.miniaturas.get(id);

  atual.idNaPrevia = id;
  moldura.classList.toggle("falhou", !url);
  if (url) {
    imagem.src = url;
    imagem.alt = `Prévia de ${img.nome ?? "imagem"} enviada por ${img.autor}`;
  } else {
    imagem.removeAttribute("src");
    imagem.alt = "Miniatura indisponível";
  }
  dialogo.querySelector("#previa-titulo").textContent = img.nome ?? "Imagem";
  dialogo.querySelector(".previa-meta").textContent =
    `Enviada por ${img.autor} em ${formatarData(img.data)}`;
  dialogo.showModal();
}
