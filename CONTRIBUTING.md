# Contributing

Thanks for taking an interest in Personal Understanding. This project is a working, daily-driven personal-memory system for AI agents — every design rule below exists because a real use case demanded it.

## Ways to contribute

- **Bug reports & issues** — include the client (Claude Code / Codex / VS Code / Cursor / Windsurf / Cline / Trae / ZCode / generic MCP), the command or tool that failed, and the full error output.
- **New client installers** — `scripts/install_mcp.py` detects AI clients and registers the local MCP server. If you use a client it doesn't cover, a PR adding its config layout is very welcome.
- **Dashboard improvements** — `dashboard/` is a local read-only audit panel. Keep it read-only.
- **i18n** — the low-signal detector (`scripts/preflight_context.py`) currently recognizes English and Chinese; more languages welcome.
- **Tests** — `tests/` must stay side-effect-free on a clean tree: any test that writes archive data must do so inside a temporary copy, never in the repo.

## Design rules to respect

This project is opinionated on purpose. Before changing behavior, read the relevant policy in `references/`:

- **Verbatim-first**: user messages are captured word-for-word (immutable, hashed) *before* any summarizing. Summaries must never impersonate verbatim.
- **No fabricated certainty**: uncertain dates stay uncertain; vague pronouns never become people; a single event never becomes a causal hypothesis; the model's guesses always stay `candidate`.
- **Privacy is absolute**: data stays on the user's machine. Never add telemetry, cloud calls, or third-party dependencies.
- **Dependencies**: Python stdlib only. No pip installs, no vector databases, no embeddings services.
- **Backwards compatibility**: legacy records are kept as migration debt, never deleted or silently rewritten.

## Development setup

```bash
# Python 3.10+ (stdlib only)
python -m unittest discover -s tests -p "test_*.py"   # suite must exit 0
py -3 -m py_compile scripts/*.py                       # sanity compile
```

## Code of conduct

See [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md). Be constructive; this is a small, friendly project.

## License

By contributing you agree that your contributions are licensed under the [MIT License](LICENSE).
