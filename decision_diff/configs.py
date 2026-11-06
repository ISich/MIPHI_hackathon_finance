"""Example configurations; the application should load user configurations at runtime."""
from .core import ArrayRule, NormalizationConfig

REAL = NormalizationConfig(
    excluded_paths=frozenset({'appData.request_id', 'appData.createDateTime'}),
    arrays={
        'decisionResult.available_offers': ArrayRule('fields', ('product_id','type')),
        'decisionResult.product_trials': ArrayRule('fields', ('product_id',)),
        'decisionResult.product_trials.rules': ArrayRule('fields', ('name',)),
        'decisionResult.product_trials.scoring.scoreModels': ArrayRule('fields', ('modelName',)),
        'decisionResult.scoring': ArrayRule('fields', ('modelName',)),
        'decisionResult.scoring.value': ArrayRule('index'),
        'ext_data': ArrayRule('fields', ('body.action',)),
        'product_catalog': ArrayRule('fields', ('mfo_id', 'product_id')),
        'tariff_matrix': ArrayRule('fields', ('mfo_id', 'product_id')),
    }
)

TEACHING = NormalizationConfig(
    excluded_paths=frozenset({'company.decisionResult.calculatedAt'}),
    arrays={
        'company.scoreCardResult': ArrayRule('fields', ('name',)),
        'company.rejectReasons': ArrayRule('value', scalar_suffix='reason'),
    },
    display_suffixes={'company.scoreCardResult': 'scoreCard', 'company.limitResult': 'Limit'},
    buckets={
        'company.scoreCardResult.value': (
            (0.3, '(0 - 0.3]'), (0.6, '(0.3 - 0.6]'),
            (0.9, '(0.6 - 0.9]'), (1.0, '(0.9 - 1.0]'),
        ),
        'company.limitResult.limit': (
            (0, '0'), (100000, '(0 - 100K]'),
            (250000, '(100K - 250K]'), (1000000, '(250K - 1M]'),
        ),
    },
)
