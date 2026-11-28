# Contrato da API REST

Rotas protegidas usam o header `Authorization: Bearer <token>`. Sem token, ou com token inválido, a resposta é `401`.

## Galeria — http://localhost:8001

### POST /auth/register
```json
{"username": "ana", "password": "segredo"}
```
`201` `{"username": "ana"}` · `409` usuário existe · `422` formato inválido

### POST /auth/login
Mesmo corpo do cadastro. `200` `{"token": "abc123..."}` · `401` credenciais inválidas

### POST /images
`multipart/form-data` com o campo `file` (jpeg, png, gif ou webp, até 5 MB).
```bash
curl -X POST localhost:8001/images -H "Authorization: Bearer $TOKEN" -F "file=@foto.png"
```
`201`:
```json
{"id": "32fe5d7c-...", "autor": "ana", "data": "2026-11-17T01:50:00", "nome": "foto.png",
 "tipo": "image/png", "tamanho": 1949, "url_miniatura": "/images/32fe5d7c-.../thumbnail"}
```
`400` vazio · `401` sem token · `413` maior que 5 MB · `415` tipo inválido · `422` sem arquivo ou
imagem corrompida (repassado do Processamento) · `502` falha inesperada no Processamento ·
`503` Processamento indisponível

### GET /images
Lista as imagens de todos os usuários, mais recentes primeiro por padrão. Parâmetros opcionais:

| Parâmetro | Valores | Padrão | Descrição |
|---|---|---:|---|
| `autor` | nome de usuário | — | Filtra pelo nome exato do autor. |
| `ordem` | `data_desc`, `data_asc` | `data_desc` | Ordena pela data do envio, da mais recente ou da mais antiga. |
| `limit` | inteiro maior que 0 | `100` | Número máximo de imagens retornadas. |
| `offset` | inteiro maior ou igual a 0 | `0` | Número de imagens a ignorar para paginar os resultados. |

Os filtros e a ordenação são aplicados antes da paginação. Exemplo:

```bash
curl 'localhost:8001/images?autor=ana&ordem=data_asc&limit=20&offset=0' \
  -H "Authorization: Bearer $TOKEN"
```

`200`:
```json
[{"id": "32fe5d7c-...", "autor": "ana", "data": "2026-11-17T01:50:00",
  "nome": "foto.png", "tamanho": 1949,
  "url_miniatura": "/images/32fe5d7c-.../thumbnail"}]
```
`401` sem token · `422` valor inválido para `ordem`, `limit` ou `offset`

### GET /images/{id}/thumbnail
`200` imagem `image/jpeg` · `401` · `404` imagem não existe ou arquivo não está mais no disco

### GET /images/{id}/download
`200` arquivo original, com o nome enviado no `Content-Disposition` · `401` · `404` imagem não existe ou
arquivo não está mais no disco

### GET /history
Retorna somente os uploads do usuário autenticado, ordenados do mais recente para o mais antigo. Cada item inclui a URL da miniatura:
```json
[{"usuario": "ana", "image_id": "32fe5d7c-...", "nome": "foto.png",
  "data": "2026-11-17T01:50:00", "url_miniatura": "/images/32fe5d7c-.../thumbnail"}]
```
`401` sem token

## Processamento — http://localhost:8002 (interna)

### POST /internal/thumbnail
`multipart/form-data` com o campo `file`. A Galeria também envia `X-User-Context` para correlacionar
os logs entre os serviços; esse cabeçalho é apenas contexto de log, não autentica a chamada.

Exemplo de chamada e gravação da miniatura:
```bash
curl -X POST http://localhost:8002/internal/thumbnail \
  -H "X-User-Context: ana" \
  -F "file=@foto.png" \
  --output miniatura.jpg
```

`200` corpo = bytes `image/jpeg` (lado máx. 256 px) ·
`400` vazio · `413` grande · `415` tipo inválido · `422` imagem corrompida
