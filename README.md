# Galeria Colaborativa de Imagens

Projeto de Sistemas Distribuídos — **Entrega 1 (Arquitetura e Escopo)**.
Repositório de imagens colaborativo: o usuário se cadastra, envia fotos (`multipart/form-data`), lista as imagens (autor, data e miniatura), vê a prévia e baixa o original. O sistema guarda um histórico de uploads.

## Tecnologia escolhida

**Python + FastAPI** (API RESTful sobre HTTP), com Pillow para gerar miniaturas e httpx para um serviço chamar o outro.

Justificativa: o FastAPI permite criar cada microsserviço em poucas linhas, em porta própria, com suporte nativo a `multipart/form-data` e validação de dados. Ele também gera a documentação interativa das rotas em `/docs`. É uma alternativa equivalente às tecnologias sugeridas no enunciado.
