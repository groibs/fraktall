# Primeiro teste local

Não comece com um podcast de 3 horas. Primeiro valide o pipeline inteiro com um vídeo de 10 a 20 minutos em português.

## 1. Instalação

No Windows, depois de clonar este repositório, execute uma vez:

`INSTALL_WINDOWS.bat`

O script prepara Git/Node/Python/Ollama quando necessário, baixa a base fixada do ClipForge, aplica o patch Fraktall, instala o servidor faster-whisper e baixa/cria o modelo local `fraktall-qwen`.

## 2. Abrir o Fraktall

Execute:

`RUN_FRAKTALL.bat`

O launcher inicia Ollama, o servidor Whisper local e o app desktop.

## 3. Primeiro vídeo

Use um podcast/entrevista de 10–20 minutos, por URL do YouTube ou arquivo local.

Configuração inicial recomendada:

- Curadoria: `Podcast`
- Tipo de vídeo: `Podcast`
- Duração: `Medium / 30–60s`
- B-roll: desligado
- Open on the hook: desligado no primeiro teste
- saída: 9:16
- legendas: ligadas
- auto-reframe: padrão do pipeline

A primeira transcrição baixa o modelo Whisper escolhido, então a primeira execução pode consumir mais rede e armazenamento do que as seguintes.

## 4. O que validar

O teste só é considerado bom quando o fluxo inteiro funciona:

URL/arquivo → download/import → extração de áudio → transcrição PT-BR → seleção pelo Qwen → cards com score → preview/reframe → legendas → exportação MP4.

Observe principalmente:

- se a transcrição em português está correta;
- se os cortes começam e terminam em pensamentos completos;
- se `Editorial` faz sentido além do score viral;
- se `Contexto` pune trechos enganosos ou incompletos;
- se o crop acompanha o speaker correto;
- se a legenda está sincronizada;
- se a exportação usa NVENC quando disponível.

## 5. Diagnóstico

Se algo falhar, rode:

`powershell -ExecutionPolicy Bypass -File .\check-local.ps1`

Ele verifica Node, Git, Ollama, `fraktall-qwen`, ambiente do Whisper e endpoints locais.

## Depois do primeiro teste

Só depois de validar essa cadeia com vídeos curtos devemos implementar o pipeline de podcast longo em janelas, ranking global e uma segunda verificação contextual dedicada. Isso evita otimizar uma arquitetura ainda não testada no hardware real.
