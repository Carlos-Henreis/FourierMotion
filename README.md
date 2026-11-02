# FourierMotion

**Da imagem ao vídeo: contornos reconstruídos com séries de Fourier e epiciclos.**

FourierMotion transforma PNG/JPG com traços definidos em vídeo MP4 vertical para Instagram Reels. Duas cadeias de epiciclos representam as componentes **X(t)** e **Y(t)** enquanto uma curva é reconstruída progressivamente. Ao final, o programa exibe a fórmula paramétrica real, o número final de harmônicos `N` e o erro medido.

**Regra obrigatória:** o vídeo só é exportado quando a reconstrução atinge **erro < 0,05%**, com a tolerância padrão; um limite de harmônicos insuficiente causa erro explícito.

## Instalação

Requisitos: Python 3.10+, FFmpeg com codificador H.264, pip.

```bash
sudo apt update && sudo apt install -y ffmpeg
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
```

## Primeira execução

```bash
fourier-motion imagem.png --output output/reel.mp4
```

Por padrão: **1080 × 1920**, **30 FPS**, **60 segundos**, **2048 amostras**, **0,05%** de erro máximo exclusivo, **6 segundos** de tela final.

Gerar prévia menor (ainda mantendo 0,05% de erro):

```bash
fourier-motion imagem.png --output output/preview.mp4 --width 540 --height 960 --duration 8 --fps 12 --final-seconds 2 --samples 512
```

Analisar sem codificar o vídeo:

```bash
fourier-motion imagem.png --analyze-only
```

Limitar número de termos (falha quando insuficiente):

```bash
fourier-motion imagem.png --max-terms 100 --error 0.05
```

Ver opções:

```bash
fourier-motion --help
```

## Saídas

- `output/reel.mp4`: MP4 H.264 / yuv420p / faststart, sem áudio.
- `output/reel.fourier.json`: séries numéricas dos eixos X e Y, coeficientes reais/imaginários, amplitudes, fases, escala do erro, amostras e valor final de N.

O conteúdo do JSON permite reconstruir a expressão numérica; a tela do vídeo mostra a fórmula **compacta**, pois milhares de parcelas não caberiam no Reel.

## Como funciona

1. Carrega PNG/JPG, com prioridade ao alpha quando há transparência; senão aplica Otsu.
2. Extrai contornos externos e internos, incluindo cavidades de desenho.
3. Reamostra cada curva por comprimento de arco e concatena as curvas, preservando identificadores de caminhos para desenhá-las separadamente.
4. Centraliza as coordenadas, inverte Y e aplica FFT real independente em X e Y.
5. Busca o **menor corte de frequência N** cujo erro normalizado por diagonal do bounding box é estritamente menor que o limite.
6. Usa Parseval para avaliar todas as ordens eficientemente e confirma o N escolhido por inversa FFT e RMSE direto.
7. Renderiza quadros RGB por Pillow e transmite-os a FFmpeg, sem armazenar milhares de PNGs.
8. Reserva os segundos finais à equação paramétrica e ao resultado de convergência.

## O que é exatamente o erro?

```text
RMSE = sqrt(mean((x - x_hat)^2 + (y - y_hat)^2))
D = sqrt((xmax-xmin)^2 + (ymax-ymin)^2)
erro (%) = 100 * RMSE / D
```

**0,05% não significa** que todos os pixels da imagem original foram recuperados. Significa que o erro médio dos **pontos amostrados do contorno** está abaixo de 0,05% da diagonal. A fidelidade à imagem depende da segmentação e amostragem escolhidas.

## Fórmula reconstruída

```text
x(t) = a0 + Σ[k=1..N] Ak cos(2πkt + φk)
y(t) = b0 + Σ[k=1..N] Bk cos(2πkt + ψk)
```

O termo Nyquist da FFT real tem tratamento especial (não é dobrado). Detalhes e demonstração de Parseval em [MATEMATICA.md](docs/MATEMATICA.md).

## Organização do repositório

