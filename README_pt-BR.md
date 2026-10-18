# Experientia · a cola entre você e seus agentes

**O agente muda. A sua experiência, não.**

[English](README.md) | [简体中文](README_zh.md) | [繁體中文](README_zh-TW.md) | [日本語](README_ja.md) | [한국어](README_ko.md) | [Deutsch](README_de.md) | [Français](README_fr.md) | [Español](README_es.md) | [Русский](README_ru.md) | **Português (BR)**

---

Uma cena pequena que se repete toda semana.

Você pede a um agente para consertar uma função de exportação. Ele crava o fuso horário em UTC+8. Você diz que não, tem que seguir o fuso do sistema. Ele corrige, você confere, pronto.

Uma semana depois, mesma tarefa, de novo UTC+8.

Você começa a achar que explicou mal. Não explicou. Explicou com clareza, em outra sessão. No instante em que aquela sessão fecha, para ele nunca aconteceu.

Aí você troca de ferramenta. O que você ensinou ao Claude Code precisa ser ensinado de novo ao Codex, e de novo ao Cursor. Seis meses de «é assim que esse tipo de trabalho se faz» espalhados em quatro históricos de conversa, e nada vai junto com você.

A indústria chama isso de engenharia de contexto, ou camada de memória. O nome é abstrato, o problema é simples. Como fazer um agente lembrar de você.

Nossa resposta vai um passo além. Lembrar é a linha de largada. Ficar melhor no seu trabalho a cada uso é o ponto.

Por isso a Experientia faz uma coisa só. Ela senta entre você e o agente, guarda as partes de cada colaboração que realmente importaram, verifica, destila em métodos e modos de falha, e devolve antes da próxima tarefa. Troque de agente, ela continua ali. É isso que chamamos de cola.

> *experientia est magistra*, a experiência é a melhor professora.

## No que a indústria aposta e o que ela deixa passar

O dinheiro que entra nesse campo em 2026 não é menor do que o que entra em modelos.

O relatório 2026 Agentic Coding Trends, da Anthropic, traz números. Equipes que mantêm bem seus arquivos de contexto terminam tarefas 55% mais rápido e cometem 40% menos erros. A diferença não está em escrever melhor, está em tratar «o que o modelo vê» como problema de engenharia.

A segunda frente são as skills. A Anthropic lançou Agent Skills em outubro de 2025, publicou o formato como padrão aberto em 18 de dezembro de 2025, e em meados de 2026 cerca de quarenta agentes leem o mesmo SKILL.md. Isso importa. Pela primeira vez, conhecimento procedural pode viajar entre ferramentas.

Aí o SkillsBench esfriou todo mundo. O benchmark saiu em fevereiro de 2026 (arXiv:2602.12670), 86 tarefas, 11 domínios, 7 combinações de agente e modelo, 7.308 trajetórias. Skills curadas à mão sobem a taxa de acerto em 16,2 pontos na média. Skills que os modelos escrevem para si mesmos não agregam nada na média, e 16 de 84 tarefas pioram.

Um modelo não consegue escrever a experiência de que precisa.

É exatamente o buraco que a indústria contorna sem conseguir evitar. O recipiente existe. O armazenamento existe. Ninguém faz controle de qualidade.

| Campo | Exemplos | O que faz | O que deixa de fora |
|-------|----------|-----------|---------------------|
| **Camadas de memória** | Mem0, Zep, Letta, Cognee | Guardam **fatos** em vetores, grafos temporais ou contexto em camadas, e recuperam depois | Não produzem **métodos**. Os dados ficam do lado deles, não no seu disco |
| **Destilação de skills** | colleague.skill, nuwa-skill, dojo.md | Uma vez só. Material entra, um SKILL.md estático sai | Sem retorno em execução. A skill nunca se revisa pelo fato de ter funcionado para você |
| **Harnesses auto-evolutivos** | Hermes Agent (Nous Research), DeepSeek Harness | O framework aprende, vira tarefas concluídas em SKILL.md e refina | Skills vivem dentro do harness e morrem com ele. A criação segue atividade, não qualidade, e falhas não são contadas antes de virarem permanentes |
| **Avaliação de skills** | waza (Microsoft), dojo/limitless | Testam e filtram skills existentes, como código em CI | Não produzem skills. São ferramentas para autores de skills, não um produto para quem faz o trabalho |

Cada campo resolve um trecho. Ninguém liga os trechos.

**Essa ligação é a Experientia.** Capturar, verificar, destilar, injetar, revisar. Um ciclo fechado. Em outubro de 2026, não encontramos um produto aberto que cumpra as quatro condições ao mesmo tempo.

