// Formulário de upload: seleção de um ou mais arquivos e validação imediata
// (mesmas regras do POST /images: jpeg/png/gif/webp, até 5 MB).

import { mostrarAviso } from "./toast.js";

const TIPOS_ACEITOS = {
  "image/jpeg": "JPEG",
  "image/png": "PNG",
  "image/gif": "GIF",
  "image/webp": "WebP",
};
const TAMANHO_MAX = 5 * 1024 * 1024; // 5 MB

export function formatarTamanho(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1).replace(".", ",")} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1).replace(".", ",")} MB`;
}

// Devolve o motivo da rejeição, ou null se o arquivo pode ser enviado.
function problemaDoArquivo(arquivo) {
  if (!(arquivo.type in TIPOS_ACEITOS)) {
    return "tipo não aceito (use JPEG, PNG, GIF ou WebP)";
  }
  if (arquivo.size === 0) return "arquivo vazio";
  if (arquivo.size > TAMANHO_MAX) {
    return `${formatarTamanho(arquivo.size)}, acima do limite de 5 MB`;
  }
  return null;
}

function criarItemDaLista(arquivo, problema) {
  const item = document.createElement("li");
  item.className = problema ? "arquivo invalido" : "arquivo";
  const nome = document.createElement("span");
  nome.className = "arquivo-nome";
  nome.textContent = arquivo.name;
  const info = document.createElement("span");
  info.className = "arquivo-info";
  info.textContent = problema ?? formatarTamanho(arquivo.size);
  item.append(nome, info);
  return item;
}

/**
 * Monta o formulário dentro de `container`.
 * `enviar(arquivos)` recebe só os arquivos válidos.
 */
export function montarUpload(container, { enviar }) {
  container.innerHTML = `
    <form class="upload" novalidate>
      <div class="upload-cabecalho">
        <h2>Enviar imagens</h2>
        <p class="dica">JPEG, PNG, GIF ou WebP, até 5 MB cada.</p>
      </div>
      <div class="upload-acoes">
        <label class="botao seletor">
          Escolher imagens
          <input type="file" name="arquivos" multiple
                 accept="image/jpeg,image/png,image/gif,image/webp">
        </label>
        <button type="submit" class="botao primario" disabled>Enviar</button>
      </div>
      <ul class="lista-arquivos" aria-live="polite"></ul>
    </form>`;

  const form = container.querySelector("form");
  const input = form.elements.arquivos;
  const lista = form.querySelector(".lista-arquivos");
  const botaoEnviar = form.querySelector('button[type="submit"]');

  function separar() {
    const arquivos = [...input.files];
    const validos = [];
    const invalidos = [];
    for (const arquivo of arquivos) {
      const problema = problemaDoArquivo(arquivo);
      if (problema) invalidos.push({ arquivo, problema });
      else validos.push(arquivo);
    }
    return { arquivos, validos, invalidos };
  }

  // Retorno imediato ao escolher os arquivos
  input.addEventListener("change", () => {
    const { arquivos, validos, invalidos } = separar();
    lista.replaceChildren(
      ...arquivos.map((a) => criarItemDaLista(a, problemaDoArquivo(a))),
    );
    for (const { arquivo, problema } of invalidos) {
      mostrarAviso(`"${arquivo.name}" não pode ser enviado: ${problema}.`, "erro");
    }
    botaoEnviar.disabled = validos.length === 0;
    botaoEnviar.textContent = validos.length > 1 ? `Enviar ${validos.length}` : "Enviar";
  });

  function limpar() {
    form.reset();
    lista.replaceChildren();
    botaoEnviar.disabled = true;
    botaoEnviar.textContent = "Enviar";
  }

  form.addEventListener("submit", async (evento) => {
    evento.preventDefault();
    const { validos } = separar();
    if (!validos.length) {
      mostrarAviso("Escolha ao menos uma imagem válida.", "erro");
      return;
    }
    botaoEnviar.disabled = true;
    input.disabled = true;
    form.setAttribute("aria-busy", "true");
    botaoEnviar.textContent = validos.length > 1 ? `Enviando ${validos.length}…` : "Enviando…";
    try {
      await enviar(validos);
    } finally {
      form.removeAttribute("aria-busy");
      input.disabled = false;
      limpar();
    }
  });
}
