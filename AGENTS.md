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
