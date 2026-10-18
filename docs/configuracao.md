# Guia de configuração do HomeDock

Este guia explica como obter as chaves dos seus dispositivos Tuya, onde guardar cada
arquivo e como manter tudo funcionando quando você adicionar ou trocar dispositivos.

> **Por que isso é necessário?** O HomeDock fala com as lâmpadas direto pela rede local,
> e cada dispositivo Tuya exige uma *local key* para isso. Essa chave só pode ser obtida
> pela nuvem da Tuya — por isso usamos o assistente do tinytuya **uma vez**, fora do
> HomeDock. O HomeDock em si nunca acessa a nuvem.

## Onde fica cada arquivo

| Pasta | O que guarda |
|---|---|
| `%USERPROFILE%\tuya-wizard\` | Pasta de trabalho do wizard: `devices.json`, `tinytuya.json` (Access ID/Secret da sua conta Tuya), `tuya-raw.json`, `snapshot.json`. |
| `%APPDATA%\HomeDock\` | Dados do HomeDock: `devices.json` importado, configuração (nomes, grupos, cenas), logs. |
| Pasta do repositório | **Nada sensível.** Só o `devices.example.json` com valores fictícios. |

Para abrir essas pastas, cole o caminho na barra de endereço do Explorador de Arquivos
(ex.: `%APPDATA%\HomeDock`).

> ⚠️ Nunca coloque esses arquivos dentro da pasta do repositório nem os envie a ninguém.
> Quem tiver a local key de uma lâmpada consegue controlá-la na sua rede, e o
> `tinytuya.json` dá acesso à sua conta de desenvolvedor Tuya.

## 1. Pré-requisitos

- Lâmpadas pareadas no app **Positivo Casa Inteligente** (ou Smart Life / Tuya Smart).
- [uv](https://docs.astral.sh/uv/) instalado: `winget install astral-sh.uv`.
- PC e lâmpadas na **mesma rede Wi-Fi**.
- A rede Wi-Fi marcada como **Privada** no Windows
  (Configurações → Rede e Internet → Wi-Fi → *sua rede* → Tipo de perfil de rede →
  Privada). Em rede Pública o firewall bloqueia a descoberta dos dispositivos.

## 2. Criar a conta e o Cloud Project na Tuya

1. Crie uma conta em [platform.tuya.com](https://platform.tuya.com) (é gratuita).
2. Vá em **Cloud → Development → Create Cloud Project**:
   - *Industry*: Smart Home
   - *Development Method*: Smart Home
   - *Data Center*: **Western America** (é o data center das contas brasileiras do app)
3. Na tela de serviços de API, mantenha os serviços sugeridos e confirme.
4. Na aba **Overview** do projeto, anote o **Access ID / Client ID** e o
   **Access Secret / Client Secret**.

## 3. Vincular a conta do app (QR code)

1. No projeto, abra a aba **Devices → Link App Account → Add App Account**.
2. Aparece um QR code. No app do celular, vá em **Eu / Perfil** e toque no ícone de
   **escanear** (canto superior), e leia o QR code.
3. Confirme o vínculo (vínculo automático, permissões de leitura e controle).
4. Os dispositivos da sua conta passam a aparecer na aba **Devices** do projeto. Anote o
   ID de qualquer um deles (o wizard pede um).

## 4. Rodar o wizard

Com as lâmpadas **energizadas** e o PC na mesma rede Wi-Fi (rede Privada):

```powershell
mkdir $env:USERPROFILE\tuya-wizard -Force
cd $env:USERPROFILE\tuya-wizard
uv run --no-project --with tinytuya python -m tinytuya wizard
```

Responda:

- **API Key / Access ID** e **API Secret / Access Secret**: os valores do passo 2.
- **Any Device ID**: o ID anotado no passo 3.
- **Region**: `us` (Western America).
- **Poll local devices?**: `Y` — assim ele descobre os IPs e a versão de protocolo.

Se o Windows perguntar sobre o firewall, permita o Python em **redes privadas**.

O wizard cria na pasta `tuya-wizard` os arquivos `devices.json`, `tinytuya.json`,
`tuya-raw.json` e `snapshot.json`.

## 5. Importar no HomeDock

1. Copie `%USERPROFILE%\tuya-wizard\devices.json` para `%APPDATA%\HomeDock\devices.json`
   (crie a pasta `HomeDock` se não existir).
2. No HomeDock, abra **Gerenciar grupos e lâmpadas → Procurar lâmpadas novas**. O
   HomeDock lê o `devices.json` de novo e procura as lâmpadas na rede (uns 20 segundos)
   para completar ou atualizar os IPs. Na primeira vez, se o Windows perguntar sobre o
   firewall, permita o HomeDock (ou o Python) em **redes privadas**: a procura usa as
   portas UDP 6666, 6667 e 7000 para ouvir os avisos que as lâmpadas mandam na rede e
   nunca se conecta a elas.

## Testar a conexão (opcional)

Para conferir se o HomeDock consegue falar com cada lâmpada, rode na pasta do projeto:

```powershell
uv run python scripts/diagnose.py --dry-run
```

Ele só **lê** o estado de cada lâmpada (IDs e IPs aparecem mascarados). Sem `--dry-run`,
o script também testa liga/desliga, modo branco, cores e brilho — as lâmpadas piscam e
mudam de cor por cerca de 1 minuto cada — e no fim volta cada uma ao estado em que estava.
Use `--only 1` para testar só a primeira lâmpada e `--tests power` para um teste só.

## IPs vazios

Se o wizard rodar fora da rede de casa (ou sem o *poll*), o campo `ip` de cada
dispositivo fica vazio. Opções, quando estiver em casa:

- **Mais simples:** rode o wizard de novo em casa (passo 4) e importe de novo (passo 5).
- **Procurar lâmpadas novas** no HomeDock também procura as lâmpadas na rede e completa
  (ou atualiza) os IPs no `devices.json` — só o campo `ip` (e a versão de protocolo, quando
  estiver vazia); o resto do arquivo fica igual.
- **Manual:** em `%USERPROFILE%\tuya-wizard`, rode
  `uv run --no-project --with tinytuya python -m tinytuya scan`, que lista o IP e o ID de
  cada dispositivo encontrado, e preencha o campo `ip` correspondente no `devices.json`.

### Recomendação: IP fixo

Reserve um IP fixo para cada lâmpada no seu roteador (**reserva DHCP**, normalmente em
*LAN / DHCP / Endereços reservados*, usando o MAC da lâmpada). Assim o IP nunca muda e o
HomeDock não precisa redescobrir a lâmpada.

Sem IP fixo, o HomeDock também se vira: quando uma lâmpada deixa de responder algumas
vezes seguidas, ele procura as lâmpadas na rede (no máximo uma vez a cada 5 minutos) e,
se o IP dela mudou, atualiza o campo `ip` no `devices.json` e volta a controlá-la no
endereço novo.

## Adicionar um dispositivo novo

O HomeDock não consegue cadastrar sozinho um dispositivo novo (a chave dele só vem do
wizard) — o processo é manual:

1. Pareie o dispositivo no app do celular.
2. Rode o wizard de novo (passo 4) — as credenciais já ficam salvas no `tinytuya.json`.
3. Importe o novo `devices.json` (passo 5).

Se **Procurar lâmpadas novas** encontrar na rede um dispositivo Tuya que não está no
`devices.json`, o HomeDock avisa que é preciso rodar o wizard de novo.

## Resetar ou parear de novo um dispositivo

Resetar ou parear de novo um dispositivo **gera uma nova local key**. A chave antiga para
de funcionar, então repita os passos de "Adicionar um dispositivo novo".

## Comportamento após queda de energia

Desligar pelo HomeDock (ou pelo app) mantém a cor, o modo e o brilho: ao religar, a
lâmpada volta como estava. Já quando a **energia é cortada** (interruptor da parede, queda
de luz), quem decide como ela volta é a configuração da própria lâmpada, ajustada no app
do celular (nas configurações do dispositivo, opções como *memória ao desligar* /
*comportamento ao ligar* e *não perturbe*). O HomeDock não altera essas opções.

## Arquivos do HomeDock em `%APPDATA%\HomeDock`

| Arquivo | Para que serve |
|---|---|
| `devices.json` | Cópia do arquivo do wizard. O HomeDock só lê — exceto os IPs (e uma versão de protocolo vazia), que **Procurar lâmpadas novas** atualiza com o que achou na rede. Renomear uma lâmpada não muda este arquivo. |
| `config.json` | Nomes que você deu às lâmpadas, grupos, cenas e preferências (iniciar com o Windows, último alvo selecionado). Criado na primeira execução. |
| `logs\homedock.log` | Registro de funcionamento, útil para diagnosticar problemas. Gira automaticamente (até 4 arquivos de 1 MB). |

- O `config.json` é sempre gravado de forma segura (arquivo temporário + troca), então
  uma queda de energia durante a gravação não deixa o arquivo pela metade.
- Se o `config.json` estiver corrompido ou ilegível, o HomeDock **não fecha**: ele renomeia
  o arquivo para `config.corrupt-<data>-<hora>.json` (para você não perder nada) e começa
  de novo com a configuração padrão.
- Os logs **nunca** mostram local keys, IDs completos de dispositivos ou IPs: eles
  aparecem mascarados (ex.: `bf…9c`, `19…10`). Mesmo assim, prefira não publicar logs.

## Problemas comuns

| Sintoma | O que verificar |
|---|---|
| Wizard não encontra dispositivos / IPs vazios | Rede marcada como Privada? Lâmpadas energizadas? PC na mesma rede? Firewall liberado para o Python em redes privadas? |
| Lâmpada aparece *offline* no HomeDock | Ela está energizada? Ao religá-la, ela volta a aparecer online sozinha em até ~30 s. Se o IP mudou, o HomeDock a procura na rede sozinho em menos de um minuto (ou use **Procurar lâmpadas novas**); reserve IP fixo para evitar. |
| "Não foi possível procurar na rede" | Outro programa (ex.: um `tinytuya scan` aberto) está usando as portas UDP 6666/6667/7000, ou o firewall bloqueou o HomeDock. Feche o outro programa e tente de novo. |
| Erro de chave / dispositivo não responde após reset | A local key mudou — rode o wizard de novo e reimporte. |
| Wizard reclama de credenciais | Confira Access ID/Secret e o Data Center (Western America → região `us`). |
| Grupos/cenas sumiram e apareceu um `config.corrupt-….json` | O `config.json` estava corrompido. Seus dados continuam no arquivo `config.corrupt-…` (não o publique: ele contém IDs dos dispositivos). |