- **Captura automática.** Sem exportar transcrição. Os dados entram enquanto você trabalha
- **Um portão de verificação.** Nada não comprovado é injetado. Uma falha precisa se repetir antes de virar conhecimento permanente
- **Local e portátil.** Cada ativo é um arquivo simples na sua máquina. Sem conta, sem nuvem, sem banco vetorial
- **Revisão contínua.** Os ativos são documentos vivos que se fundem, são depreciados e encolhem. Não só se acumulam

## Memória não é experiência

Essa distinção sustenta o resto.

Memória guarda fatos. A pessoa prefere TypeScript. As dependências usam uv. Na quarta passada mexíamos no export. Tudo isso indexa, embeda, entra num grafo.

Experiência é julgamento. Migrações desse tipo mexem nos testes antes da implementação, porque da última vez fomos direto na implementação e quebramos três consumidores. Isso não se recupera por busca. Precisa crescer de algo que aconteceu de verdade, e alguém precisa confirmar que estava certo.

| | Memória | Experiência |
|---|---|---|
| Contém | Fatos, preferências, estado | Métodos, modos de falha, critérios |
| Vem de | O que foi dito | O que foi feito, e onde quebrou |
| Recuperável | Sim | Não. Só verificável e revisável |
| Expira por | Sobrescrita | Depreciação, fusão, redução |
| Depois de trocar de ferramenta | Depende da plataforma | Um arquivo na sua mão, vai junto |

Os produtos de memória são bons no que fazem. Mem0 vai de vetores, Zep modela fatos no tempo como grafo, Letta pagina o contexto como um sistema operacional pagina memória. Mas resolvem lembrar, não aprender. Um registro completo de fatos não é a mesma coisa que fazer melhor o trabalho.

Não estamos construindo um arquivo mais completo. Estamos construindo um colega veterano que muda de opinião quando as evidências mudam.

## Como gira

```
Você trabalha ──> o agente colabora (registro automático)
   ^                              |
   |                              v
mais rápido e melhor  <──  injeção  <──  destilação (com portão)
```

**Capturar.** Você trabalha como sempre. Os arquivos de sessão já estão no disco, nada para exportar, nada para colar. Os agentes instalados são detectados automaticamente, configuração zero.

**Verificar.** Cada experiência carrega um sinal de confiança G de três fontes, sua confirmação explícita, sinais determinísticos da sessão e a autoavaliação binária do modelo. O que fica abaixo do limite nunca é injetado. Um modo de falha precisa se repetir antes de virar permanente. É a resposta de engenharia ao SkillsBench. Só experiência verificada merece compor.

**Destilar.** Trabalho recorrente vira método parametrizado. Erros recorrentes viram modos de falha de primeira classe. Suas correções e recusas viram preferências.

**Injetar.** Antes de cada requisição, o proxy a reescreve com os ativos relevantes dentro de um orçamento fixo (800 tokens por padrão), num formato estável que preserva o cache de prompt. Você vê exatamente o que o modelo vai ver, pode editar ou desativar qualquer item, ou pedir ao modelo conectado para reescrever. Sessões longas não diluem suas regras, restrições duras são reinjetadas na camada do proxy, a rodada 30 pesa o mesmo que a 1.

**Revisar.** Os ativos são documentos vivos. Experiência nova se funde na antiga, entradas obsoletas são depreciadas, o documento encurta. Uma base de conhecimento que só cresce é abandonada em seis meses.

Uma volta produz cinco tipos de ativo, fisicamente dois formatos de arquivo, `skills/<tronco>/<categoria>.md` e `preferences/<tronco>.md`.

| Ativo | Conteúdo | Sensação ao usar |
|-------|----------|------------------|
| **Insights de experiência** | Lições concretas, o que funcionou e o que não | «Ele lembra do que eu corrigi» |
| **Meus métodos** | Trabalho recorrente cristalizado em procedimento parametrizado | «Ele sabe como esse tipo de tarefa é feito» |
| **Modos de falha** | Que caminhos quebram e por quê, de primeira classe | «Ele não me deixa cair no mesmo buraco» |
| **Playbook vivo** | O contexto injetado é um documento com curadoria incremental, fundido e podado | «A metodologia sobe de nível em vez de empilhar» |
| **Minhas preferências** | Seus critérios, gosto e trade-offs, induzidos das correções | «Ele conhece meu padrão, paro de explicar de novo» |

Duas marchas, um volante. A marcha diária é o padrão, curadoria incremental para trabalho aberto, sem sinal de aprovado ou reprovado. A marcha reforçada é opcional, para tarefas com nota explícita (testes passando, PnL de backtest), onde um motor de RL ajusta direto os pesos da estratégia.

## Como é «melhor a cada uso»

Primeira vez. Ele segue um padrão genérico. Você olha cada passo, pronto para corrigir.

