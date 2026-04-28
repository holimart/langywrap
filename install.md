# langywrap Local Install Notes

This checkout needed a few manual steps before Ralph dry-runs worked cleanly.

## 1. Pull the latest langywrap changes

```bash
git pull
```

## 2. Initialize the vendored submodules

`graphify` and `textify` are git submodules. If they are uninitialized, their
directories exist but are empty, and Ralph's graphify/textify preflight will not
work.

```bash
git submodule update --init graphify textify
```

Check status:

```bash
git submodule status
```

If the line starts with `-`, that submodule is still not initialized.

## 3. Install the knowledge-graph tools

Install both tools from the submodules into langywrap's local `uv` environment:

```bash
./just install-textify
./just install-graphify
```

Equivalent one-shot install:

```bash
uv sync --extra knowledge-graph
```

Expected binaries after install:

```bash
./.venv/bin/textify
./.venv/bin/graphify
./.venv/bin/langywrap
```

## 4. Make the CLIs visible on PATH for downstream Ralph wrappers

Ralph preflight checks `command -v graphify` and `command -v textify`, so it is
not enough that they only exist inside the `uv` environment. The launching shell
must have `langywrap/.venv/bin` on `PATH`.

For sibling-project wrappers, prepend:

```bash
export PATH="/path/to/langywrap/.venv/bin:$PATH"
```

In this workspace layout, that was:

```bash
export PATH="$PROJECT_DIR/../langywrap/.venv/bin:$PATH"
```

## 5. Verify

From the langywrap root:

```bash
./uv run graphify --help
./uv run textify --help
./uv run langywrap --help
```

From the downstream project shell:

```bash
command -v graphify
command -v textify
command -v langywrap
```

## 6. Ralph-specific note

If a downstream project uses `research/ralph/ralph_research.sh`, make sure the
wrapper either:

1. activates an environment that already exposes these CLIs on `PATH`, or
2. explicitly prepends `../langywrap/.venv/bin` to `PATH` before launching
   `langywrap`.

Otherwise Ralph dry-run may warn that `graphify` and `textify` are missing even
though they are installed in langywrap's venv.
