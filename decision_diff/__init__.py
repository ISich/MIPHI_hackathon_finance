"""Pure, framework-independent JSON normalization and comparison."""
from .core import ArrayRule, NormalizationConfig, normalize, compare, normalize_pair

__all__ = ['ArrayRule', 'NormalizationConfig', 'normalize', 'compare', 'normalize_pair']
