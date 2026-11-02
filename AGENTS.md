# AGENTS.md — article2pod

## Repository-specific rules
Read the README and relevant source before editing. Article-to-podcast pipeline: verify the source article's publication rights, dialogue attribution, voice licensing and audio dependencies. Never imply a synthetic voice is a real recording. Do not claim audio output was listened to or validated without actually playing/checking it.

## Shared assets
Shared Agent Skills are maintained in https://github.com/xingtu1996/xingtu-skills; specification practices in https://github.com/xingtu1996/xingtu-sdd. External links do not automatically install Skills or inherit instructions.

## Change and verification protocol
1. Check existing instructions, source of truth, build/test commands and any nested guidance.
2. Write an SDD spec and acceptance criteria for nontrivial changes.
3. Work in an isolated branch; submit a Draft PR and preserve rollback history.
4. Record actual tests, link checks and CI evidence; never report NOT_RUN as PASS.
5. Protect private Vault content, credentials, drafts and personal data. No automatic merge, release, license or visibility changes.

## Codex 本地仓库工作流程

- 标准工程目录为行途工作区的 `github/article2pod/`。开始任务先在此处核对 Git 根目录、工作区状态、`origin`、分支/上游和同目标 PR；默认在此本地工作树操作，不另建 `/tmp` Clone。
- 按“本地修改 → 适用检查 → 隔离分支 commit → push → 核验本地、远端分支和 PR head SHA”交付；仅在 SHA 一致、PR 文件清单包含改动且工作区干净时报告已同步。
- 已有同目标 PR 时优先续用其分支并核查 base/head 和 changed files，避免重复开 PR；不得自动合并。
- 标准 Clone 不可用或远端异常时保留现场并说明证据；临时 Clone 仅作为说明原因后的例外，并确保改动回到标准工程目录。
