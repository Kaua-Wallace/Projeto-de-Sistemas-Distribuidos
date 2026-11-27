// Componente de aviso (toast) reutilizável por todas as telas.
// Uso: mostrarAviso("Imagem enviada", "sucesso");  tipos: info | sucesso | erro

const DURACAO_MS = { info: 4000, sucesso: 4000, erro: 7000 };
const MAXIMO_NA_TELA = 5;

function areaDeAvisos() {
  let area = document.getElementById("avisos");
  if (!area) {
    area = document.createElement("div");
    area.id = "avisos";
    area.className = "avisos";
    document.body.append(area);
  }
  return area;
}

export function mostrarAviso(mensagem, tipo = "info") {
  const area = areaDeAvisos();

  const aviso = document.createElement("div");
  aviso.className = `aviso aviso-${tipo}`;
  // Erros interrompem o leitor de tela; os demais são anunciados educadamente
  aviso.setAttribute("role", tipo === "erro" ? "alert" : "status");

  const texto = document.createElement("span");
  texto.textContent = mensagem;

  const fechar = document.createElement("button");
  fechar.type = "button";
  fechar.className = "aviso-fechar";
  fechar.setAttribute("aria-label", "Fechar aviso");
  fechar.textContent = "×";

  aviso.append(texto, fechar);

  let removido = false;
  const remover = () => {
    if (removido) return;
    removido = true;
    aviso.classList.add("saindo");
    setTimeout(() => aviso.remove(), 200);
  };

  fechar.addEventListener("click", remover);
  setTimeout(remover, DURACAO_MS[tipo] ?? DURACAO_MS.info);

  area.append(aviso);
  while (area.children.length > MAXIMO_NA_TELA) area.firstElementChild.remove();

  return remover;
}
