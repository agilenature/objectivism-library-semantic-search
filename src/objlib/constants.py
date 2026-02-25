"""Project-wide named constants.

Constants defined here replace inline magic numbers across the codebase.
Each constant has an empirical derivation documented in its docstring.
"""

# Empirical derivation (2026-02-25):
# - Largest successfully extracted .txt: 3,475,970 bytes (La rebelion de Atlas)
# - Single skipped .txt boundary case: 552,798 bytes (Philosophy - Who Needs It)
# - 1.5x the boundary file = 829,197 bytes, rounded to 830,000
# - Files >= BOOK_SIZE_BYTES are books (ai_metadata_status='skipped', no extraction)
# - Files < BOOK_SIZE_BYTES are non-books (must complete batch-extract)
BOOK_SIZE_BYTES: int = 830_000
