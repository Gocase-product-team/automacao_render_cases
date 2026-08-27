# Automação de render de mockups

Aplica materiais, renderiza e salva nas pastas seguindo o padrão de
nomenclatura do acervo. Substitui o ciclo manual de trocar material →
renderizar → salvar → repetir, dentro do Blender.

Um lote de 4 cores de capinha × 4 cores de corpo × 4 câmeras — 80 imagens
mais 4 máscaras — sai em torno de 22 minutos sem intervenção.

## Requisitos

- Windows
- Blender 4.3 ou superior (testado no 4.5.4 LTS)
- Python 3.9+

**Nenhuma dependência de `pip`.** A interface usa só a biblioteca padrão.

## Como usar

Existem duas interfaces, com o mesmo motor por baixo. Escolha uma:

| | Atalho | Comando |
|---|---|---|
| **Web** (recomendada) | `Render de lote (web).bat` | `python automacao/servidor.py` |
| Desktop (Tkinter) | `Render de lote.bat` | `python automacao/app.py` |

A versão web sobe um servidor em `127.0.0.1` numa porta livre e abre o
navegador. **Nada sai da máquina** — o endereço de loopback não é
alcançável de fora, e não há conta, internet nem hospedagem envolvidas.
Ao fechar a aba, o servidor se desliga sozinho.

A versão Tkinter continua funcionando e faz exatamente o mesmo. Fica como
plano B.

Fluxo de um projeto novo:

1. **Projeto** — aponte o `.blend`, a pasta raiz de saída e o template.
   Clique em `Inspecionar o .blend`.
2. **Peças e variações** — crie as peças, dê nome a elas e arraste os
   materiais da lista para as células da grade.
3. **Câmeras e máscara** — marque as câmeras do lote, dê o rótulo de cada
   uma e marque os objetos que compõem a máscara.
4. **Render** — escolha as variações, confira e renderize.

`Salvar` guarda tudo em `automacao/projetos/<nome>.json`, e `Abrir`
recarrega já reinspecionando o arquivo.

## Arquitetura

Quatro peças, com o núcleo separado da interface:

| Arquivo | Onde roda | O que faz |
|---|---|---|
| `automacao/inspecionar.py` | dentro do Blender | lê a estrutura do `.blend` e devolve JSON |
| `automacao/render.py` | dentro do Blender | executa uma fila de renders |
| `automacao/nucleo.py` | Python do sistema | mapeia peças, monta a fila, valida |
| `automacao/servidor.py` | Python do sistema | backend da interface web |
| `automacao/web/index.html` | navegador | a interface web |
| `automacao/app.py` | Python do sistema | a interface Tkinter |
| `automacao/dialogo.py` | Python do sistema | diálogo nativo de escolher arquivo |

Nenhuma interface **importa `bpy`** — todas conversam com o Blender por
subprocesso. Por isso você pode ter o Blender aberto ao mesmo tempo, e um
render travado não derruba a janela.

As duas interfaces são camadas finas sobre o mesmo `nucleo.py`, que é
onde está toda a lógica. O progresso do lote chega na web por Server-Sent
Events, lendo a saída do Blender linha por linha.

O `dialogo.py` existe porque o navegador não entrega caminho de sistema
para o backend, por segurança. Quando você clica no `…` de um campo de
caminho, o servidor abre um diálogo nativo num processo curto e devolve o
que você escolheu. Se isso falhar por qualquer motivo, os campos aceitam
caminho colado à mão.

**O `.blend` nunca é salvo.** Todas as trocas de material acontecem em
memória e são descartadas quando o Blender sai.

## O modelo de peças

Uma variação de cor é um **conjunto ordenado** de materiais, não um
material solto. As colunas da grade são as peças; as linhas são as
variações.

```
                     corpo          frame          logo
SLIM GUARD ACAI      case acai      frame acai     magsafe acai
SLIM GUARD AZUL      case azul      frame azul     magsafe azul
SLIM GUARD CLEAR     case transp.   frame transp.  magsafe transp.
```

Para aplicar uma variação, o script lê o material que está em cada slot,
descobre em qual coluna ele aparece, e escreve o material da mesma coluna
na linha escolhida. Consequências:

- Nenhum índice de slot no config, nenhum padrão de nome de material —
  funciona com nomes ruins tipo `Material.007`.
- O `.blend` pode estar salvo em qualquer cor.
- Um material que ocupa vários slots é trocado em todos de uma vez.
- Célula vazia (`—`) não altera aquele slot, então variações podem ter
  quantidades diferentes de peças preenchidas.
- Um mesmo material **não pode** estar em duas colunas do mesmo grupo —
  ficaria ambíguo de qual peça ele é. O botão `Conferir` avisa.

