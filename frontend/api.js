// Cliente HTTP compartilhado por todas as telas da interface.
// A interface é servida pela própria Galeria em /app, então as rotas da API
// ficam na mesma origem e são chamadas com caminhos absolutos ("/images").

const CHAVE_SESSAO = "galeria.sessao";

// Sessão no navegador. sessionStorage: sobrevive ao F5, some ao fechar a aba.

export function sessaoAtual() {
  try {
    const bruto = sessionStorage.getItem(CHAVE_SESSAO);
    return bruto ? JSON.parse(bruto) : null;
  } catch {
    return null;
  }
}

export function salvarSessao(token, usuario) {
  sessionStorage.setItem(CHAVE_SESSAO, JSON.stringify({ token, usuario }));
}

export function limparSessao() {
  sessionStorage.removeItem(CHAVE_SESSAO);
}

// Erro padronizado. Toda falha de requisição vira um ErroApi com:
//   status   -> código HTTP (0 quando nem chegou ao servidor)
//   mensagem -> texto pronto para mostrar ao usuário
//   detalhe  -> o "detail" cru devolvido pela API (string ou lista do Pydantic)

export class ErroApi extends Error {
  constructor(status, mensagem, detalhe = null) {
    super(mensagem);
    this.name = "ErroApi";
    this.status = status;
    this.mensagem = mensagem;
    this.detalhe = detalhe;
  }
}

export const EVENTO_SESSAO_EXPIRADA = "sessao-expirada";

// O FastAPI devolve {"detail": "texto"} nos HTTPException e
// {"detail": [{loc, msg, ...}]} nos erros de validação do Pydantic.
function textoDoDetalhe(detalhe) {
  if (typeof detalhe === "string") return detalhe;
  if (Array.isArray(detalhe)) {
    return detalhe
      .map((item) => {
        const campo = Array.isArray(item.loc)
          ? item.loc.filter((parte) => parte !== "body").join(".")
          : "";
        return campo ? `${campo}: ${item.msg}` : item.msg;
      })
      .join("; ");
  }
  return null;
}

async function lerDetalhe(resposta) {
  try {
    const corpo = await resposta.json();
    return corpo?.detail ?? null;
  } catch {
    return null;
  }
}

/**
 * Função única de requisição.
 *
 * @param {string} caminho  rota da API, ex.: "/images"
 * @param {object} opcoes
 *   metodo     "GET" | "POST" | ...
 *   json       objeto enviado como application/json
 *   form       FormData enviado como multipart/form-data
 *   formato    "json" (padrão) | "blob" | "resposta" (devolve o Response cru)
 *   autenticar false para rotas públicas (login e cadastro)
 */
export async function requisicao(
  caminho,
  { metodo = "GET", json, form, formato = "json", autenticar = true } = {},
) {
  const headers = {};
  const sessao = sessaoAtual();
  const comToken = autenticar && Boolean(sessao?.token);
  if (comToken) headers.Authorization = `Bearer ${sessao.token}`;

  let body;
  if (json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(json);
  } else if (form !== undefined) {
    body = form; // o navegador define o boundary do multipart sozinho
  }

  let resposta;
  try {
    resposta = await fetch(caminho, { method: metodo, headers, body });
  } catch {
    throw new ErroApi(
      0,
      "Não foi possível conectar ao servidor. Verifique se a Galeria está no ar.",
    );
  }

  if (!resposta.ok) {
    const detalhe = await lerDetalhe(resposta);
    const mensagem =
      textoDoDetalhe(detalhe) || `Erro ${resposta.status} no servidor.`;

    // Token inválido ou expirado: derruba a sessão e avisa a interface
    // (o app.js volta para a tela de login).
    if (resposta.status === 401 && comToken) {
      limparSessao();
      window.dispatchEvent(new CustomEvent(EVENTO_SESSAO_EXPIRADA));
    }
    throw new ErroApi(resposta.status, mensagem, detalhe);
  }

  if (formato === "resposta") return resposta;
  if (formato === "blob") return resposta.blob();
  if (resposta.status === 204) return null;
  const tipo = resposta.headers.get("content-type") || "";
  return tipo.includes("application/json") ? resposta.json() : resposta.text();
}

// Atalhos de autenticação

export function cadastrar(username, password) {
  return requisicao("/auth/register", {
    metodo: "POST",
    json: { username, password },
    autenticar: false,
  });
}

export function entrar(username, password) {
  return requisicao("/auth/login", {
    metodo: "POST",
    json: { username, password },
    autenticar: false,
  });
}

// Confere se o token salvo ainda vale (rota leve que exige autenticação).
export function validarSessao() {
  return requisicao("/history");
}

// Imagens

export function listarImagens() {
  return requisicao("/images");
}

export function enviarImagem(arquivo) {
  const form = new FormData();
  form.append("file", arquivo, arquivo.name);
  return requisicao("/images", { metodo: "POST", form });
}

// <img src> não envia o header Authorization: a miniatura vem por fetch e
// vira um blob, que a tela exibe com URL.createObjectURL.
export function baixarMiniatura(urlMiniatura) {
  return requisicao(urlMiniatura, { formato: "blob" });
}
