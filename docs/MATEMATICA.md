# Matemática do FourierMotion

## 1. Problema

Dada uma imagem, queremos representar as curvas extraídas como trajetórias paramétricas x(t), y(t), em t pertencente a [0,1), reconstruindo-as pela soma de movimentos circulares (epiciclos). Queremos obter a menor ordem inteira N tal que o erro relativo seja **estritamente menor** que 0,05%.

O programa **não treina uma rede nem minimiza uma loss por gradiente**. Calcula a DFT diretamente e acrescenta progressivamente componentes. O critério de parada é medido quantitativamente.

## 2. Extração do sinal

Para entrada PNG ou JPG, o OpenCV gera uma máscara binária. PNG com transparência parcial utiliza o canal alpha; imagens opacas usam limiar de Otsu e inversão automática quando o fundo ocupa a maioria. Com RETR_TREE, recuperamos contornos internos e externos.

Cada curva fechada é reamostrada em pontos equidistantes no comprimento de arco. Isso evita que o contorno tenha regiões super-representadas por uma maior densidade de pixels. Para múltiplas curvas, as amostras são distribuídas proporcionalmente ao perímetro, respeitando mínimo de oito pontos por contorno.

Se houver várias curvas desconexas, o sinal global é uma concatenação de caminhos. Isso introduz saltos matemáticos nos limites, portanto a série pode precisar de muitos harmônicos. Os path_ids impedem que a **visualização** desenhe linhas de ligação entre curvas. O erro continua sendo o erro do sinal concatenado.

## 3. DFT discreta independente para X e Y

Considere M amostras em coordenadas cartesianas centradas, com M par:

    p_j = (x_j, y_j),  j = 0,...,M-1.

As transformadas normalizadas são:

    Cx_k = (1/M) Σ[j=0..M-1] x_j exp(-2πi k j/M)
    Cy_k = (1/M) Σ[j=0..M-1] y_j exp(-2πi k j/M)

Como x e y são reais, há simetria conjugada. Basta armazenar os índices k=0,...,M/2, usando rFFT.

A reconstrução com N harmônicos é:

    x_N(t) = Re(Cx_0) + Σ[k=1..N] A^x_k cos(2πkt + φ^x_k)
    y_N(t) = Re(Cy_0) + Σ[k=1..N] A^y_k cos(2πkt + φ^y_k)

com A_k = 2|C_k| e φ_k = arg(C_k), exceto a frequência especial Nyquist (k=M/2) que tem amplitude |C_k| apenas. Para amostras discretas, a inversa rFFT realiza exatamente essa reconstrução, respeitando a convenção de sinal.

Os pares complexos C_k também definem os raios, fases e frequências das cadeias de epiciclos desenhadas nas laterais do contorno. O corte N é compartilhado entre os dois eixos.

## 4. Definição explícita do erro

Se p_j representa os pontos originais e p^N_j os reconstruídos:

    RMSE(N) = sqrt[(1/M) Σ[j=0..M-1] ((x_j-x^N_j)^2 + (y_j-y^N_j)^2)]

Definimos a escala D como a diagonal do menor retângulo delimitador dos pontos originais:

    D = sqrt[(max x-min x)^2 + (max y-min y)^2].

O percentual exibido e usado para validação é:

    error(N) = 100 · RMSE(N) / D.

O projeto exige error(N) < 0,05, sem aceitar igualdade. O resultado é uma medida geométrica **média**, e não garantia de que todo pixel, todo ponto isolado ou a distância de Hausdorff esteja abaixo de 0,05%. Também não mede quão fiel foi a segmentação em relação à imagem de entrada.

## 5. Critério eficiente com a identidade de Parseval

A inversa para cada N seria muito cara se repetida até M/2. Pela identidade de Parseval, a energia do erro de reconstrução é a energia dos coeficientes descartados:

    RMSE(N)^2 = Σ[k=N+1..M/2] w_k (|Cx_k|² + |Cy_k|²),

onde w_k = 2 para frequências estritamente positivas abaixo de Nyquist e w_(M/2) = 1. O termo DC é sempre preservado.

Podemos então computar a soma cumulativa reversa uma vez e avaliar todos os cortes:

    error(N) = 100 · sqrt(energia_descartada(N)) / D.

Isso faz a busca dos cortes em tempo linear depois da FFT O(M log M). Se o primeiro N que passa for N*, reconstruímos uma única vez com a iFFT e recalculamos o RMSE diretamente. A checagem só aceita N* quando o resultado real satisfaz o limite estrito.

O programa aumenta N na **ordem natural de frequência** (0, 1, 2, ...), não na ordem de maior amplitude. Logo N representa uma frequência de corte e a fórmula final é uma soma contínua de frequências. Para esse critério, o erro quadrático não aumenta ao adicionar um novo harmônico.

## 6. Propriedade e limitações da convergência

Se o limite de harmônicos chegar a M/2, a reconstrução dos M pontos amostrados é exata até erro de ponto flutuante. Isso não significa recuperar a forma contínua ideal de uma fotografia e nem a topologia pretendida. O resultado depende de binarização, comprimento de arco, resolução e amostragem.

Quando max_terms é insuficiente, o pipeline levanta ValueError e não cria um vídeo com uma afirmação de precisão falsa. A escolha de M=2048 é um compromisso padrão; aumente M para mais detalhamento. Mais amostras podem elevar bastante N*. Um N* alto também torna caro desenhar literalmente cada epiciclo em cada frame.

## 7. Fórmula final e resultado reproduzível

A tela final mostra as duas séries **paramétricas** em forma compacta e o valor de N, não imprime milhares de parcelas individualmente. O arquivo .fourier.json registra, para cada eixo e cada k utilizado, coeficientes reais e imaginários, amplitude, fase, escala, número de amostras e erro verificado, permitindo reconstruir a equação numérica.

Importante: nos eixos reais o vetor de frequência é projetado como uma soma de cossenos; a geometria dos círculos é um recurso visual para explicar cada parcela oscilatória. Em vários contornos, linhas entre caminhos não são mostradas, ainda que o sinal paramétrico salte entre eles.

## 8. Exemplos de interpretação

- Um círculo ideal amostrado uniformemente requer tipicamente apenas N=1.
- Uma figura com componente significativa na frequência 14 necessita pelo menos N=14 sob corte natural para conservar essa componente.
- Quinas, degraus, rasterização irregular e caminhos descontínuos geram altas frequências e elevam N.

A tolerância é um **critério de aceitação** e não uma restrição rígida para reduzir o tempo de vídeo: a busca ocorre antes da renderização e o vídeo distribui a evolução ao longo de 60 segundos.
