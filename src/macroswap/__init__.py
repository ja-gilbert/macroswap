"""Macro-equivalent food swaps from a MyFitnessPal diary and USDA data."""

from importlib.metadata import version

from macroswap.api import Fit, Food, Match, Matcher

__version__ = version("macroswap")
__all__ = ["Fit", "Food", "Match", "Matcher", "__version__"]
