# Contrato da API REST

Rotas protegidas usam o header `Authorization: Bearer <token>`.

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
`400` vazio · `401` sem token · `413` maior que 5 MB · `415` tipo inválido · `422` sem arquivo ·
`503` Processamento indisponível

### GET /images
`200`:
```json
[{"id": "32fe5d7c-...", "autor": "ana", "data": "2026-11-17T01:50:00",
  "url_miniatura": "/images/32fe5d7c-.../thumbnail"}]
```
`401` sem token

### GET /images/{id}/thumbnail
`200` imagem `image/jpeg` · `401` · `404` imagem não existe

### GET /images/{id}/download
`200` arquivo original · `401` · `404`

### GET /history
`200`:
```json
[{"usuario": "ana", "image_id": "32fe5d7c-...", "nome": "foto.png", "data": "2026-11-17T01:50:00"}]
```

## Processamento — http://localhost:8002 (interna)

### POST /internal/thumbnail
`multipart/form-data` com o campo `file`. `200` corpo = bytes `image/jpeg` (lado máx. 256 px) ·
`400` vazio · `413` grande · `415` tipo inválido · `422` imagem corrompida
