"""model/datasets/ -- real-dataset loaders for Stage A pre-training (design 02 SS4.2)
and thin wrappers registering the existing synthetic feature CSVs (design 02 SS4.3).

Every loader in this package converts a public raw dataset into the CONTRACTS.md
SS2 / features/schema.py per-cycle record schema and writes a manifest CSV under
data/manifests/. Loaders never invent sensor values: a channel that cannot be
genuinely derived from the source data is emitted as NaN with the reason
documented in the module docstring and in `NONDERIVABLE_CHANNELS`.
"""
