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