```text
src/fourier_motion/
  config.py      configuração e validação
  contours.py    imagem, segmentação, caminhos, reamostragem
  fourier.py     análise espectral, convergência e RMSE
  render.py      epiciclos, desenho e FFmpeg
  cli.py         interface de linha de comando e exportação
tests/           testes matemáticos e de geometria
docs/
  MATEMATICA.md  equações, decisões de erro e limites
  ARQUITETURA.md módulos, desempenho, trade-offs
.github/workflows/ci.yml
pyproject.toml
```

## Testes

```bash
pytest -q
```

A CI do GitHub Actions executa os testes em cada push e pull request.

## Decisões e limitações

- **Ordem de frequência 1..N**, não coeficientes selecionados por amplitude: permite uma fórmula por corte de frequência bem definido.
- **Convergência antes do vídeo**, com rejeição explícita de resultados acima do limite.
- **Contornos internos incluídos**, mas transições entre curvas criam descontinuidades no sinal matemático.
- **Prévia recomendada** antes do vídeo completo, pois 1800 frames em 1080×1920 com muitos harmônicos exigem processamento considerável.
- **A máscara é obtida automaticamente**; fotografias complexas podem exigir limpeza ou segmentação prévia.
- **Fonte sonora não incluída**; o MP4 gerado é silencioso.

Leia [Arquitetura](docs/ARQUITETURA.md) e [Matemática](docs/MATEMATICA.md) para detalhes e justificativas.


## Vídeo TikTok: gancho visual e evolução mais lenta

O formato padrão continua **1080x1920, 30 FPS e 60 segundos**, mas o
renderizador agora usa **7s de abertura centralizada**, um texto de gancho
parametrizável, e um ciclo completo de **3,5s para cada N**.

```bash
fourier-motion imagem.png --output output/tiktok.mp4 \
  --hook-text "Transformando o Smile em uma equação de Fourier" \
  --flash-seconds 7 --cycle-seconds 3.5 \
  --stage-terms 1,2,5,15,40,100,150,200 \
  --visual-max-terms 200 --target-fill-ratio 0.68
```

As etapas mostradas são **marcos fixos**. A duração útil restante é dividida
em pausas após cada volta completa: os pontos não são percorridos de modo
acelerado para encaixar dezenas de incrementos de N.

**N visual e N matemático não são a mesma coisa:** o limite visual de 200
reduz complexidade e melhora a leitura; a análise continua encontrando o
menor N que efetivamente satisfaz **erro < 0,05%**. Se a figura precisa de
973 harmônicos, o vídeo progride até 200 e a tela final revela N=973 e seu
erro real. O arquivo JSON preserva todos os coeficientes necessários.

A escala usa o bounding box da geometria já **centralizada antes da FFT** e
procura ocupar cerca de 68% da região reservada ao desenho. A figura permanece
à direita para abrir espaço à cadeia de epiciclos verdes, e a escala pode
ser reduzida adicionalmente para preservar os círculos visíveis.

Aos 0,5 segundos iniciais o espectador vê o resultado final de forma
antecipada; o texto aparece nos primeiros 3 segundos (quando fornecido).
Se o vídeo for curto demais para completar todos os ciclos configurados, a
aplicação falha explicitamente, em vez de cortar uma volta.

Os valores podem ser alterados no terminal com `--help`. Os detalhes de
tempo, escala e distinção entre precisão matemática e limitação visual
estão em [ARQUITETURA.md](docs/ARQUITETURA.md).


## Revisão de layout — boneco de palito e desenhos pequenos

A versão atual aumenta significativamente o desenho nos três momentos:

- **0–7 segundos:** o contorno final fica grande e centralizado, com o
  gancho original no topo. O exemplo de boneco de palito não deve mais
  ficar reduzido a poucas dezenas de pixels.
- **Ciclos:** a figura ocupa uma região maior à direita, e os epiciclos
  ficam nos espaços superior/esquerdo. Para não reduzir o boneco pelo
  raio dos círculos, os epiciclos usam escala auxiliar própria, mas
  continuam sincronizados pelo mesmo parâmetro temporal `t`.
- **Encerramento:** contorno final ampliado e centralizado; o texto
  `Erro = ...%` aparece em português; o rodapé
  `Animação: N <= 200...` não é mais mostrado.

