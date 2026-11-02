# Arquitetura e decisões de engenharia

## Objetivo

Uma ferramenta CLI reproduzível que recebe uma imagem de contornos e gera um MP4 vertical explicando a reconstrução por Fourier, com condição de convergência estrita e fórmula paramétrica final. O programa deve separar IO, geometria, cálculo espectral e desenho para testes e evolução independentes.

## Fluxo

    imagem PNG/JPG
         |
         v
    contours.py -- mascara, contornos, comprimentos de arco, pontos e path_ids
         |
         v
    fourier.py -- rFFT X/Y, energias espectrais, busca de N, validação direta
         |
         +--> CLI exporta .fourier.json
         |
         v
    render.py -- quadros RGB Pillow, epiciclos, projeções, trilha e equação
         |
         v
    ffmpeg (stdin rgb24) --> .partial.mp4 --> rename final

## Módulos

- config.py: parâmetros imutáveis e validação.
- contours.py: carregamento e separação dos caminhos fechados, alpha/Otsu e reamostragem.
- fourier.py: algoritmo independente de vídeo, dataclass Analysis, erro, Parseval, iFFT.
- render.py: apresentação visual, desenho em Pillow, codificação com FFmpeg, limpeza em falhas.
- cli.py: composição das etapas, argumentos e exportação JSON.
- tests/: exemplos analíticos e testes de extração.
- .github/workflows/ci.yml: pytest em push e pull request.

## Decisões

### Python, NumPy e OpenCV

NumPy implementa FFT altamente otimizada e representação complexa; OpenCV fornece segmentação, detecção de contornos e leitura de PNG/JPEG. Pillow simplifica fontes e renderização RGB. FFmpeg codifica H.264 para compatibilidade social. Essa divisão dispensa frameworks de animação pesados para um MVP.

### Séries reais independentes para X/Y

A referência visual exige duas cadeias de projeção. Usar rFFT para cada eixo cria uma representação direta da equação x(t), y(t), com pares conjugados tratados matematicamente. O eixo Y é invertido após extração para convenção cartesiana.

### Frequência de corte compartilhada

Mantemos DC e harmônicos 1..N para os dois eixos. Isso permite leitura simples de N e uma fórmula concisa. A seleção por maior amplitude teria índices dispersos e uma semântica diferente de N.

### Erro antes da renderização

Calcular e validar convergência antes de qualquer frame impede um vídeo aparentemente concluído, porém fora do limite matemático. A identidade de Parseval evita fazer uma iFFT para cada candidato N. Recalculamos uma iFFT só no corte escolhido para validação independente.

### Vários contornos

RETR_TREE permite contornos externos e internos (como olhos e boca). O algoritmo concatena as curvas em um único sinal, guardando path_ids para manter caminhos separados no desenho. Saltos entre contornos são inerentes ao sinal global: há um custo de harmônicos, mas não são desenhados como traços contínuos artificiais.

### Vídeo vertical e progressão

O padrão é 1080x1920, 30 FPS e 60 segundos (1800 frames), sem áudio. A animação cresce N ao longo da fase inicial e reserva 6 segundos para a equação final. A forma continua sendo varrida por um parâmetro t periódico durante a evolução, enquanto o erro informado é o erro do contorno inteiro, não o erro da porção já traçada.

### Pipeline de streaming

Frames RGB são enviados por stdin para FFmpeg, evitando armazenar 1800 PNGs em disco. libx264, yuv420p e faststart visam reprodução ampla. O arquivo primeiro é gravado com extensão .partial.mp4 e só é renomeado após finalização bem-sucedida. A falha remove o parcial.

## Segurança e limites

- Imagem inválida ou contorno ausente falha antes do processamento.
- N máximo insuficiente impede exportação de vídeo.
- A métrica não é um comparador pixel a pixel e não garante máximo erro pontual.
- Se houver milhares de harmônicos, desenhar círculos individualmente a 1080p é caro; o renderer oculta epiciclos abaixo de 1,3 px e visualiza até 180 raios mais relevantes pela ordem de frequência, mas a reconstrução mantém todos os termos aceitos.
- O vídeo final exibe a forma geral; coeficientes numéricos completos ficam no JSON.
- Não há upload de imagens nem API remota, e os arquivos ficam localmente.
- Fontes variam por sistema; DejaVu é preferido com fallback.
- Futuras melhorias: seleção interativa de contornos, máscara assistida, medidor de Hausdorff, suavização dos caminhos, benchmark, prévia acelerada e layouts configuráveis.

## Convenções de testes

Testes de sinal circular validam N=1, frequências altas verificam corte e convergência, max_terms insuficiente deve falhar; testes de imagem cobrem contorno externo e cavidade interna. CI roda pytest. Testes de fumaça para FFmpeg e aparência devem ser executados separadamente, porque dependem do codec e do ambiente.

## Critérios de aceitação

1. Erro percentual verificado estritamente menor que a tolerância configurada.
2. Um MP4 válido somente após convergência e codificação bem-sucedida.
3. JSON reprodutível com as duas séries numéricas.
4. Duração e geometria parametrizáveis, padrão de 60 s em 1080x1920.
5. Código em módulos e testes de matemática sem depender da renderização.
