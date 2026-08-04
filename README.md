# Ecossistema Serverless de Escala com Apache OpenWhisk

Este diretório contém a especificação arquitetural, infraestrutura em conteineres, implementações de funções multilinguagem, infraestrutura como código (IaC) e o manual operacional completo de uma plataforma FaaS (Function-as-a-Service) corporativa baseada no **Apache OpenWhisk**.

---

## 1. Arquitetura do Sistema e Fluxo de Execução

O Apache OpenWhisk é um motor serverless distribuído e orientado a eventos de alto desempenho. Abaixo, detalhamos o ciclo de vida completo de uma requisição HTTP ou evento desde sua entrada até a resposta.

### 1.1 Diagrama de Fluxo de Execução (ASCII)

```text
  [ Chamada HTTP / Evento Externo ]
                 |
                 v
        +------------------+
        |  NGINX Reverse   | (SSL, Terminação TLS, Roteamento API Gateway)
        |  Proxy / Gateway |
        +------------------+
                 |
                 v (Porta 443 -> /api/v1/...)
        +------------------+
        |    Controller    | (Orquestração, Auth, Validação de Cota e Limites)
        +------------------+
           |            ^
           | (Consulta) | (Verificação de Credenciais e Metadados das Actions)
           v            |
     +-----------+  +-----------+
     |  CouchDB  |  |  CouchDB  |
     | (Entidades|  | (Sujeito /|
     |  & Rules) |  |   Auth)   |
     +-----------+  +-----------+
           |
           v (Publicação de Mensagem com Payload e Activation ID)
     +--------------------------------------------------------------+
     |                    Apache Kafka (Topic: invokerX)            |
     +--------------------------------------------------------------+
                                    |
                                    v (Mensagem Consumida pelo Invoker Elegível)
                     +-------------------------------+
                     |            Invoker            |
                     +-------------------------------+
                       | (Gerenciamento de Lifecycle de Containers)
                       v
         +---------------------------------------+
         | Docker / Kubernetes Container Pool    |
         |                                       |
         |  [ Container Warm (Reusado) ]        |
         |               ou                      |
         |  [ Container Cold (Inicializado) ]    |
         +---------------------------------------+
                       |
                       v (Executa a Função via HTTP POST /run no Runtime)
         +---------------------------------------+
         |     Action Runtime (Go/Python/Node)   |
         +---------------------------------------+
                       |
                       v (Retorna Resultado de Execução)
         +---------------------------------------+
         | CouchDB Activation Record (Persistido)|
         +---------------------------------------+
```

### 1.2 Detalhamento do Fluxo de Vida de uma Requisição

1. **Entrada do Evento (NGINX/Gateway)**: Uma requisição HTTP chega ao NGINX (atuando como API Gateway). O NGINX verifica o roteamento e direciona a chamada para o **Controller**.
2. **Processamento no Controller**: O Controller é o cérebro do OpenWhisk. Ele:
   - Valida o token de autenticação (`AUTH_KEY`) consultando a base de dados de sujeitos no **CouchDB**.
   - Carrega a definição da Action correspondente (metadados, código, limites de memória/timeout) do CouchDB.
   - Verifica se a taxa de requisições está dentro do limite configurado (Rate Limiting).
3. **Roteamento e Enfileiramento (Kafka)**: O Controller escolhe o melhor **Invoker** (baseado no estado de carga e afinidade de containers frios/quentes) e publica um evento de ativação no **Kafka**, sob o tópico correspondente àquele Invoker (ex: `invoker0`). O Kafka garante entrega robusta e resiliente do job de execução.
4. **Execução no Invoker**: O Invoker correspondente escuta o tópico do Kafka, extrai o payload e gerencia o pool de containers:
   - **Cold Start**: Se não houver um container ocioso para a imagem runtime da Action, o Invoker inicializa um novo container (`docker run`). Em seguida, ele injeta o código da função no container usando a API `/init` exposta pelo runtime do container.
   - **Warm Start**: Se já houver um container aquecido ocioso (criado em ativações anteriores da mesma ação), o Invoker reutiliza-o diretamente, mitigando a latência de inicialização do Docker.
   - **Execução**: O Invoker aciona o endpoint `/run` do container, passando os argumentos JSON em tempo de execução.
