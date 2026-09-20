# macroswap

Macro-equivalent food swaps from a MyFitnessPal diary and USDA data:
"I'm tired of this food; what else, and exactly how many grams of it,
gives me the same macros?"

## Development

    uv sync
    uv run ruff check .
    uv run ruff format --check .
    uv run mypy
    uv run pytest

Personal data never enters the repository: the diary HTML lives under
`data/raw/` and the built database under `data/build`, both are ignored.
