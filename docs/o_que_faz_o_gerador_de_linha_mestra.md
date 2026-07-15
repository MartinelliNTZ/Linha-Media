# 🧭 O que faz o "Gerador de Linha Mestra"?

## Em poucas palavras

Imagine que você tem **duas linhas desenhadas no mapa** — por exemplo, as duas margens de uma estrada, as bordas de uma calçada, ou os limites laterais de um terreno.

O **Gerador de Linha Mestra** cria automaticamente:

1. ✅ **Uma linha central** entre essas duas linhas (a **Linha Mestra**)
2. ✅ **Várias linhas de conexão** ligando uma borda à outra (as **Conexões**)

---

## 📌 Para que serve?

Esta ferramenta é útil sempre que você precisa encontrar o **meio do caminho** entre duas linhas paralelas ou irregulares.

### Exemplos do dia a dia:

| Situação | Como a ferramenta ajuda |
|---|---|
| 🛣️ **Estradas** | Você tem as duas faixas de uma rodovia e quer gerar o eixo central |
| 🏗️ **Obras lineares** | Tem os limites de um canteiro e precisa do centro para planejamento |
| 🌊 **Cursos d'água** | Duas margens de um rio — gera a calha central |
| 📏 **Lotes e faixas** | Dois limites laterais de um corredor — encontra a linha média |

---

## ⚙️ Como funciona (sem complicação)

1. **Você informa duas linhas** no mapa (pode ser na mesma camada ou em camadas separadas)
2. **Escolhe o estilo** de como as linhas de conexão serão criadas:
   - **Proximidade** — conecta os pontos mais próximos entre as duas linhas
   - **Perpendicular** — cria conexões em ângulo reto com a linha
   - **Ponto a Ponto** — liga os pontos em sequência organizada
   - **Espaçamento Fixo** — cria conexões a cada X metros
3. **A ferramenta calcula** a linha central e as conexões
4. **O resultado** é salvo como duas novas camadas no seu projeto

---

## 🎛️ Opções que você pode ajustar

- **Número de Partições** — quantos pontos serão usados para o cálculo (quanto mais, mais preciso)
- **Critério de Proximidade** — como escolher qual ponto de cada linha será emparelhado
- **Estilo da Linha Mestra** — como a linha central será gerada
- **Espaçamento Fixo** — a distância entre cada conexão (em metros)
- **Resolver órfãos** — tenta corrigir pontas soltas nas conexões

---

## 🧩 O que você recebe de resultado

| Camada de saída | O que contém |
|---|---|
| **Linha Mestra** | Uma única linha central entre as duas linhas de entrada |
| **Conexões** | Várias linhas ligando as duas bordas (como "travessas") |

---

## 🎯 Resumo para um leigo

> **"Dê duas linhas para o computador, e ele descobre qual é a linha do meio entre elas, além de criar várias linhas de ligação entre as duas — tudo isso de forma automática e com vários estilos diferentes para escolher."**

A ferramenta é como um **medidor inteligente**: ela analisa o formato das duas linhas e decide qual é a melhor maneira de conectá-las e encontrar o centro entre elas.