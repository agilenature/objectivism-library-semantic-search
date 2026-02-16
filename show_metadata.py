#!/usr/bin/env python3
"""Display extracted metadata from Wave 1 results in a friendly format."""

import sys
import json
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / 'src'))

from objlib.database import Database


def show_metadata(file_index=None, file_path=None):
    """Display metadata for a file from wave1_results."""
    db = Database('data/library.db')

    if file_path:
        # Query by file path
        result = db.conn.execute(
            'SELECT file_path, strategy, metadata_json, confidence_score FROM wave1_results WHERE file_path = ? LIMIT 1',
            (file_path,)
        ).fetchone()
    elif file_index is not None:
        # Query by index
        result = db.conn.execute(
            'SELECT file_path, strategy, metadata_json, confidence_score FROM wave1_results WHERE strategy = "minimalist" LIMIT 1 OFFSET ?',
            (file_index - 1,)
        ).fetchone()
    else:
        # Show first file
        result = db.conn.execute(
            'SELECT file_path, strategy, metadata_json, confidence_score FROM wave1_results WHERE strategy = "minimalist" LIMIT 1'
        ).fetchone()

    if not result:
        print("❌ No metadata found")
        db.close()
        return

    file_path, strategy, metadata_json, confidence = result
    metadata = json.loads(metadata_json)
    filename = Path(file_path).name

    # Display
    print("\n" + "=" * 80)
    print(f"📄 FILE: {filename}")
    print("=" * 80)
    print(f"Strategy: {strategy} | Confidence: {confidence:.0%}")
    print()

    # Tier 1
    print("🎯 TIER 1: Structured Classification")
    print(f"   Category:   {metadata.get('category', 'N/A')}")
    print(f"   Difficulty: {metadata.get('difficulty', 'N/A')}")
    print()

    # Tier 2
    print("🏷️  TIER 2: Primary Topics (Controlled Vocabulary)")
    topics = metadata.get('primary_topics', [])
    for i, topic in enumerate(topics, 1):
        print(f"   {i}. {topic}")
    print()

    # Tier 3
    print("📋 TIER 3: Topic Aspects (Freeform)")
    aspects = metadata.get('topic_aspects', [])
    for i, aspect in enumerate(aspects, 1):
        print(f"   {i}. {aspect}")
    print()

    # Tier 4
    print("📝 TIER 4: Semantic Description")
    desc = metadata.get('semantic_description', {})

    summary = desc.get('summary', 'N/A')
    print(f"   Summary:")
    # Word wrap at 75 chars
    words = summary.split()
    line = "      "
    for word in words:
        if len(line) + len(word) + 1 > 75:
            print(line)
            line = "      " + word
        else:
            line += (" " if line.strip() else "") + word
    if line.strip():
        print(line)
    print()

    print("   Key Arguments:")
    for i, arg in enumerate(desc.get('key_arguments', []), 1):
        # Word wrap
        words = arg.split()
        line = f"      {i}. "
        for word in words:
            if len(line) + len(word) + 1 > 75:
                print(line)
                line = "         " + word
            else:
                line += (" " if not line.endswith(". ") else "") + word
        if line.strip():
            print(line)
    print()

    positions = desc.get('philosophical_positions', [])
    if positions:
        print("   Philosophical Positions:")
        for i, pos in enumerate(positions, 1):
            print(f"      {i}. {pos}")

    print("\n" + "=" * 80 + "\n")

    db.close()


if __name__ == '__main__':
    if len(sys.argv) > 1:
        arg = sys.argv[1]
        if arg.isdigit():
            show_metadata(file_index=int(arg))
        else:
            show_metadata(file_path=arg)
    else:
        # Show available files
        db = Database('data/library.db')
        results = db.conn.execute(
            'SELECT ROW_NUMBER() OVER (ORDER BY file_path) as num, file_path FROM wave1_results WHERE strategy = "minimalist"'
        ).fetchall()
        print("\n📚 Available files with extracted metadata:\n")
        for num, path in results:
            filename = Path(path).name
            print(f"   {num}. {filename[:70]}")
        print(f"\n💡 Usage: python show_metadata.py <number>")
        print(f"   Example: python show_metadata.py 1\n")
        db.close()