5. **Persistência de Resultados e logs**: O container processa a lógica de negócio e responde um JSON. O Invoker captura o resultado e os logs (`stdout`/`stderr`), destrói ou devolve o container para o pool como ocioso (Warm), e grava o registro de ativação (`Activation Record`) de forma assíncrona no CouchDB. O Controller retorna o resultado se a chamada original foi síncrona (`blocking=true`).

### 1.3 Conceitos Fundamentais

* **Actions**: Funções puras sem estado (stateless) que executam um bloco de código estruturado. Aceitam um objeto JSON como parâmetro e retornam um JSON. Podem ser escritas em várias linguagens (Go, Python, Node.js, Java, Rust, Swift) ou empacotadas em qualquer Docker runtime customizado.
* **Triggers**: Canais nomeados de eventos. Eles são disparados por agentes externos (como webhooks, commits em git, logs de auditoria) ou agendadores temporais (cron jobs).
* **Rules**: Mapeamentos lógicos de N-para-N que ligam **Triggers** a **Actions**. Quando um Trigger é acionado, a regra dispara automaticamente a execução da Action ou Sequence associada.
* **Packages**: Agrupamentos lógicos de Actions, Feeds e parâmetros padrão. Permite reutilização, governança corporativa e compartilhamento de integrações (ex: `whisk.system/alarms`).
* **Feeds**: Um Feed é um Trigger especializado que configura dinamicamente um produtor externo de eventos (como conectar-se a uma fila Kafka ou registrar um listener em um banco de dados).
* **Sequence Actions**: Mecanismo nativo de composição serverless para encadear múltiplas Actions de forma sequencial (`Action A -> Action B -> Action C`). A saída JSON da primeira função serve de entrada JSON para a próxima, permitindo pipeline de processamento sem acoplamento.

---

## 2. Infraestrutura e Deployment (`docker-compose.yml`)

Nossa arquitetura de infraestrutura distribui os componentes fundamentais em uma rede de containers Docker dedicada para permitir simulação local de alta fidelidade produtiva.

### 2.1 Componentes da Pilha
* **CouchDB (Porta 5984)**: Armazém transacional de persistência. Contém os metadados das ações criadas, credenciais e os logs/resultados de execução de todas as ativações.
* **ZooKeeper (Porta 2181)**: Coordenação de estado distribuído para o cluster Apache Kafka.
* **Apache Kafka (Porta 9092)**: Barramento de mensagens de altíssima vazão que enfileira os jobs de ativações para os Invokers correspondentes de forma resiliente.
* **OpenWhisk Controller (Portas 8888/8080)**: Camada de API administrativa e controle de fluxo do cluster.
* **OpenWhisk Invoker (Porta 8085)**: Agente supervisor local encarregado de orquestrar a execução física de containers das Actions por meio de requisições de API na rede Docker.
* **NGINX (Porta 80 e 443)**: API Gateway principal, servindo SSL auto-assinado e fazendo proxy reverso seguro para o Controller do OpenWhisk.

---

## 3. Implementação de Actions Multilinguagem

Para exemplificar o pipeline de processamento serverless, desenvolvemos duas funções otimizadas (Go e Python) que funcionam perfeitamente de forma isolada ou encadeadas através de uma **Sequence Action**.

### 3.1 Go Action (`main.go`)
Focado em alta performance, validação estruturada de parâmetros, tipagem estática robusta e cálculo criptográfico de hashes MD5/SHA256 para auditoria de payloads de arquivos ou textos.

### 3.2 Python Action (`main.py`)
Responsável por manipulações de string e enriquecimento dinâmico. Ela pega os metadados gerados pela Go Action e os consome junto a uma API externa fictícia de enriquecimento, adicionando timestamps de auditoria e normalizando caracteres.

### 3.3 Sequence Action (`Go Action -> Python Action`)
Cria um pipeline integrado de ponta a ponta sem qualquer código extra de integração:
1. `Go Action` recebe e limpa o JSON original, calcula os hashes criptográficos e extrai metadados do payload.
2. O resultado da `Go Action` é enviado diretamente como entrada da `Python Action`.
3. `Python Action` enriquece os metadados com um provedor externo e finaliza o payload estruturado.

---

## 4. Automação e Infraestrutura como Código (`manifest.yaml`)

