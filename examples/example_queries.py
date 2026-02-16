#!/usr/bin/env python3
"""
Example Queries for Objectivism Library

This file demonstrates various ways to query your library.
"""

import sys
sys.path.append('../src')

from query_interface import ObjectivismLibrary


def main():
    # Initialize library
    library = ObjectivismLibrary()

    print("="*60)
    print("OBJECTIVISM LIBRARY - EXAMPLE QUERIES")
    print("="*60)

    # Example 1: Basic Semantic Search
    print("\n### Example 1: Basic Semantic Search")
    print("Query: 'How does knowledge deepen through returning to earlier concepts?'")
    results = library.search("How does knowledge deepen through returning to earlier concepts?", limit=3)
    for r in results:
        print(f"  • {r['metadata'].get('intellectual.title', 'Unknown')}")
    print(f"Found {len(results)} results")

    # Example 2: Filtered Search
    print("\n### Example 2: Filtered Search (Foundations + Ethics)")
    print("Query: 'values and virtues' + filters")
    results = library.search(
        "values and virtues",
        filters={
            "content_characteristics.primary_branch": "Ethics",
            "instructional.difficulty_level": "Foundations"
        },
        limit=3
    )
    for r in results:
        print(f"  • {r['metadata'].get('intellectual.title', 'Unknown')}")
        print(f"    Level: {r['metadata'].get('instructional.difficulty_level', 'N/A')}")

    # Example 3: Navigate by Structure
    print("\n### Example 3: Navigate by Structure (Year 1, Q1)")
    results = library.get_by_structure(
        year="Year1",
        quarter="Q1"
    )
    print(f"Found {len(results)} lectures in Year 1, Q1")
    if results:
        for r in results[:3]:
            print(f"  • {r['metadata'].get('intellectual.title', 'Unknown')}")

    # Example 4: Ask a Question with Synthesis
    print("\n### Example 4: Ask Question (with answer synthesis)")
    print("Question: 'What is the relationship between hierarchy and context?'")
    answer = library.ask_question("What is the relationship between hierarchy and context?")
    print(f"\nAnswer (first 500 chars):\n{answer[:500]}...")

    # Example 5: Trace Concept Evolution
    print("\n### Example 5: Trace Concept Evolution")
    print("Concept: 'free will'")
    evolution = library.trace_concept_evolution("free will")
    print(f"\nFound in {len(evolution)} sources, ordered by difficulty:")
    current_level = None
    for r in evolution[:5]:  # Show first 5
        level = r['metadata'].get('instructional.difficulty_level', 'Unknown')
        if level != current_level:
            print(f"\n  {level}:")
            current_level = level
        print(f"    • {r['metadata'].get('intellectual.title', 'Unknown')}")

    # Example 6: Compare Explanations
    print("\n### Example 6: Compare Explanations Across Sources")
    print("Concept: 'objectivity' in ITOE vs. Objectivism Through Induction")
    comparison = library.compare_explanations(
        concept="objectivity",
        source1_filter={"course_name": "ITOE"},
        source2_filter={"course_name": "Objectivism Through Induction"}
    )
    print(f"\nComparison (first 500 chars):\n{comparison[:500]}...")

    # Example 7: Advanced - Find Prerequisites
    print("\n### Example 7: Finding Prerequisites")
    print("Topic: 'concept formation'")
    # Search for foundational content
    foundational = library.search(
        "perception, senses, consciousness",
        filters={"instructional.difficulty_level": "Foundations"},
        limit=3
    )
    print("Prerequisites to study first:")
    for r in foundational:
        print(f"  • {r['metadata'].get('intellectual.title', 'Unknown')}")

    # Example 8: Specific Course Content
    print("\n### Example 8: Browse Specific Course")
    print("Course: 'Objectivism Seminar - Foundations'")
    course_content = library.search(
        "*",
        filters={"course_name": "Objectivism Seminar - Foundations"},
        limit=5
    )
    print(f"Found {len(course_content)} lectures")
    for r in course_content[:3]:
        title = r['metadata'].get('intellectual.title', 'Unknown')
        year = r['metadata'].get('pedagogical_structure.course_sequence.year', '')
        quarter = r['metadata'].get('pedagogical_structure.course_sequence.quarter', '')
        week = r['metadata'].get('pedagogical_structure.course_sequence.week', '')
        print(f"  • {year} {quarter} {week}: {title}")

    print("\n" + "="*60)
    print("Examples complete!")
    print("\nTry these yourself:")
    print("  python ../src/03_query_interface.py --interactive")
    print("  python ../src/03_query_interface.py --query 'your question'")
    print("="*60)


if __name__ == '__main__':
    main()
