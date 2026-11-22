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
Lista as imagens de todos os usuários. `200`:
```json
[{"id": "32fe5d7c-...", "autor": "ana", "data": "2026-11-17T01:50:00",
  "url_miniatura": "/images/32fe5d7c-.../thumbnail"}]
```
`401` sem token

### GET /images/{id}/thumbnail
`200` imagem `image/jpeg` · `401` · `404` imagem não existe ou arquivo não está mais no disco

### GET /images/{id}/download
`200` arquivo original, com o nome enviado no `Content-Disposition` · `401` · `404` imagem não existe ou
arquivo não está mais no disco

### GET /history
Só os uploads do usuário logado. `200`:
```json
[{"usuario": "ana", "image_id": "32fe5d7c-...", "nome": "foto.png", "data": "2026-11-17T01:50:00"}]
```
`401` sem token

## Processamento — http://localhost:8002 (interna)

### POST /internal/thumbnail
`multipart/form-data` com o campo `file`. `200` corpo = bytes `image/jpeg` (lado máx. 256 px) ·
`400` vazio · `413` grande · `415` tipo inválido · `422` imagem corrompida