Cada marco recebe **uma volta de 3,5 segundos**. Assim que termina,
o próximo N começa imediatamente, sem pausas artificiais.
A duração continua sendo 60 segundos; o tempo que sobra depois
dos ciclos fica com a exibição da figura final e a fórmula.
O parâmetro `--final-seconds` reserva um tempo **mínimo**, não fixa
a duração exata da cena final.

Exemplo:

```bash
fourier-motion desenho.png --output output/reel.mp4 --error 0.005 \
  --hook-text "Como o Fourier desenharia um boneco de palito?"
```

A centralização matemática (subtração da média antes da FFT) continua
inalterada. O centro **visual** agora usa o ponto médio do bounding box,
que não é necessariamente igual à média das amostras. A meta de escala
é calculada pelo bounding box e limitada pela área disponível, evitando
cortes em desenhos com proporções diferentes.


## Revisão: transições cinematográficas e última volta com N* real

A abertura mantém **7 segundos** e mostra o **contorno original**, não a
reconstrução por Fourier. A imagem foi reduzida um pouco (até 74% da largura
e 40% da altura do quadro) e posicionada em aproximadamente 44% da altura
para não invadir o gancho textual. O encerramento continua usando a
**reconstrução efetiva**, ampliada e centralizada.

O intervalo entre abertura e ciclos e o intervalo entre ciclos e resultado
possuem uma **transição de 0,4 segundo** com crossfade suavizado,
pulso dourado e zoom discreto. Ajustável por `--transition-seconds`.

A lista de ciclos tem marcos intermediários de N, mas agora **sempre
inclui o N* encontrado pela análise** como último ciclo, ainda que seja
maior que `--visual-max-terms 200`. Portanto, N=200 é apenas um
marco intermediário, nunca um teto para o resultado final.

Os ciclos continuam sem pausas: cada N realiza uma volta em 3,5 segundos
e o próximo começa imediatamente. O rótulo redundante `ETAPA N/N - 1
volta por N` foi removido. A cena final preserva N real, Erro e fórmulas,
sem o rodapé sobre o limite visual.

```bash
fourier-motion desenho.png --output output/reel.mp4 --error 0.005 \
  --hook-text "Como o Fourier desenharia um boneco de palito?" \
  --transition-seconds 0.4
```

O programa rejeita uma duração incapaz de acomodar abertura, duas
transições, todas as voltas e a duração final mínima. O valor de erro
matemático continua sendo calculado antes da renderização.


## Lápis contínuo: `--continuous-path`

Por padrão, o FourierMotion continua usando contornos independentes, sem
desenhar deslocamentos entre olhos, boca e rosto. Para construir uma única
trajetória periódica (sem levantar a caneta), habilite:

```bash
fourier-motion desenho.png --output output/reel.mp4 --error 0.005 \
  --hook-text "Como o Fourier desenharia um emoji?" \
  --continuous-path
```

**O que muda:** cada contorno fechado é percorrido por inteiro. Um algoritmo
guloso escolhe o próximo contorno mais próximo e gira seu ponto inicial para
diminuir a distância da ligação. O trajeto também retorna ao início no
último segmento, pois a série de Fourier é periódica. As ligações
integram o sinal amostrado e a análise espectral, mas são identificadas por
IDs negativos para serem exibidas como **linhas pontilhadas ciano** em vez
de traços sólidos amarelos.

O traço original permanece amarelo; apenas os movimentos entre contornos
aparecem pontilhados (na abertura, na animação e no quadro final).
No modo padrão, nenhuma ligação é exibida.

Importante: uma trajetória fisicamente contínua entre regiões
desconectadas precisa atravessar o espaço que as separa. A distinção entre
contorno e ligação é **visual**: pontilhado significa movimento de
transição, não que a caneta desapareceu. A precisão de erro é calculada
sobre o novo sinal contínuo inteiro, incluindo os deslocamentos.
O arquivo `.fourier.json` traz o campo `continuous_path` para registrar
qual modo foi utilizado.

O modo não resolve o problema de traçar contornos desconexos sem conectar
regiões. Apenas escolhe conexões relativamente curtas e torna essas
conexões explícitas. As curvas são reamostradas por comprimento de arco
para que os coeficientes descrevam a trajetória única a velocidade de
percurso aproximadamente constante.
