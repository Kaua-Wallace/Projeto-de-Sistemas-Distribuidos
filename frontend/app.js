// Ponto de entrada da interface: login, cadastro e troca de telas.

import {
  EVENTO_SESSAO_EXPIRADA,
  ErroApi,
  cadastrar,
  entrar,
  limparSessao,
  salvarSessao,
  sessaoAtual,
  validarSessao,
} from "./api.js";
import { mostrarAviso } from "./toast.js";
import { montarUpload } from "./upload.js";
import { iniciarGaleria, pararGaleria } from "./galeria.js";

const carregandoInicial = document.getElementById("carregando-inicial");
const telaAuth = document.getElementById("tela-auth");
const telaApp = document.getElementById("tela-app");
const conteudo = document.getElementById("conteudo");
const nomeUsuario = document.getElementById("nome-usuario");
const botaoSair = document.getElementById("botao-sair");
const formEntrar = document.getElementById("form-entrar");
const formCadastrar = document.getElementById("form-cadastrar");
const abas = document.querySelectorAll("[data-aba]");

// Mesmas regras do POST /auth/register
const USUARIO_MIN = 3;
const USUARIO_MAX = 30;
const SENHA_MIN = 6;

// Troca de telas

let telaAtual = "carregando"; // carregando | auth | app

function mostrarTela(nome) {
  telaAtual = nome;
  carregandoInicial.hidden = true;
  telaAuth.hidden = nome !== "auth";
  telaApp.hidden = nome !== "app";
}

function trocarAba(aba) {
  abas.forEach((botao) => {
    botao.setAttribute("aria-selected", String(botao.dataset.aba === aba));
  });
  formEntrar.hidden = aba !== "entrar";
  formCadastrar.hidden = aba !== "cadastrar";
  limparErros(formEntrar);
  limparErros(formCadastrar);
  (aba === "entrar" ? formEntrar : formCadastrar).elements.username.focus();
}

// Validação e mensagens

function validarCampos(form) {
  const erros = {};
  const usuario = form.elements.username.value.trim();
  const senha = form.elements.password.value;
  if (!usuario) {
    erros.username = "Informe o usuário.";
  } else if (usuario.length < USUARIO_MIN || usuario.length > USUARIO_MAX) {
    erros.username = `O usuário deve ter de ${USUARIO_MIN} a ${USUARIO_MAX} caracteres.`;
  }
  if (!senha) {
    erros.password = "Informe a senha.";
  } else if (senha.length < SENHA_MIN) {
    erros.password = `A senha deve ter no mínimo ${SENHA_MIN} caracteres.`;
  }
  return erros;
}

function mostrarErrosCampos(form, erros) {
  form.querySelectorAll("[data-erro]").forEach((el) => {
    const campo = el.dataset.erro;
    const mensagem = erros[campo] || "";
    el.textContent = mensagem;
    form.elements[campo].setAttribute("aria-invalid", mensagem ? "true" : "false");
  });
}

function mostrarErroForm(form, mensagem) {
  const caixa = form.querySelector(".erro-form");
  caixa.textContent = mensagem || "";
  caixa.hidden = !mensagem;
}

function limparErros(form) {
  mostrarErrosCampos(form, {});
  mostrarErroForm(form, "");
}

function mensagemDeErroAuth(erro) {
  if (!(erro instanceof ErroApi)) return "Erro inesperado. Tente novamente.";
  if (erro.status === 401) return "Usuário ou senha incorretos.";
  if (erro.status === 409) return "Esse usuário já existe. Escolha outro nome ou entre.";
  return erro.mensagem; // 422 e demais: texto do próprio servidor
}

function ocupado(form, sim, textoOcupado) {
  const botao = form.querySelector('button[type="submit"]');
  if (sim) {
    botao.dataset.textoOriginal = botao.textContent;
    botao.textContent = textoOcupado;
  } else if (botao.dataset.textoOriginal) {
    botao.textContent = botao.dataset.textoOriginal;
  }
  botao.disabled = sim;
}

