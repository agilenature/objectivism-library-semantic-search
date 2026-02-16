#!/usr/bin/env python3
"""
Parallel extraction implementation.

This script modifies run_production() in orchestrator.py to:
1. Use correct temperature from strategy config (0.1 for minimalist)
2. Add success logging
3. Process 3 files in parallel using asyncio.gather()
"""

import re

# Read the current file
with open('src/objlib/extraction/orchestrator.py', 'r') as f:
    content = f.read()

# Fix 1: Add temperature from strategy at start of run_production
old_start = '''        system_prompt = build_production_prompt(
            strategy_name, "production"
        )'''

new_start = '''        # Get temperature from Wave 1 strategy config
        from objlib.extraction.strategies import WAVE1_STRATEGIES
        strategy_config = WAVE1_STRATEGIES.get(strategy_name)
        if not strategy_config:
            raise ValueError(f"Unknown strategy: {strategy_name}")
        temperature = strategy_config.temperature

        system_prompt = build_production_prompt(
            strategy_name, "production"
        )'''

content = content.replace(old_start, new_start, 1)

# Fix 2: Change temperature=1.0 to temperature=temperature
content = content.replace(
    'temperature=1.0,  # ALWAYS 1.0 for production',
    'temperature=temperature,  # From Wave 1 winning strategy'
)

# Fix 3: Add success logging
old_logging = '''                    # Track results
                    status_value = validation.status.value
                    if status_value == "extracted":
                        results["extracted"] += 1
                    elif status_value == "needs_review":
                        results["needs_review"] += 1'''

new_logging = '''                    # Track results
                    status_value = validation.status.value
                    if status_value == "extracted":
                        results["extracted"] += 1
                        logger.info("✓ Extracted: %s (conf: %.1f%%, %dms)",
                                    file_info.get("filename", file_path), confidence * 100, latency_ms)
                    elif status_value == "needs_review":
                        results["needs_review"] += 1
                        logger.info("⚠ Needs review: %s (conf: %.1f%%, %dms)",
                                    file_info.get("filename", file_path), confidence * 100, latency_ms)'''

content = content.replace(old_logging, new_logging, 1)

# Write back
with open('src/objlib/extraction/orchestrator.py', 'w') as f:
    f.write(content)

print("✅ Applied temperature fix and logging")
print("✅ Temperature now uses strategy config (0.1 for minimalist)")
print("✅ Success logging added")
print("")
print("⚠️  Parallel processing NOT implemented yet (requires more complex refactoring)")
print("    Current implementation will continue at ~5-10 files/min")
