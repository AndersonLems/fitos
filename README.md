# FitOS

Sistema pessoal de treino, alimentação, mercado e evolução física. Streamlit + SQLite, com o Gemini
como assistente opcional. Suporta vários perfis (pessoas) na mesma instalação.

```bash
pip install -r requirements.txt
cp .env.example .env        # preencha GEMINI_API_KEY e FITOS_ACCESS_CODE
streamlit run app.py
```

Na primeira execução o banco é criado (`data/fitos.db`, migrações Alembic), a tabela TACO é carregada
e o catálogo de exercícios é baixado do ExerciseDB (~1–2 min, só uma vez; cópia dos metadados em
`data/exercisedb.json`).

## Em produção nesta máquina

- Serviço: `systemctl --user {status,restart} fitos` (porta 127.0.0.1:8501; log em `logs/streamlit.log`).
- Túnel: `fitos.aejsolutions.com.br` → `127.0.0.1:8501`, pela regra de ingress do túnel `brasil-em-dados`
  (`~/.cloudflared/config.yml`, serviço `cloudflared-brasil-em-dados`).
- Acesso pelo túnel exige o código `FITOS_ACCESS_CODE` do `.env` (cookie de 30 dias no navegador).
  Não é um sistema de contas; para trocar, edite o `.env` e reinicie o serviço.

## Páginas

| Página | O que faz |
|---|---|
| Painel | Peso, meta, IMC, calorias estimadas, consumo do dia, treinos da semana, custos e recomendações |
| Meus treinos | Treino de hoje (com troca do dia), registro de séries, cronômetro, ficha, versões, progressão |
| Biblioteca de exercícios | Busca, GIF/vídeo, instruções, erros comuns, fonte e licença |
| Meu plano alimentar | Cardápios de 1/7/15/30/31 dias, macros e custos por refeição/dia, versão econômica, substituições |
| Mercado inteligente | Preços por estabelecimento, comparação, histórico, lista de compras interativa, custos, gastos |
| Minha despensa | Estoque com validade; “O que posso preparar hoje?” e refeições de amanhã com o que há em casa |
| Minha evolução | Peso com média móvel, medidas, fotos, frequência, cargas e análise opcional pelo Gemini |
| Meu personal IA | Chat com ferramentas estruturadas; alterações só após confirmação |
| Meu perfil | Dados obrigatórios e opcionais, estimativa energética, exclusão do perfil |
| Configurações | Modelo Gemini, uso de tokens, backup, exportação CSV/JSON, exclusão de dados |

## Arquitetura

```
app.py                  navegação, perfis, onboarding, portão de acesso
views/                  uma página por arquivo (st.navigation)
components/             ui.py (tema editorial), auth.py, state.py, timer.py
services/               regras de negócio — determinísticas, sem Streamlit
  nutrition_service     macros (TACO), cru/cozido/comprado, gerador local, versão econômica
  pricing_service       cotações, normalização R$/kg|l|un, melhor preço, comparação
  shopping_service      consolidação, estoque, embalagens, totais, compras
  workout_service       fichas, versões, treino do dia, sessões, progressão conservadora
  gemini_service        cliente, saídas estruturadas (Pydantic), nova tentativa, uso de tokens
  ai_planner            prompts compactos + validação contra o catálogo local
  chat_service          ferramentas do chat, validação e confirmação
integrations/           exercisedb.py, wger.py, workoutdb.py (não disponível)
database/               models.py, connection.py; migrations/ (Alembic)
utils/units.py          Decimal, unidades, embalagens
tests/                  pytest (41 testes)
```

Separação pedida no projeto: o Python calcula nutrientes, conversões, rendimento, preços, embalagens,
orçamentos e estatísticas; o Gemini só propõe (cardápios, fichas, substituições, textos). Toda saída do
Gemini é validada (IDs precisam existir no catálogo enviado, porções e prescrições em faixas razoáveis);
se vier inconsistente, há uma nova tentativa com a lista de erros e, persistindo, nada é salvo.

### Economia de tokens

