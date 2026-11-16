# Vendored Euterpe

`auditorium music` composes its beds with Euterpe (MIT, see `LICENSE`). PyPI
refuses a package whose metadata names a git dependency, and the PyPI project
called `euterpe` is unrelated, so the package is copied here (#132).

- Source: https://github.com/gia-uh/euterpe
- Commit: `45f21d8022da13fdb3ae6e81fc1630dc22261d41`
- Changes: imports rewritten from `euterpe` to `auditorium._vendor.euterpe`;
  `view/`, `lint/`, `book.py`, `cli.py` and `inspect.py` left out, since
  `auditorium/music.py` never loads them (so `display()`, `Shape.view()` and
  `Score.lint()` raise ImportError here). Ruff skips this tree.
- Runtime needs: numpy, scipy and soundfile, the `music` extra in
  `pyproject.toml`.

## Refreshing

From the repo root, with a Euterpe checkout at `../euterpe` and `REV` the new
commit:

```bash
rm -rf auditorium/_vendor/euterpe.new && mkdir auditorium/_vendor/euterpe.new
git -C ../euterpe archive "$REV" euterpe LICENSE | tar -x -C auditorium/_vendor/euterpe.new
cd auditorium/_vendor/euterpe.new && mv euterpe/* . && rmdir euterpe
rm -rf view lint book.py cli.py inspect.py
grep -rlE '(from|import) euterpe([. ]|$)' --include=*.py . \
  | xargs sed -i -E 's/\b(from|import) euterpe(\.|\b)/\1 auditorium._vendor.euterpe\2/g'
cd .. && cp euterpe/README.md euterpe.new/ && rm -rf euterpe && mv euterpe.new euterpe
```

Then update the commit above, compare Euterpe's `pyproject.toml` dependencies
with the `music` extra, check that nothing kept imports a removed module at load
time, and run `uv run pytest tests/test_music.py`.