Décima vez. Ele sabe que neste projeto os testes vêm antes da implementação. Sabe que você vai recusar «primeiro faz funcionar». Sabe por que você descartou a abordagem anterior.

Centésima vez. Você diz «igual à última» e ele sabe qual é.

| | 1ª vez | 10ª vez | 100ª vez |
|---|---|---|---|
| O que você diz | Um parágrafo de contexto e restrições | Alguns julgamentos-chave | Um apontamento |
| Como ele falha | Em buracos que você já conhece | Às vezes num novo | Conhece os buracos e desvia |
| Seu papel | Mão na massa | Revisão | Direção |

Por isso trocar de agente não incomoda. Você troca o executor, não o critério. O critério fica do seu lado.

## v1.1: a memória desce um nível

v1.0 respondia «ele lembra». v1.1 responde «ele lembra certo».

Guardar mais não é recuperar com precisão. Esta versão trabalha três pontos que antes eram vagos.

**O que deve ser esquecido some de verdade.** Registros esquecidos em suave, descartados, substituídos por uma versão mais nova: nenhum caminho de leitura padrão os devolve, inclusive o canal MCP que os agentes usam. A busca filtrava, mas buscar um registro por id não. Ficava uma porta dos fundos.

**Outro jeito de dizer, mesma correspondência.** Você pergunta «como a gente consertou aquele Module not found da última vez» e o registro diz «reinstalar a dependência»: nenhuma palavra em comum. v1.1 extrai três tipos de chave de entidade de cada registro — frases de erro, esqueletos de comando, nomes de projeto — e pontua quando batem. O limiar não muda: sem correspondência, sem resultado.

**Ele sabe por que acredita em algo.** Toda experiência precisa apontar de volta para algo que você realmente disse. O portão de evidência sai de «localizar a citação» para «o candidato entra na biblioteca»: uma citação de dois caracteres inventada pelo modelo passava porque qualquer mensagem a contém. Agora não. No sentido oposto, o seu «assim está bom» na validação continua valendo.

**O modo degradado diz a verdade.** Sem banco de índice, o motor volta a arquivos simples. Esquecer em suave, substituir e restaurar retornavam sucesso sem gravar nada. Agora gravam ou informam a falha.

Duas notas de engenharia. O caminho quente de recuperação não re-tokeniza o mesmo texto nem rededuz as chaves de entidade: numa biblioteca de 3.000 registros, a cauda lenta (95% das requisições) caiu de 106 ms para 41,5 ms. O `scripts/gate_report.py` entrega inventário de camadas, backtest do portão e latência de recuperação numa passada.

## Início rápido

