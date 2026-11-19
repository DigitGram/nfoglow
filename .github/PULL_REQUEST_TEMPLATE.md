## What and why

<!-- A short description. Link the issue if there is one: "Fixes #123". -->

## Checked

- [ ] `python3 -m pyflakes src tests tools`, `python3 tests/test_core.py`, `shellcheck` and `tests/install_test.sh` pass
- [ ] New text in the UI is translatable (`_()`), and `po/nfoglow.pot` is updated if strings changed (`python3 tools/update_pot.py`)
- [ ] One change per pull request
