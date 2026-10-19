# HomeDock

[![CI](https://github.com/LeandroGOLiv/home-dock/actions/workflows/ci.yml/badge.svg)](https://github.com/LeandroGOLiv/home-dock/actions/workflows/ci.yml)

HomeDock é um app para Windows que fica na **bandeja do sistema** (perto do relógio) e
controla dispositivos de casa inteligente **Tuya** diretamente pela **rede local**, sem
passar pela nuvem. Ele usa a biblioteca [tinytuya](https://github.com/jasonacox/tinytuya).

Na v1 o foco são as **lâmpadas RGB Wi-Fi da Positivo Casa Inteligente** (Tuya white label):

- liga/desliga, modo branco (temperatura de cor) e modo cor (matiz, saturação, brilho);
- grupos definidos por você (ex.: Sala, Quarto) — uma lâmpada pode estar em vários;
- cenas salvas (ex.: Leitura, Filme, Relaxar);
- flyout compacto no estilo Windows 11, que segue o modo do Windows (claro/escuro) e a
  cor de destaque, e se atualiza na hora quando você os troca;
- opção de iniciar com o Windows.

> **Status:** em desenvolvimento. O ícone na bandeja, o menu e o painel (flyout) com o
> seletor de alvo, os controles de modo, cor e brilho, as cenas, o gerenciamento de
> grupos e lâmpadas, a opção de iniciar com o Windows e o `HomeDock.exe` já funcionam —
> acompanhe as [issues](https://github.com/LeandroGOLiv/home-dock/issues) e milestones.

## Requisitos

- Windows 10 ou 11
- [uv](https://docs.astral.sh/uv/) (gerenciador de projeto Python):
  `winget install astral-sh.uv` — para rodar o wizard (uma vez), gerar o `HomeDock.exe`
  ou rodar o HomeDock a partir do código. O `HomeDock.exe` em si **não precisa de
  Python** instalado.
- Python 3.12 ou superior, só para rodar a partir do código (o uv instala se faltar)
- Lâmpadas já pareadas no app **Positivo Casa Inteligente** (ou Smart Life / Tuya Smart)
- O PC e as lâmpadas na **mesma rede Wi-Fi**

## Configuração (chaves dos dispositivos)

O HomeDock precisa da *local key* de cada dispositivo para falar com ele pela rede local.
Essas chaves são obtidas **uma vez** com o assistente do tinytuya (`tinytuya wizard`),
que consulta a sua conta de desenvolvedor Tuya. **O HomeDock em si nunca acessa a nuvem.**

O passo a passo completo — conta em platform.tuya.com, Cloud Project, vínculo da conta do
app por QR code, execução do wizard, onde guardar cada arquivo e como importar — está em
**[docs/configuracao.md](docs/configuracao.md)**.

Resumo:

1. Crie a conta e o Cloud Project em [platform.tuya.com](https://platform.tuya.com)
   (Data Center **Western America**) e vincule a conta do app pelo QR code.
2. Com o PC na mesma rede Wi-Fi das lâmpadas (rede marcada como **Privada** no Windows) e
   as lâmpadas ligadas, rode o wizard numa pasta **fora deste repositório**:
   `uv run --no-project --with tinytuya python -m tinytuya wizard`
3. Copie o `devices.json` gerado para `%APPDATA%\HomeDock\devices.json`.
4. No HomeDock, use **Gerenciar grupos e lâmpadas → Procurar lâmpadas novas**.

### Adicionar ou resetar dispositivos

O HomeDock não consegue cadastrar sozinho um dispositivo novo (a chave dele só vem do
wizard) — o processo é manual:

1. Pareie o dispositivo no app do celular.
2. Rode o wizard de novo e copie o novo `devices.json` para `%APPDATA%\HomeDock\`.
3. Use **Procurar lâmpadas novas** no HomeDock. Se ele achar na rede um dispositivo Tuya
   que não está no `devices.json`, avisa para rodar o wizard de novo.

Resetar ou parear de novo um dispositivo **troca a chave dele** e exige o mesmo processo.

### IPs vazios e IP fixo

Se o wizard rodar fora da rede de casa, os IPs no `devices.json` ficam vazios. Em casa,
use **Procurar lâmpadas novas**: o HomeDock procura as lâmpadas na rede e completa (ou
atualiza) os IPs sozinho (detalhes em [docs/configuracao.md](docs/configuracao.md)).

Se o roteador der outro IP a uma lâmpada, o HomeDock percebe sozinho na próxima vez que
falar com ela (ao iniciar, ao abrir o painel ou o menu, num comando): depois de algumas
tentativas sem resposta, ele procura as lâmpadas na rede e atualiza o IP no
`devices.json` (em menos de um minuto, sem você fazer nada).

**Recomendação:** reserve um IP fixo (reserva DHCP) para cada lâmpada no seu roteador.
Assim o IP não muda e o HomeDock não precisa redescobri-las.

## Uso

Abra o `HomeDock.exe` (veja [Gerar o HomeDock.exe](#gerar-o-homedockexe)) ou, a partir do
código, rode `uv run homedock`. O HomeDock aparece como um ícone de lâmpada na bandeja (se
não o vir, procure na seta **^** ao lado do relógio). Abrir o app de novo não cria um
segundo ícone.

- **Clique esquerdo:** abre/fecha o painel, no canto da tela ao lado da bandeja. Ele fecha
  ao clicar fora dele ou com **Esc**. No topo, escolha **o que controlar**: "Todas as
  lâmpadas", um dos seus grupos ou uma lâmpada (com o status online/offline e os grupos
  de cada uma). O botão redondo ao lado liga/desliga **só o que está selecionado**; o
  HomeDock lembra a última escolha.
- **Gerenciar grupos e lâmpadas** (no fim da lista do topo): mostra seus grupos (cômodos)
  com as lâmpadas de cada um e todas as lâmpadas, com o status (verde = respondendo).
  **+ Novo grupo** ou um clique num grupo abre **Editar grupo**: nome, lâmpadas do grupo
  (uma lâmpada pode estar em vários grupos; "também em …" mostra os outros), **Excluir
  grupo** (com **Desfazer** por alguns segundos) e **Salvar**; voltar sem salvar descarta
  as mudanças. "Todas as lâmpadas" é automático e sempre inclui todas. O lápis ao lado de
  uma lâmpada a renomeia (Enter salva, Esc cancela): o nome fica só no `config.json` do
  HomeDock — o `devices.json` não muda — e voltar ao nome original do app tira o apelido.
  **Procurar lâmpadas novas** lê o `devices.json` de novo e procura as lâmpadas na rede
  (leva uns 20 segundos, sem travar o painel) para completar ou atualizar os IPs; avisa se
  houver na rede um dispositivo Tuya que não está no `devices.json`.
- **Branco | Cor:** no modo **Branco**, arraste o marcador no arco para escolher de branco
  quente (esquerda) a frio (direita); no modo **Cor**, escolha a cor no anel e ajuste a
  **Saturação**. O **Brilho** vale para os dois modos. As lâmpadas mudam enquanto você
  arrasta. Num grupo, o painel mostra o estado da primeira lâmpada online e os comandos
  vão para todas as lâmpadas do grupo.
- **Cenas:** embaixo do painel. Clique numa cena para aplicá-la (modo, cor ou temperatura,
  brilho e liga/desliga de cada lâmpada). **+ Salvar atual** pede um nome e salva o estado
  das lâmpadas **do que está selecionado** no topo (Enter salva, Esc cancela). Clique
  direito numa cena (ou a tecla de menu): **Renomear**, **Sobrescrever com o estado
  atual** (troca a cena pelo estado atual do que está selecionado) ou **Excluir** —
  depois de excluir, **Desfazer** aparece por alguns segundos (e não some enquanto o
  mouse estiver em cima). Aparecem três cenas por vez, lado a lado; as outras rolam para
  o lado (roda do mouse ou a barrinha embaixo). Lâmpadas offline ficam de fora ao aplicar
  ou salvar, e um aviso discreto diz quantas. As cenas ficam salvas no `config.json` e o
  submenu **Cenas** da bandeja mostra a mesma lista.
- **Clique direito:** menu com **Abrir painel**, **Ligar todos**, **Desligar todos**, uma
  opção por lâmpada (marcada = acesa; "offline" quando ela não responde), **Cenas** (aplica
  uma cena salva), **Iniciar com o Windows** e **Sair**. Ao ligar/desligar uma lâmpada ou
  alternar **Iniciar com o Windows**, o menu continua aberto (com o mouse ou com Enter/
  espaço), para você mexer em várias lâmpadas seguidas; os outros itens, **Esc** ou um
  clique fora fecham o menu.
- **Iniciar com o Windows:** marcado, o Windows abre o HomeDock quando você entra na sua
  conta (sem pedir permissão de administrador). A marca mostra o que o Windows vai fazer
  de fato: ela some se você desativar o HomeDock em **Gerenciador de Tarefas → Aplicativos
  de inicialização** ou se mover o `HomeDock.exe` de pasta — marque de novo para o Windows
  abrir o exe no lugar novo. Desmarcar remove o HomeDock da inicialização.

O estado das lâmpadas é lido de novo toda vez que o menu ou o painel abre. Os comandos
nunca travam o app, mesmo com uma lâmpada fora da tomada: ela aparece como *offline* (no
seletor, no menu da bandeja e em **Gerenciar grupos e lâmpadas**) e o HomeDock continua
tentando sozinho — a cada poucos segundos no começo, depois a cada 30 segundos —, então
ela volta a aparecer online logo depois de ligada de novo.

## Segurança

Os arquivos gerados pelo wizard contêm **segredos**:

| Arquivo | Conteúdo sensível |
|---|---|
| `devices.json` | IDs, local keys e IPs dos dispositivos |
| `tinytuya.json` | Access ID / Access Secret da sua conta de desenvolvedor Tuya |
| `tuya-raw.json`, `snapshot.json` | dumps completos da conta e da rede |

- **Nunca** coloque esses arquivos dentro da pasta do repositório nem os publique.
- O HomeDock guarda dados **apenas** em `%APPDATA%\HomeDock\`.
- O repositório só contém o [`devices.example.json`](devices.example.json), com valores
  fictícios.
- Os logs do HomeDock mascaram chaves e credenciais.
- Quem tiver a local key de uma lâmpada consegue controlá-la na sua rede — trate-a como
  uma senha.

## Desenvolvimento

```powershell
uv sync                          # cria o .venv e instala as dependências
uv run pre-commit install --hook-type pre-commit --hook-type commit-msg
uv run homedock                  # roda o app
uv run pytest                    # testes
uv run ruff check .              # lint
uv run ruff format .             # formatação
```

### Gerar o HomeDock.exe

O `HomeDock.exe` não tem janela de console e roda em qualquer Windows 10/11 **sem Python
instalado**. Ele vem numa **pasta** `HomeDock\`, junto com a subpasta `_internal\` (as
bibliotecas que ele carrega): assim ele abre em menos de meio segundo, sem se descompactar
numa pasta temporária a cada execução. Para gerá-lo:

1. Na pasta do repositório, instale as dependências: `uv sync`.
2. Gere o executável (leva um ou dois minutos):

   ```powershell
   uv run pyinstaller packaging/HomeDock.spec
   ```

3. O resultado fica em `dist\HomeDock\` (cerca de 70 MB): o `HomeDock.exe`, com o ícone de
   lâmpada e a versão do HomeDock nas propriedades do arquivo (clique direito →
   Propriedades → Detalhes), e a pasta `_internal\`. As pastas `build\` e `dist\` não vão
   para o Git.
4. Copie a pasta `dist\HomeDock\` **inteira** para um lugar fixo, por exemplo
   `%LOCALAPPDATA%\Programs\HomeDock\`, e abra o `HomeDock.exe` de lá. O exe sozinho, sem a
   `_internal\` ao lado, não abre. Faça isso **antes** de marcar **Iniciar com o Windows**:
   a inicialização aponta para o lugar onde o exe está.
5. Na primeira vez, o Firewall do Windows pode pedir permissão para o HomeDock: permita em
   **redes privadas** (ele precisa ouvir a rede para achar as lâmpadas).

Para atualizar, saia do HomeDock (menu da bandeja → **Sair**), apague o conteúdo da pasta
onde ele está e copie o de `dist\HomeDock\` no lugar. Mantendo a mesma pasta, o **Iniciar
com o Windows** continua valendo.

O exe não leva nenhum dado seu: o `devices.json`, o `config.json` e os logs continuam em
`%APPDATA%\HomeDock\`, e o build para com erro se algum desses arquivos fosse entrar na
pasta. Para conferir o que foi empacotado, basta olhar `dist\HomeDock\_internal\`.

A primeira abertura depois de gerar ou copiar a pasta é mais lenta (uns 2 segundos): o
Windows (e o antivírus) ainda não leu esses arquivos.

### Medir o desempenho

`scripts/perf_probe.py` mede o que importa para o desempenho, sem mostrar chaves, IDs ou
IPs:

```powershell
uv run python scripts/perf_probe.py exe --minutes 2   # partida, RAM, CPU, threads, sockets
uv run python scripts/perf_probe.py flyout --profile  # abertura do painel (lâmpadas falsas)
uv run python scripts/perf_probe.py paint             # custo de pintura dos controles
uv run python scripts/perf_probe.py drag              # comandos enviados durante um arrasto
```

O `exe` abre o `dist\HomeDock\HomeDock.exe` algumas vezes (feche o seu HomeDock antes:
só um roda por vez), mede o tempo até o ícone aparecer na bandeja e depois deixa o app
parado na bandeja, medindo memória e CPU. Ele usa os seus dados em `%APPDATA%\HomeDock\`
e lê o estado das lâmpadas reais ao abrir, sem enviar comandos; no fim, encerra o
processo (o ícone pode ficar na bandeja até você passar o mouse sobre ele). Os outros
rodam o painel dentro do próprio script, com lâmpadas falsas.

## Licença

[MIT](LICENSE)
