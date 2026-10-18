# HomeDock

[![CI](https://github.com/LeandroGOLiv/home-dock/actions/workflows/ci.yml/badge.svg)](https://github.com/LeandroGOLiv/home-dock/actions/workflows/ci.yml)

HomeDock é um app para Windows que fica na **bandeja do sistema** (perto do relógio) e
controla dispositivos de casa inteligente **Tuya** diretamente pela **rede local**, sem
passar pela nuvem. Ele usa a biblioteca [tinytuya](https://github.com/jasonacox/tinytuya).

Na v1 o foco são as **lâmpadas RGB Wi-Fi da Positivo Casa Inteligente** (Tuya white label):

- liga/desliga, modo branco (temperatura de cor) e modo cor (matiz, saturação, brilho);
- grupos definidos por você (ex.: Sala, Quarto) — uma lâmpada pode estar em vários;
- cenas salvas (ex.: Leitura, Filme, Relaxar);
- flyout compacto no estilo Windows 11, que segue o tema claro/escuro e a cor de
  destaque do sistema;
- opção de iniciar com o Windows.

> **Status:** em desenvolvimento. O ícone na bandeja, o menu e o painel (flyout) com o
> seletor de alvo, os controles de modo, cor e brilho e as cenas já funcionam; o
> gerenciamento de grupos e lâmpadas ainda não — acompanhe as
> [issues](https://github.com/LeandroGOLiv/home-dock/issues) e milestones.

## Requisitos

- Windows 10 ou 11
- Python 3.12 ou superior
- [uv](https://docs.astral.sh/uv/) (gerenciador de projeto Python):
  `winget install astral-sh.uv`
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
4. No HomeDock, use **Recarregar dispositivos**.

### Adicionar ou resetar dispositivos

Não existe descoberta automática de dispositivos novos — o processo é manual:

1. Pareie o dispositivo no app do celular.
2. Rode o wizard de novo e copie o novo `devices.json` para `%APPDATA%\HomeDock\`.
3. Use **Recarregar dispositivos** no HomeDock.

Resetar ou parear de novo um dispositivo **troca a chave dele** e exige o mesmo processo.

### IPs vazios e IP fixo

Se o wizard rodar fora da rede de casa, os IPs no `devices.json` ficam vazios. Em casa,
complete-os com o `tinytuya scan` (detalhes em [docs/configuracao.md](docs/configuracao.md)).

**Recomendação:** reserve um IP fixo (reserva DHCP) para cada lâmpada no seu roteador.
Assim o IP não muda e o HomeDock não precisa redescobri-las.

## Uso

Rode `uv run homedock`. O HomeDock aparece como um ícone de lâmpada na bandeja (se não o
vir, procure na seta **^** ao lado do relógio). Abrir o app de novo não cria um segundo
ícone.

- **Clique esquerdo:** abre/fecha o painel, no canto da tela ao lado da bandeja. Ele fecha
  ao clicar fora dele ou com **Esc**. No topo, escolha **o que controlar**: "Todas as
  lâmpadas", um dos seus grupos ou uma lâmpada (com o status online/offline e os grupos
  de cada uma). O botão redondo ao lado liga/desliga **só o que está selecionado**; o
  HomeDock lembra a última escolha. **Gerenciar grupos e lâmpadas** ainda está em
  construção.
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
  clique fora fecham o menu. Por enquanto, **Iniciar com o Windows** só guarda a
  preferência; o registro no Windows chega junto com o `HomeDock.exe`.

O estado das lâmpadas é lido de novo toda vez que o menu ou o painel abre. Os comandos
nunca travam o app, mesmo com uma lâmpada fora da tomada.

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

```powershell
uv run pyinstaller packaging/HomeDock.spec
```

O executável fica em `dist\HomeDock.exe`. *(O spec de build é criado na issue de build.)*

## Licença

[MIT](LICENSE)
