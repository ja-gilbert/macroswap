# Using macroswap as a library

The matcher, the fit and the USDA table import as `macroswap`, through one class
and three values. The swap engine is not part of the library in this version;
the `swap` command is. The [README](../README.md) has the commands, and
[how it works](how-it-works.md) the rules behind every number here.

## Install

Pin a tag; the `embed` extra is the default method's:

    macroswap[embed] @ git+https://github.com/ja-gilbert/macroswap@v0.1.0

The CPU-only torch a clone of this repository installs comes from its own uv
settings, which a project pinning macroswap does not inherit: that project gets
the default torch build unless it points torch at the CPU index itself.

## The store

The library reads the SQLite store the command builds. Build it once with the
installed command, in the directory you want it in:

    macroswap data pull     # about 140 MB into data/raw/usda/, verified by checksum; 238 MB unpacked
    macroswap data build    # data/build/macroswap.sqlite

and pass that path as `store`. In a clone, `uv run macroswap data pull` and
`uv run macroswap data build`, run from its root, do the same under it.

## Example

    from pathlib import Path
    from macroswap import Matcher

    # where data pull and data build were run: ~/macroswap-data
    store = Path.home() / "macroswap-data/data/build/macroswap.sqlite"
    m = Matcher(store=store)

    match = m.match("kirkland - chicken breast")  # None when the matcher abstains (NO_MATCH)
    if match:
        fit = m.fit(match, protein_g=31.0, carbs_g=0.0, fat_g=3.6)
        print(match.name, round(fit.grams), "g")
        food = m.food(match.row_id)  # macros per 100 g

    matches = m.match_many(["oats", "greek yogurt", "kirkland - chicken breast"])

## Matcher

`Matcher(store=None, method=None, labels=None)` does no work when it is made.
The library reads the config shipped inside the package, so a project using it
needs no config file; a `macroswap.toml` in the working directory is not read.
`store` defaults to the config's, `data/build/macroswap.sqlite` relative to the
working directory, which is why the example passes one; `method` defaults to
the config's, embed, and an unknown method raises `ValueError`.

The model and the index's vectors load on first use and stay loaded for the
life of the `Matcher`. The very first use downloads the model, about 88 MB,
into `~/.cache/huggingface`; after that it loads from there. The vectors are
cached beside the store as `embeddings-*.npy`, one file per model, library
versions and table; a new version writes beside the old file, which is yours
to delete.

`labels`, a `Path` to a labels file (a string fails), applies labels the way
`diary match` does: a labeled name takes its label, with method `"label"` and
no score, and the rest go to the matcher. The labels are read and checked when
the `Matcher` first loads, after the model, with the check `diary match` uses.
Without `labels`, the answers are the matcher's alone, the ones the eval
measures.

| Method | Returns |
| --- | --- |
| `match(name)` | The top food for a name as a `Match`, or `None` when the matcher abstains under this `Matcher`'s method, which `macroswap match` prints as NO_MATCH for that method. |
| `match_many(names)` | A list of `Match` or `None`, in order, with one call of the model for the whole list and one more for the names that stand on their family's default level. |
| `fit(match, protein_g, carbs_g, fat_g)` | A `Fit`: the grams of the matched food that best give those macros, by the swap's fit, and what that serving misses. A row lacking one of the macros raises `ValueError` naming it. |
| `food(row_id)` | A `Food`: the row's macros per 100 g. An unknown `row_id` raises `KeyError`. |

A ground-meat name without a level, `ground beef`, stands on its family's
configured default level; `ground beef 93/7` picks one. A level the table has
no row at, `ground beef 91/9`, falls back to the default level, and `Match` does
not say so yet; the `swap` command does, in its header. The five everyday
names of the `swap` command (`[swap.staples]`) are not used here: the library
gives the matcher's own answer for them.

## The values

`Match`, `Fit` and `Food` are frozen dataclasses.

| `Match` | |
| --- | --- |
| `row_id` | The row: `sr:168877`, `foundation:2646170`, or `derived:beef, ground:88/12` for a ground-beef level interpolated between two published ones. |
| `name` | Its USDA description; a derived level has one made for it, `Beef, ground, 88/12`. |
| `family` | Its family key, such as `chicken, breast`. |
| `score` | The method's own score: BM25 for lexical, cosine for embed, a fused rank for hybrid, not comparable across methods; `None` for a label. |
| `method` | `"label"`, `"lexical"`, `"embed"` or `"hybrid"`. |

| `Fit` | |
| --- | --- |
| `row_id` | The row. |
| `grams` | The serving. |
| `residual` | The weighted miss a swap ranks by, in calories. |
| `delta_protein_g`, `delta_carbs_g`, `delta_fat_g` | The serving's macros minus the ones asked for. |

| `Food` | |
| --- | --- |
| `row_id`, `name`, `family` | As in `Match`. |
| `kcal`, `protein_g`, `carbs_g`, `fat_g`, `sugars_g` | Per 100 g. Each may be `None`: a few rows lack a macro, and many lack sugars. |

`macroswap.__version__` is the installed version.

## Errors

A missing or unbuilt store raises `FileNotFoundError`, with "no database at
<path>; run `data build` first", "no USDA table in <path>; run `data build`
first" or "no USDA rows in <path>; run `data build` again". A file that is not
a SQLite database raises `sqlite3.DatabaseError`, an unknown method
`ValueError`, and a label naming a row the store does not have raises
`LabelError`, from `macroswap.match.diary`.

The default method without the `embed` extra raises `EmbedUnavailable`, a
`RuntimeError` imported from `macroswap.match.embed`: "embed extra not
installed (uv sync --extra embed, or install macroswap[embed])". It is raised
too, with the extra installed, when the model is neither cached nor
downloadable.

An unknown `row_id` raises `KeyError`, and a fit on a row lacking a macro
raises `ValueError`.