// Fluxos de login e cadastro

async function fazerLogin(usuario, senha) {
  const { token } = await entrar(usuario, senha);
  salvarSessao(token, usuario);
  abrirApp();
}

async function aoEnviar(evento, form, acao) {
  evento.preventDefault();
  mostrarErroForm(form, "");
  const erros = validarCampos(form);
  mostrarErrosCampos(form, erros);
  if (Object.keys(erros).length) {
    form.querySelector('[aria-invalid="true"]')?.focus();
    return;
  }

  const usuario = form.elements.username.value.trim();
  const senha = form.elements.password.value;
  ocupado(form, true, acao === "entrar" ? "Entrando…" : "Criando conta…");
  try {
    if (acao === "cadastrar") {
      await cadastrar(usuario, senha);
      mostrarAviso(`Conta "${usuario}" criada!`, "sucesso");
    }
    await fazerLogin(usuario, senha);
    form.reset();
  } catch (erro) {
    mostrarErroForm(form, mensagemDeErroAuth(erro));
    if (erro instanceof ErroApi && erro.status === 0) mostrarAviso(erro.mensagem, "erro");
  } finally {
    ocupado(form, false);
  }
}

// Tela principal

function abrirApp() {
  nomeUsuario.textContent = sessaoAtual()?.usuario ?? "";
  mostrarTela("app");
  iniciarApp();
}

// Ponto de montagem das funcionalidades da tela principal (galeria, histórico...)
function iniciarApp() {
  conteudo.innerHTML = `
    <div id="area-upload"></div>
    <div id="area-galeria"></div>`;
  montarUpload(document.getElementById("area-upload"), {
    enviar: async (arquivos) => {
      mostrarAviso(`${arquivos.length} imagem(ns) pronta(s) para envio.`, "info");
    },
  });
  iniciarGaleria(document.getElementById("area-galeria"));
}

// Desmonta o que iniciarApp() montou (timers, object URLs...)
function encerrarApp() {
  pararGaleria();
  conteudo.replaceChildren();
}

function voltarParaLogin() {
  encerrarApp();
  nomeUsuario.textContent = "";
  mostrarTela("auth");
  trocarAba("entrar");
}

// O botão Sair só limpa a sessão local: a API ainda não tem POST /auth/logout
// (Membro 5). Quando a rota existir, basta chamá-la aqui antes de limpar.
function sair() {
  limparSessao();
  voltarParaLogin();
  mostrarAviso("Você saiu da sua conta.", "info");
}

// Disparado pelo api.js quando a API responde 401 para um token salvo.
function aoExpirarSessao() {
  if (telaAtual === "auth") return; // várias requisições podem falhar juntas
  voltarParaLogin();
  mostrarAviso("Sua sessão expirou. Entre novamente.", "erro");
}

// Ao abrir ou recarregar a página, confere se o token salvo ainda vale.
async function restaurarSessao() {
  if (!sessaoAtual()) {
    mostrarTela("auth");
    return;
  }
  try {
    await validarSessao();
    abrirApp();
  } catch (erro) {
    if (erro instanceof ErroApi && erro.status === 0) {
      // Servidor fora do ar: mantém a sessão e abre o app; as telas mostram
      // o erro de conexão e se recuperam quando a Galeria voltar.
      abrirApp();
      mostrarAviso(erro.mensagem, "erro");
    } else if (telaAtual !== "auth") {
      // 401 já foi tratado pelo evento de sessão expirada
      limparSessao();
      mostrarTela("auth");
    }
  }
}

// Inicialização

abas.forEach((botao) => botao.addEventListener("click", () => trocarAba(botao.dataset.aba)));
formEntrar.addEventListener("submit", (e) => aoEnviar(e, formEntrar, "entrar"));
formCadastrar.addEventListener("submit", (e) => aoEnviar(e, formCadastrar, "cadastrar"));
botaoSair.addEventListener("click", sair);
window.addEventListener(EVENTO_SESSAO_EXPIRADA, aoExpirarSessao);

restaurarSessao();
