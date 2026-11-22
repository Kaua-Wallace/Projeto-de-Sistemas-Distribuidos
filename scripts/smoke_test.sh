#!/usr/bin/env bash
# Fluxo completo contra os serviços reais: cadastro -> login -> upload -> listagem -> prévia -> download -> histórico.
set -uo pipefail

cd "$(dirname "$0")/.."

GALERIA="${GALERIA_URL:-http://localhost:8001}"
PROCESSAMENTO="${PROCESSAMENTO_URL:-http://localhost:8002}"
if [ -x .venv/bin/python ]; then PY=.venv/bin/python; else PY=python3; fi

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

ok() { echo "OK      $1"; }
falha() { echo "FALHOU  $1"; exit 1; }
confere() {
    if [ "$2" = "$3" ]; then ok "$1"; else falha "$1 (esperado $3, veio $2)"; fi
}
json() { "$PY" -c "import sys, json; print(json.load(sys.stdin)$1)"; }

USUARIO="smoke_$(date +%s)"
CRED="{\"username\": \"$USUARIO\", \"password\": \"segredo123\"}"

confere "health processamento" "$(curl -s -o /dev/null -w '%{http_code}' "$PROCESSAMENTO/health")" 200
confere "health galeria" "$(curl -s -o /dev/null -w '%{http_code}' "$GALERIA/health")" 200

confere "cadastro" "$(curl -s -o /dev/null -w '%{http_code}' -X POST "$GALERIA/auth/register" \
    -H 'Content-Type: application/json' -d "$CRED")" 201

TOKEN="$(curl -s -X POST "$GALERIA/auth/login" -H 'Content-Type: application/json' -d "$CRED" | json '["token"]')" \
    || falha "login"
ok "login"
AUTH="Authorization: Bearer $TOKEN"

"$PY" -c "from PIL import Image; Image.new('RGB', (800, 600), 'green').save('$TMP/foto.png')"

STATUS="$(curl -s -o "$TMP/upload.json" -w '%{http_code}' -X POST "$GALERIA/images" -H "$AUTH" -F "file=@$TMP/foto.png")"
confere "upload" "$STATUS" 201
ID="$(json '["id"]' < "$TMP/upload.json")"

curl -s "$GALERIA/images" -H "$AUTH" | json '' | grep -q "$ID" && ok "listagem contém a imagem" \
    || falha "listagem contém a imagem"

TIPO="$(curl -s -o "$TMP/miniatura.jpg" -w '%{http_code} %{content_type}' "$GALERIA/images/$ID/thumbnail" -H "$AUTH")"
confere "prévia" "$TIPO" "200 image/jpeg"

confere "download" "$(curl -s -o "$TMP/original.png" -w '%{http_code}' "$GALERIA/images/$ID/download" -H "$AUTH")" 200
cmp -s "$TMP/foto.png" "$TMP/original.png" && ok "original idêntico ao enviado" || falha "original idêntico ao enviado"

curl -s "$GALERIA/history" -H "$AUTH" | json '' | grep -q "$ID" && ok "histórico contém o upload" \
    || falha "histórico contém o upload"

confere "listagem sem token" "$(curl -s -o /dev/null -w '%{http_code}' "$GALERIA/images")" 401

echo "Smoke test concluído com sucesso."
