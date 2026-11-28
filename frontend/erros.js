// centraliza as mensagens exibidas para os principais codigos de erro HTTP
const MENSAGENS_POR_STATUS = {
  401: "Sua sessão expirou. Entre novamente.",
  413: "O arquivo ultrapassa o limite de 5 MB.",
  415: "Formato não permitido. Utilize JPEG, PNG, GIF ou WebP.",
  422: "O arquivo é inválido, está corrompido ou não corresponde ao formato declarado.",
  500: "O servidor encontrou um erro inesperado. Tente novamente.",
  502: "Não foi possível gerar a miniatura. Tente novamente.",
  503: "Serviço de processamento indisponível. Tente novamente mais tarde.",
};

const MENSAGEM_SEM_CONEXAO =
  "Não foi possível conectar ao servidor. Verifique se a Galeria está no ar.";
const MENSAGEM_INESPERADA = "Ocorreu um erro inesperado. Tente novamente.";

//retorna uma mensagem padrao de acordo com o código HTTP recebido
export function mensagemPadraoDoStatus(status) {
  return MENSAGENS_POR_STATUS[status] ?? `Erro ${status} no servidor.`;
}

// identifica o tipo de falha e seleciona uma mensagem adequada para o usuario
export function mensagemDeErro(erro) {
  const status = erro?.status;
  if (status === 0) return MENSAGEM_SEM_CONEXAO;
  if (typeof status === "number" && MENSAGENS_POR_STATUS[status]) {
    return MENSAGENS_POR_STATUS[status];
  }
  if (typeof erro?.mensagem === "string" && erro.mensagem) return erro.mensagem;
  return MENSAGEM_INESPERADA;
}

// identifica falhas relacionadas a geraçao ou disponibilidade das miniaturas
export function ehFalhaDeMiniatura(erro) {
  return erro?.status === 502 || erro?.status === 503;
}

// monta uma mensagem de erro especifica para cada arquivo enviado
export function mensagemDeFalhaDeUpload(nomeArquivo, erro) {
  const motivo = mensagemDeErro(erro);
  if (ehFalhaDeMiniatura(erro)) {
    return `Falha na miniatura de "${nomeArquivo}": ${motivo}`;
  }
  return `Falha ao enviar "${nomeArquivo}": ${motivo}`;
}