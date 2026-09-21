# Skills externas instaladas (2026-09-21)

Este arquivo documenta skills de terceiros trazidas para este repositório a
pedido do usuário, para facilitar atualização futura e não confundir com
skills escritas especificamente para este projeto.

## `tdd`, `grill-me` e `grilling` — Matt Pocock (aihero.dev)

- Fonte: https://github.com/mattpocock/skills (MIT — ver `THIRD_PARTY_LICENSES.md`)
- `tdd`: workflow de TDD (red/green/refactor, mocking, estrutura de testes)
  para tarefas de engenharia — `skills/engineering/tdd` no repo original.
- `grill-me`: interview relentless para validar plano/spec/decisão antes de
  implementar (`/grill-me` ou pedir "me grill sobre X") — por sua vez chama a
  skill `grilling`, copiada junto por ser uma dependência dela.
- Copiadas como arquivos estáticos — mesmo resultado do instalador oficial
  (`npx skills add mattpocock/skills`, que também grava os arquivos direto no
  repo) — em vez do plugin `mattpocock-skills` completo, porque esse plugin
  traz ~24 skills e só estas duas foram pedidas.
- Atualizar: repetir a cópia de `skills/engineering/tdd` e
  `skills/productivity/{grill-me,grilling}` do repo upstream.

## `find-skills` — Vercel Labs

- Fonte: https://github.com/vercel-labs/skills (MIT — ver `THIRD_PARTY_LICENSES.md`)
- Ajuda a descobrir e instalar outras skills do ecossistema aberto
  (skills.sh) quando o usuário pedir algo que provavelmente já tem skill
  pronta, em vez de reinventar.
- É a única skill desse repositório — o resto do repo é o CLI `npx skills`
  em si, não uma skill.
- Atualizar: repetir a cópia de `skills/find-skills` do repo upstream.

## `superpowers` (plugin, não arquivo local)

O plugin [`superpowers`](https://github.com/obra/superpowers) (marketplace
`superpowers-dev`, registrada em `.claude/settings.json`) traz skills
genéricas de engenharia (brainstorming, escrita de plano, TDD, debug
sistemático, revisão de código, subagentes, git worktree etc.) para
qualquer agente que abrir este repositório — mesmo padrão já usado em
`ressoa`, `rezenhai-mvp` e `revoz`. Não é copiado como arquivo: o Claude
Code busca o conteúdo do marketplace/plugin em tempo de execução.
