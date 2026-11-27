// Ponto de entrada da interface: login, cadastro e troca de telas.

import { ErroApi, cadastrar, entrar, salvarSessao, sessaoAtual } from "./api.js";
import { mostrarAviso } from "./toast.js";

const carregandoInicial = document.getElementById("carregando-inicial");
const telaAuth = document.getElementById("tela-auth");
const telaApp = document.getElementById("tela-app");
const conteudo = document.getElementById("conteudo");
const formEntrar = document.getElementById("form-entrar");
const formCadastrar = document.getElementById("form-cadastrar");
const abas = document.querySelectorAll("[data-aba]");

// Mesmas regras do POST /auth/register
const USUARIO_MIN = 3;
const USUARIO_MAX = 30;
const SENHA_MIN = 6;

// Troca de telas

function mostrarTela(nome) {
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
  mostrarTela("app");
  iniciarApp();
}

// Ponto de montagem das funcionalidades da tela principal (galeria, histórico...)
export function iniciarApp() {
  conteudo.innerHTML = '<p class="placeholder">Galeria em breve.</p>';
}

// Inicialização

abas.forEach((botao) => botao.addEventListener("click", () => trocarAba(botao.dataset.aba)));
formEntrar.addEventListener("submit", (e) => aoEnviar(e, formEntrar, "entrar"));
formCadastrar.addEventListener("submit", (e) => aoEnviar(e, formCadastrar, "cadastrar"));

if (sessaoAtual()) {
  abrirApp();
} else {
  mostrarTela("auth");
}
