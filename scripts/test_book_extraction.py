#!/usr/bin/env python3
"""Test extraction on the Fossil Future book."""

import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / 'src'))

from objlib.database import Database
from objlib.extraction.client import MistralClient
from objlib.extraction.orchestrator import ExtractionOrchestrator, ExtractionConfig
from objlib.extraction.checkpoint import CheckpointManager
from objlib.extraction.chunker import prepare_transcript
from objlib.config import get_mistral_api_key
import json


async def test_book():
    # Setup
    api_key = get_mistral_api_key()
    client = MistralClient(api_key)
    db = Database('data/library.db')
    checkpoint = CheckpointManager()
    config = ExtractionConfig()

    # Get the Fossil Future book
    file_info = db.conn.execute('''
        SELECT file_path, file_size
        FROM files
        WHERE file_path LIKE '%Fossil Future%'
        LIMIT 1
    ''').fetchone()

    file_path = file_info[0]
    file_size = file_info[1]

    print(f'📚 Book: {file_path.split("/")[-1]}')
    print(f'📏 Size: {file_size / (1024*1024):.2f} MB ({file_size:,} bytes)')
    print()

    # Test chunking
    print('Testing adaptive chunker...')
    transcript = prepare_transcript(file_path, max_tokens=18000)
    estimated_tokens = len(transcript) // 4
    print(f'✓ Chunked to ~{estimated_tokens:,} tokens')

    if '[...CONTENT TRUNCATED...]' in transcript:
        print('✓ Used head-tail windowing strategy')
    elif '[EXCERPT' in transcript:
        print('✓ Used windowed sampling strategy')
    else:
        print('✓ Used full text (within token limit)')
    print()

    # Run extraction
    print('Running extraction with minimalist strategy...')
    orchestrator = ExtractionOrchestrator(client, db, checkpoint, config)

    # Load strategy
    with open('data/wave1_selection.json') as f:
        selection = json.load(f)
        strategy = selection['strategy']

    files = [{'file_path': file_path, 'filename': file_path.split('/')[-1], 'file_size': file_size}]

    result = await orchestrator.run_production(files, strategy)

    print()
    print(f'✓ Extraction complete!')
    print(f'  Status: {result.get("extracted", 0)} extracted, {result.get("failed", 0)} failed')
    print(f'  Tokens: {result.get("total_tokens", 0):,}')
    print(f'  Cost: ${result.get("estimated_cost", 0):.3f}')
    print()
    print('📊 View metadata with:')
    print('   python -c "from objlib.database import Database; import json')
    print('   db = Database(\'data/library.db\')')
    print('   r = db.conn.execute(\'SELECT metadata_json, ai_confidence_score FROM file_metadata_ai WHERE file_path LIKE \"%Fossil Future%\" AND is_current=1\').fetchone()')
    print('   print(json.dumps(json.loads(r[0]), indent=2)); print(f\"Confidence: {r[1]:.0%}\")"')

    db.close()


if __name__ == '__main__':
    asyncio.run(test_book())