Nenhuma chamada ao Gemini é automática. Fichas e cardápios têm **gerador local** (sem IA) além da opção
Gemini. Planos de 15–31 dias usam 7 cardápios distintos em ciclo. O chat envia contexto resumido e as
últimas 12 mensagens; ações de alteração não fazem segunda chamada. Leituras geradas (painel, evolução)
ficam salvas e só são refeitas quando você pede. O uso fica registrado em Configurações.

## Fontes e decisões

- **Nutrição:** TACO 4ª ed. (NEPA/UNICAMP, 2011), 597 alimentos, CSV normalizado do projeto
  [taco-api](https://github.com/raulfdm/taco-api) em `assets/taco/`. Valores ausentes na TACO ficam
  ausentes (o total avisa “parcial”), nunca estimados.
- **Cru × cozido × comprado:** porção consumida ÷ índice de cocção = peso cru; ÷ fator comestível = peso
  comprado. Índices de referência de técnica dietética (arroz 2,8; feijão 2,4; frango grelhado 0,70…) e
  fatores comestíveis (banana 0,65, ovo 0,88…) são aproximações editáveis no banco (`foods`).
- **Energia:** Mifflin-St Jeor × fator de atividade; ajuste por objetivo (−15% / +10% / −5% / 0) com piso no
  gasto basal; proteína 1,4–2,0 g/kg (peso de referência IMC 27 quando IMC ≥ 30). Sem sexo, nível de
  atividade ou objetivo, o valor aparece como **provisório**.
- **Exercícios:**
  - ExerciseDB open source (`oss.exercisedb.dev`): sem chave, ~1.500 exercícios com GIF, limite de taxa.
    Termos de mídia não autorizam redistribuição explicitamente → **sem cache local**, só URL + atribuição.
  - wger: CC-BY-SA, imagens e ~80 vídeos (vários em HEVC/.MOV, que alguns navegadores não tocam).
    Importação opcional na Biblioteca.
  - ExerciseDB comercial (RapidAPI): exige chave paga — não usada.
  - WorkoutDB: domínios não responderam e não há API documentada → **não implementado**, sem simulação.
  - 62 exercícios principais têm nome em português e padrão de movimento (curadoria em
    `services/catalog_data.py`); são os usados pelos geradores e oferecidos ao Gemini.
- **Preços:** apenas os cadastrados. Há um botão para carregar os preços de exemplo do enunciado, marcados
  como “Exemplo (fictício)”.

## Dados, backup e privacidade

- Perfis são independentes (medidas, treinos, cardápios, despensa, listas, compras, conversas). Produtos,
  preços e estabelecimentos são compartilhados pela instalação.
- Backup automático diário (API de backup do SQLite) em `backups/`, 20 mais recentes; manual em
  Configurações. Exportação ZIP em CSV ou JSON por perfil ou completa. Exclusões pedem confirmação e
  fazem backup antes.
- `.env`, `data/`, `backups/` e `logs/` estão no `.gitignore`. Logs filtram a chave da API.

## Limitações conhecidas

- Restrições alimentares são aplicadas por palavras-chave (“vegetariano”, “lactose”, “glúten”, nomes de
  alimentos). Confira os cardápios.
- O catálogo curado de alimentos tem ~85 itens TACO; os demais 500+ existem no banco e podem ser ligados a
  produtos, mas não entram nos geradores.
- Sugestões de progressão de carga usam dupla progressão simples; incrementos podem não coincidir com as
  anilhas/placas disponíveis.
- O chat cobre as ações listadas; pedidos fora delas recebem resposta em texto.
- As chamadas ao Gemini foram testadas com respostas simuladas; o formato dos esquemas foi verificado
  contra a API sem consumir tokens. O comportamento real do modelo só aparece no primeiro uso.

## Testes

```bash
python3 -m pytest
```

Cobrem unidades e Decimal, normalização de preços, rendimento e fator comestível, consolidação, pessoas,
embalagens, estoque (validade, unidades), totais da lista, estimativa energética, gerador local,
versão econômica, divisão de treino, limitações, troca do treino do dia, progressão conservadora e
validação das saídas/ações do Gemini.