Utilizamos o padrão declarativo do `wskdeploy` para provisionar toda a infraestrutura serverless através de código (`manifest.yaml`).

O manifesto configura:
* O pacote (`Package`) corporativo denominado `data-pipeline`.
* Variáveis de ambiente padrão aplicadas a todas as funções de forma global.
* Duas Actions principais (`validate-hash` e `enrich-metadata`) configuradas com restrições rígidas de consumo de recursos:
  - **Memory Limits**: 128 MB (Go) e 256 MB (Python) para evitar vazamento de memória e sobrecarga financeira.
  - **Timeouts**: Máximo de 15 segundos para assegurar término rápido de processos ineficientes.
* Um Trigger do tipo cron-job (`every-minute-trigger`) parametrizado para simular chamadas de tempo a cada 60 segundos.
* Uma regra (`Rule`) chamada `execute-pipeline-rule` conectando o trigger diretamente ao pipeline sequencial.

---

## 5. Guia de Comandos CLI (`wsk`) e Playbook Operacional

Este playbook é o guia definitivo para operadores e desenvolvedores realizarem manutenções e verificações locais no ecossistema FaaS.

### 5.1 Configuração e Autenticação

Para se conectar à instância local do OpenWhisk protegida pelo NGINX Gateway:

```bash
# Definir o endereço IP do host API do OpenWhisk
wsk property set --apihost "https://localhost"

# Configurar as credenciais de autenticação administrativa (obtidas do .env)
wsk property set --auth "23bc46b1-71f6-4ed5-8c54-816aa4f8c502:123zO3xZCLrMN6v2BKK1dQMUIg3Yxuv31623G7vS3Ym6e159yG"

# Validar conexão listando os recursos disponíveis
wsk list -i
```
> **Nota**: O parâmetro `-i` (ou `--insecure`) ignora o certificado auto-assinado local do NGINX de desenvolvimento.

### 5.2 Criação e Atualização de Recursos

**Criar/Atualizar um Pacote:**
```bash
wsk package create data-pipeline -i
wsk package update data-pipeline --shared yes -i
```

**Criar/Atualizar uma Action em Go:**
```bash
wsk action update data-pipeline/validate-hash ./actions/go/validate-hash.zip --docker openwhisk/action-golang-v1.17 -i
```

**Criar/Atualizar uma Action em Python:**
```bash
wsk action update data-pipeline/enrich-metadata ./actions/python/main.py --kind python:3 -i
```

**Criar uma Sequence Action (Encadeamento):**
```bash
wsk action update data-pipeline/data-sequence-pipeline --sequence data-pipeline/validate-hash,data-pipeline/enrich-metadata -i
```

### 5.3 Execução e Testes de Ativação

**Invocação Síncrona (Blocking) - Bloqueia o terminal até a resposta do container:**
```bash
wsk action invoke data-pipeline/data-sequence-pipeline \
  --param payload "Texto ultra secreto do payload corporativo para processar" \
  --param file_name "documento_confidencial_001.pdf" \
  --blocking --result -i
```

**Invocação Assíncrona (Non-Blocking) - Retorna um Activation ID imediatamente:**
```bash
wsk action invoke data-pipeline/data-sequence-pipeline \
  --param payload "Outro dado em lote" \
  --param file_name "lote_99.csv" -i
```
*Saída de exemplo:*
```text
ok: invoked data-pipeline/data-sequence-pipeline with id c9d8e7b6a5144f8288e7b6a5144f8202
```

### 5.4 Inspeção de Ativações e Logs

**Listar todas as ativações recentes:**
```bash
wsk activation list -i
```

**Obter os logs detalhados (stdout/stderr) de uma ativação específica pelo ID:**
```bash
wsk activation logs c9d8e7b6a5144f8288e7b6a5144f8202 -i
```

**Obter o resultado JSON de retorno de uma ativação específica pelo ID:**
```bash
wsk activation result c9d8e7b6a5144f8288e7b6a5144f8202 -i
```

**Verificar a definição completa da ativação, incluindo latência, warm/cold start e metadados de execução:**
```bash
wsk activation get c9d8e7b6a5144f8288e7b6a5144f8202 -i
```

---
*Projetado por Jules - Arquiteto de Software Sênior e Especialista em Plataformas de Escala Serverless.*
