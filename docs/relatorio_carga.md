# Relatório de teste de carga

- Data: 28/11/2026 00:03
- Máquina: Windows 11, Python 3.14.0
- Parâmetros: 20 usuários x 5 ciclos, concorrência 20
- Requisições medidas: 400 em 4.39 s (91.1 req/s)
- Erros: 0

| Operação | Qtd | Média (ms) | p50 (ms) | p95 (ms) | Máx (ms) |
|---|---:|---:|---:|---:|---:|
| upload | 100 | 555.7 | 554.1 | 592.3 | 629.5 |
| listagem | 100 | 8.3 | 7.9 | 13.1 | 15.3 |
| previa | 100 | 19.3 | 18.5 | 30.1 | 33.3 |
| download | 100 | 20.2 | 20.0 | 30.4 | 36.1 |
