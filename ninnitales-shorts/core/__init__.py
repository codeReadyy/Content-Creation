"""core — shared types, config loading, ledger, and guardrails for the content engine.

The engine is built from four plugin kinds, all wired together by config (no logic
hunting across files):

  • formats/    — produce an Asset (a video, or a set of carousel slides)
  • publishers/ — post an Asset to one (platform, account)
  • config/accounts.yml — the routing table: which accounts run which formats, when
  • config/niches/*.yml  — the per-niche content profile (voice, themes, CTA, titles)

See core.models for the Asset / PostCopy / Niche / Account types and the Format /
Publisher protocols, and core.config for loading the YAML into those types.
"""