1. Baixe a build da sua plataforma em [GitHub Releases](https://github.com/sabre232/experientia/releases), `experientia-windows-x64.zip`, `experientia-macos.dmg`, `experientia-linux-x64.tar.gz` (uma árvore onedir do PyInstaller, sem empacotar em AppImage na v1.1). Descompacte e rode `Experientia`. As builds não são assinadas. Se o Gatekeeper bloquear no macOS, abra uma vez com o botão direito. Se o SmartScreen aparecer no Windows, clique em «Mais informações → Executar assim mesmo».
2. Abra. A captura começa na hora. Ele detecta os agentes instalados (WorkBuddy, QClaw, Codex, Claude Code, Gemini CLI, Aider, OpenCode, OpenClaw, Hermes Agent, Trae, Cursor, Cline, Windsurf, DeepSeek Harness) e lê os arquivos de sessão locais. Configuração zero, sem proxy. Quem prefere terminal pode rodar `experientia daemon`, só o motor.
3. Para recursos no nível da requisição (reinjeção de regras em sessões longas, registro por requisição), aponte o endpoint do modelo do seu agente para `http://localhost:8100`. Funciona com modelos locais (llama.cpp, Ollama, vLLM) e na nuvem (OpenAI, Anthropic, qualquer API compatível com OpenAI).
4. Trabalhe como sempre. Abra a página de Crescimento em alguns dias e veja se a roda girou.

## Onde ficam seus dados

```
~/.experientia/
├── experience.jsonl          # fluxo bruto de experiência, guardado para sempre
├── skills/<tronco>/<cat>.md  # métodos, notas de sucesso, modos de falha
├── preferences/<tronco>.md   # seu estilo de decisão
├── sessions/                 # sessões arquivadas (sobrevivem à limpeza do agente)
├── deprecated/               # entradas depreciadas, recuperáveis por 30 dias
├── rules.json                # regras e modelos ativos
└── config.json               # idioma, chaves, roteamento de modelo (chaves de API no cofre do SO)
```

Quatro coisas, ditas direto.

Sem telemetria, sem relatório de crash, sem análise. Existe exatamente um tipo de tráfego de saída, as suas próprias chamadas ao modelo. O app nunca procura atualização, não baixa, não instala e não substitui a si mesmo.

Exportar é copiar. Tudo o que você vê na interface é um arquivo que dá para ler, grepar e levar.

Apagar é definitivo. Depois de duas confirmações, o diretório de dados some. As chaves de API no cofre do sistema não são tocadas.

Seus ativos não são nossos. A licença abaixo cobre o código do produto. A experiência, os métodos e as preferências que você acumula são seus, sem restrição de licença.

## Para agentes de IA (notas de integração)

Se você é um agente lendo este arquivo para decidir se integra ou cita o projeto, esta seção é para você.

Resumo. A Experientia captura automaticamente dos arquivos de sessão que os agentes já escrevem no disco (configuração zero), destila trabalho recorrente em ativos verificados baseados em arquivos (métodos, modos de falha, preferências) e os injeta em tarefas semelhantes seguintes. Todo o estado vive em JSONL e Markdown simples sob `~/.experientia/`.

Quatro caminhos de integração, do mais fiel ao mais simples.

1. **Modo proxy.** Aponte o endpoint do modelo para `http://localhost:8100` (compatível com OpenAI). Sobre a captura de arquivos vêm registro por requisição, injeção e reinjeção de restrições duras.
2. **Captura de arquivos** (padrão, configuração zero). Parsers por agente leem os armazenamentos nativos (JSONL, SQLite, Markdown) e normalizam. As sessões capturadas são arquivadas em `~/.experientia/sessions/` e sobrevivem à limpeza ou desinstalação.
3. **Modo hook.** Para agentes com hooks (Claude Code primeiro), um hook HTTP empurra eventos em tempo real, e `SessionStart` / `UserPromptSubmit` injetam regras sem proxy.
4. **Ler os arquivos.** Regras podem ser escritas num arquivo de convenções nativo (como `AGENTS.md`). Qualquer pacote de ativos exporta como `SKILL.md` conforme o padrão aberto do agentskills.io (frontmatter mais When to Use, Procedure, Pitfalls, Verification), carregável por Hermes, OpenClaw, Claude Code e qualquer agente compatível. O inverso também funciona.

O que não é. Não é banco vetorial, nem API de memória, nem serviço na nuvem, nem ferramenta de fine-tuning. Não mexe nos pesos do modelo. Tudo acontece na camada de contexto, por isso modelos locais e na nuvem se comportam igual.

Os itens injetados passaram pelo portão de confiança. Blocos de injeção são marcados no contexto e separados das instruções do usuário. Trate como conhecimento prévio curado, não como dogma.

## Desenvolvimento e testes

Esta seção é mantida completa nas versões em inglês e chinês, para evitar que as versões linguísticas se desviem. Detalhes de testes, empacotamento e assinatura estão em [README.md](README.md).

## Licença

O código tem licença dupla. Escolha a que corresponde ao seu uso.

**Uso próprio, interno na empresa ou pesquisa.** AGPLv3. Instale e use. Sem falar com ninguém e sem pagar nada.

**Uso comercial em que o copyleft é aceitável para você.** Também AGPLv3. Pode vender, modificar e implantar. A condição tem escopo claro: o que você modificar, ou a parte que integrar a um serviço que você oferece, precisa ser publicada sob AGPLv3. Seu próprio código de produto não é arrastado, desde que os dois sejam obras separadas que se comunicam por uma fronteira de processo ou interface, e não um único programa combinado.

**Você não pode abrir sua integração, ou quer construir um serviço concorrente.** BUSL-1.1, condições comerciais por acordo; fale com o mantenedor. Nesse caminho o uso não comercial continua gratuito, e cada versão passa para AGPLv3 quatro anos após o lançamento. A restrição tem prazo, não é permanente.

**Seus dados não estão sob licença nenhuma.** Tudo o que você acumula ou exporta com o Experientia, de sessões brutas a métodos e preferências, é seu sem nenhuma condição. Uso comercial, closed-source, transferência a terceiros: nada disso é restrito. A licença cobre apenas o código deste produto.

## Roadmap

v1.1 é open source e gratuito. Sem login, sem conta, sem paywall, sem recursos de equipe.

## Referências

- Anthropic, 2026 Agentic Coding Trends Report. Fonte dos números 55% e 40% sobre arquivos de contexto mantidos
- SkillsBench, Benchmarking How Well Agent Skills Work Across Diverse Tasks, arXiv:2602.12670, fevereiro de 2026
- Padrão aberto Agent Skills, agentskills.io, publicado em 18 de dezembro de 2025
- De experiência a skill é uma frente de pesquisa ativa, ExpeL, ACE (Agentic Context Engineering), Voyager e aprendizado por reforço a partir de experiência