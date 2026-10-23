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
- Entrada por perfil: cada pessoa escolhe o perfil e digita o código dele (PBKDF2 no banco; cookie
  assinado `fitos_sessao` por 30 dias, com `FITOS_SECRET`). Cada sessão só enxerga o próprio perfil.
- `FITOS_ACCESS_CODE` (código da instalação) é pedido para criar perfis e abre perfis antigos que ainda
  não têm código próprio. Trocar `FITOS_SECRET` encerra todas as sessões; trocar o código de um perfil
  encerra as sessões daquele perfil. Cinco erros seguidos bloqueiam o perfil por 5 minutos.

## Páginas

| Página | O que faz |
|---|---|
| Painel | Peso, meta, IMC, calorias estimadas, consumo do dia, treinos da semana, custos e recomendações |
| Meus treinos | Treino de hoje (com troca do dia), registro de séries, cronômetro, ficha, versões, progressão; “Ver execução” abre GIF, prescrição, passos e últimas cargas |
| Biblioteca de exercícios | Busca, GIF/vídeo, instruções, erros comuns, fonte e licença |
| Meu plano alimentar | Cardápios de 1/7/15/30/31 dias com 3 a 6 refeições, metas do cenário escolhido, macros e custos por refeição/dia, versão econômica, substituições |
| Mercado inteligente | Escanear produto (código de barras ou etiqueta com IA), preços por estabelecimento, comparação, histórico, lista de compras com “quanto tenho para esta compra”, compra avulsa, custos, gastos e orçamento por mês |
| Minha despensa | Estoque com validade; “O que posso preparar hoje?” e refeições de amanhã com o que há em casa |
| Minha evolução | Prazo da meta (cenários conservador, mais rápido e intenso, com projeção e análise opcional da IA), peso com média móvel, medidas, fotos, frequência, cargas e análise de tendências |
| Meu personal IA | Chat com ferramentas estruturadas; alterações só após confirmação |
| Meu perfil | Dados obrigatórios e opcionais, estimativa energética, orçamento fixo, tema de cores (Lima, Oceano, Brasa), exclusão do perfil |
| Configurações | Modelo Gemini, uso de tokens, backup, exportação CSV/JSON, exclusão de dados |

## Arquitetura

```
app.py                  navegação, perfis, onboarding, portão de acesso
views/                  uma página por arquivo (st.navigation)
components/             ui.py (temas e primitivos), auth.py, state.py, timer.py, scan_view.py
services/               regras de negócio — determinísticas, sem Streamlit
  nutrition_service     macros (TACO), cru/cozido/comprado, gerador local, versão econômica
  pricing_service       cotações, normalização R$/kg|l|un, melhor preço, comparação
  shopping_service      consolidação, estoque, embalagens, totais, compras, compra avulsa
  budget_service        orçamento fixo do perfil com ajuste por mês
  goal_service          prazo da meta de peso: cenários, revisão limitada da IA, metas diárias
  product_scan          código de barras (zxing-cpp), Open Food Facts, leitura de etiqueta pelo Gemini
  workout_service       fichas, versões, treino do dia, sessões, progressão conservadora
  gemini_service        cliente, saídas estruturadas (Pydantic), nova tentativa, uso de tokens
  ai_planner            prompts compactos + validação contra o catálogo local
  chat_service          ferramentas do chat, validação e confirmação
integrations/           exercisedb.py, wger.py, workoutdb.py (não disponível)
database/               models.py, connection.py; migrations/ (Alembic)
utils/units.py          Decimal, unidades, embalagens
tests/                  pytest
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

### Mercado: orçamento, leitura de produtos e temas

- **Orçamento:** o valor de Meu perfil é o fixo mensal; em Mercado › Gastos dá para definir outro valor para
  um mês específico (vazio volta ao fixo). Cada lista de compras tem o seu “quanto tenho para esta compra”,
  editável a qualquer momento, com o saldo “ainda posso gastar” e a sugestão dos itens mais caros a deixar
  para depois quando a projeção passa do valor.
- **Escanear produto:** o código de barras é lido localmente (zxing-cpp, EAN/UPC com dígito verificador). Se
  o produto não estiver cadastrado, só o código é consultado no [Open Food Facts](https://world.openfoodfacts.org)
  para trazer nome, marca e conteúdo. “Ler etiqueta com IA” é opcional, uma chamada ao Gemini por foto, e lê
  nome, conteúdo e preço da gôndola. Tudo aparece para conferência antes de salvar; o item pode entrar direto
  como comprado na lista da compra (ou numa compra avulsa, sem cardápio).
- **Temas:** três temas escuros por perfil. Os widgets nativos do Streamlit vêm do `config.toml`; o tema troca
  acento e superfícies por CSS, então tabelas (desenhadas em canvas) mantêm o tom escuro padrão.

### Prazo da meta de peso

Em Minha evolução, o FitOS calcula três cenários até a meta pelo balanço energético (≈7.700 kcal/kg):
**conservador** (0,5% do peso por semana), **mais rápido** (0,75%) e **intenso** (1%, limite superior usual);
para ganho, superávit de 200/350/500 kcal. As calorias nunca ficam abaixo do piso (gasto basal estimado ou
1.200/1.500 kcal) e a proteína sobe com o déficit. “Analisar com IA” faz uma chamada: a IA pode ajustar cada
cenário em até ±150 kcal, escolher de 3 a 6 refeições, recomendar um cenário e escrever a análise comparando
com a tendência registrada; o Python valida e recalcula prazos e macros. O cenário escolhido fica salvo e passa
a ser a meta de calorias, proteína e refeições do cardápio (local e IA), da despensa, do Painel e do chat. A tela
mostra a projeção, o peso esperado para hoje e pede recálculo após 4 semanas, mudança de meta ou de 3 kg.

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
  - Seis exercícios principais apontavam para GIFs removidos (404); `CORE_MEDIA_FROM` copia a mídia de
    uma entrada duplicada que funciona, sem trocar os IDs usados nas fichas.
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

### GroqCloud como alternativa automática

O Gemini continua como padrão. Se falhar (rede, cota, chave, resposta vazia ou inválida),
o FitOS tenta a GroqCloud, incluindo as ferramentas do chat e a validação dos planos.
Configure `GROQ_API_KEY` no `.env`; `GROQ_MODEL` define o modelo
(padrão: `qwen/qwen3.8-27b`). Reinicie o app após alterar o ambiente.