Objetos ocultos no render e objetos em coleção oculta ficam de fora do
mapeamento. É o que impede a automação de reescrever os cubos de swatch
que só existem para segurar os materiais.

## A lista de materiais

Cada material aparece com um quadradinho da sua cor principal. A cor é
extraída no lado do Blender com uma regra que respeita o setup dos
arquivos: nos plásticos translúcidos a cor visível **não** está no Base
Color (que é branco) e sim no nó de Volume Absorption, então a absorção
tem prioridade quando a transmissão está ligada.

Um quadradinho **xadrez** significa material regido por textura, sem cor
única — é o caso dos materiais de lente e flash.

## Grupos

- **Capinha** — o nome da variação vira o nome da pasta (`{capinha}`).
- **Corpo** — o número da variação vira o nome do arquivo (`{numero}`).

O número é campo editável, preenchido automaticamente pela ordem das
linhas com o botão `renumerar`. Isso cobre tanto `02..06` quanto
sequências que começam em outro valor, porque no acervo o número é um
código de cor e não um contador.

## Saída

Template com marcadores, montado sobre a pasta raiz:

```
{aparelho}/{capinha}/{camera}/{numero}.png
```

| Marcador | De onde vem |
|---|---|
| `{capinha}` | nome da variação de capinha |
| `{camera}` | rótulo da câmera |
| `{numero}` | número da variação de corpo |
| `{aparelho}`, `{linha}` | campos digitados na aba Projeto |

## Máscara

A máscara é geometria pura, idêntica em todas as cores de capinha. Então
é renderizada **uma vez por câmera** com poucos samples, e copiada para
as outras pastas de capinha depois do lote.

Na aba `Câmeras e máscara` você marca quais objetos aparecem nela — o
resto é escondido durante aquele render.

## Câmeras

Aparecem com o nome que têm no `.blend`, com um checkbox para entrar ou
não no lote e um campo de texto para o rótulo que vira pasta. A ordem dos
rótulos é sua: `Camera.003` não precisa ser a `POS 4`.

## Monitor de dispositivo (só na web)

Acima da barra de progresso há um gráfico ao vivo do dispositivo que está
renderizando, atualizado a cada segundo, com 60 segundos de histórico.

A fonte não é fixa. O `.blend` guarda apenas `GPU` ou `CPU` — **qual**
placa e qual backend não estão nele, vêm das preferências do Blender e do
hardware. Então a inspeção enumera os dispositivos na mesma ordem de
preferência que o `render.py` usa (OPTIX → CUDA → HIP → METAL → ONEAPI) e
o monitor escolhe como medir:

| Backend detectado | Fonte da medição |
|---|---|
| OPTIX, CUDA | `nvidia-smi` — uso, VRAM e temperatura |
| HIP, METAL, ONEAPI | sem equivalente de linha de comando; mostra a CPU |
| nenhum / CPU | uso de CPU |

O uso de CPU vem de `GetSystemTimes` por `ctypes`, sem dependência
externa. A linha da CPU aparece junto com a da GPU de propósito: se um
render cair para CPU sem você perceber, o gráfico mostra na hora — GPU
parada e CPU no teto.

A VRAM fica em vermelho acima de 90%. Numa placa de 6 GB isso importa:
quando o Cycles não cabe na VRAM, o render desaba de desempenho.

Referência medida no `studio.blend`: ociosa ~12%, durante o render pico
de 97% com platô de 92–97%, VRAM em 1,4 de 6 GB.

## Botões da aba Render

- **Conferir** — valida o config contra o `.blend` sem renderizar nada.
- **Dry-run** — lista os caminhos que seriam gerados, marcando o que já
  existe.
- **Renderizar** — executa. Pula arquivos que já existem, a menos que
  `refazer o que já existe` esteja marcado, então dá para retomar um lote
  interrompido de onde parou.

O modo `preview` usa samples e resolução reduzidos para validar
combinações rápido antes de mandar o lote final.

## Referência de tempo

Medido com RTX 3050 6GB (OPTIX), 1000×1000, Cycles:

| | tempo |
|---|---|
| render final, 256 samples | 13–19 s |
| máscara, 8 samples | ~3,5 s |

O script força a ativação da GPU: em modo background o Cycles não a
seleciona sozinho e cairia em CPU silenciosamente.

## O que não está no repositório

Os arquivos `.blend` e as pastas de saída ficam fora por serem binários
grandes que mudam a cada ajuste — veja o `.gitignore`. Os projetos em
`automacao/projetos/` guardam caminhos absolutos da máquina onde foram
criados; ao usar em outro computador, reaponte o `.blend` e a pasta raiz
na aba Projeto.
