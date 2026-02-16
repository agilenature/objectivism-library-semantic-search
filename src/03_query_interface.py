#!/usr/bin/env python3
"""
Query Interface - Phase 3: Semantic search and query system

This script provides the interface for searching your Objectivism Library.

Usage:
    python 03_query_interface.py --query "What is the spiral theory of knowledge?"
    python 03_query_interface.py --interactive
"""

import os
import json
import argparse
from typing import Dict, List, Any, Optional
from datetime import datetime

try:
    import google.generativeai as genai
except ImportError:
    print("Error: google-generativeai package not installed")
    print("Install with: pip install google-generativeai")
    exit(1)


class ObjectivismLibrary:
    """Interface for searching the Objectivism Library corpus"""

    def __init__(self, corpus_name: str = "objectivism-library-v1", api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv('GEMINI_API_KEY')
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY not found in environment")

        genai.configure(api_key=self.api_key)
        self.corpus_name = corpus_name
        self.corpus = self.get_corpus()
        self.model = genai.GenerativeModel("gemini-2.0-flash-exp")

    def get_corpus(self) -> Any:
        """Get the corpus"""
        try:
            corpora = genai.list_corpora()
            for corpus in corpora:
                if corpus.name.endswith(self.corpus_name):
                    print(f"Connected to corpus: {corpus.name}")
                    return corpus

            raise ValueError(f"Corpus not found: {self.corpus_name}")

        except Exception as e:
            print(f"Error getting corpus: {e}")
            raise

    def search(self, query: str, filters: Optional[Dict[str, Any]] = None,
              limit: int = 10) -> List[Dict[str, Any]]:
        """
        Semantic search with optional metadata filters

        Args:
            query: Natural language query
            filters: Metadata filters (e.g., {"course_name": "ITOE", "difficulty_level": "Advanced"})
            limit: Maximum results to return

        Returns:
            List of results with content and metadata
        """
        try:
            # Build metadata filter if provided
            metadata_filter = self._build_metadata_filter(filters) if filters else None

            # Query corpus
            results = self.corpus.query(
                query=query,
                metadata_filter=metadata_filter,
                results_count=limit
            )

            # Format results
            formatted_results = []
            for i, result in enumerate(results, 1):
                formatted_results.append({
                    'rank': i,
                    'content': result.text[:500] if hasattr(result, 'text') else "",
                    'metadata': result.metadata if hasattr(result, 'metadata') else {},
                    'relevance_score': result.score if hasattr(result, 'score') else None
                })

            return formatted_results

        except Exception as e:
            print(f"Search error: {e}")
            return []

    def _build_metadata_filter(self, filters: Dict[str, Any]) -> Any:
        """Build Gemini metadata filter from dict"""
        # Note: Actual implementation depends on Gemini API metadata filter format
        # This is a placeholder - adjust based on actual API
        return filters

    def get_by_structure(self, **kwargs) -> List[Dict[str, Any]]:
        """
        Find content by organizational structure

        Examples:
            get_by_structure(year="Year1", quarter="Q1")
            get_by_structure(course_name="ITOE Advanced Topics")
        """
        # Use * as query to match all, filter by metadata
        return self.search("*", filters=kwargs)

    def ask_question(self, question: str, context_filters: Optional[Dict[str, Any]] = None) -> str:
        """
        Ask a question and get a synthesized answer from library

        Args:
            question: Your question
            context_filters: Optional filters to narrow search context

        Returns:
            Synthesized answer with citations
        """
        try:
            # Search for relevant content
            results = self.search(question, filters=context_filters, limit=5)

            if not results:
                return "No relevant content found in library."

            # Build context from results
            context = "\n\n".join([
                f"Source {i}: {r['metadata'].get('intellectual.title', 'Unknown')}\n{r['content']}"
                for i, r in enumerate(results, 1)
            ])

            # Use Gemini to synthesize answer
            prompt = f"""Based on the following excerpts from the Objectivism Library, answer this question:

Question: {question}

Library Content:
{context}

Provide a comprehensive answer with citations to the sources (Source 1, Source 2, etc.).
"""

            response = self.model.generate_content(prompt)
            return response.text

        except Exception as e:
            return f"Error generating answer: {e}"

    def trace_concept_evolution(self, concept: str) -> List[Dict[str, Any]]:
        """
        Show how a concept is explained across the curriculum

        Args:
            concept: Philosophical concept to trace

        Returns:
            List of sources ordered by pedagogical sequence
        """
        # Search for concept
        results = self.search(concept, limit=20)

        # Sort by pedagogical progression
        # Priority: Foundations -> Intermediate -> Advanced
        # Then by: Year -> Quarter -> Week
        def get_sort_key(result):
            metadata = result.get('metadata', {})

            difficulty_order = {
                'Foundations': 1,
                'Intermediate': 2,
                'Advanced': 3,
                'Expert': 4
            }

            difficulty = difficulty_order.get(
                metadata.get('instructional.difficulty_level', 'Intermediate'),
                2
            )

            # Extract year/quarter/week if available
            year = metadata.get('pedagogical_structure.course_sequence.year', 'Year9')
            quarter = metadata.get('pedagogical_structure.course_sequence.quarter', 'Q9')
            week = metadata.get('pedagogical_structure.course_sequence.week', 'Week99')

            return (difficulty, year, quarter, week)

        results.sort(key=get_sort_key)
        return results

    def compare_explanations(self, concept: str,
                            source1_filter: Dict[str, Any],
                            source2_filter: Dict[str, Any]) -> str:
        """
        Compare how two sources explain the same concept

        Args:
            concept: Concept to compare
            source1_filter: Metadata filter for first source
            source2_filter: Metadata filter for second source

        Returns:
            Comparative analysis
        """
        # Get explanations from both sources
        results1 = self.search(concept, filters=source1_filter, limit=3)
        results2 = self.search(concept, filters=source2_filter, limit=3)

        if not results1 or not results2:
            return "Could not find content from both sources."

        # Build comparison prompt
        source1_content = "\n".join([r['content'] for r in results1])
        source2_content = "\n".join([r['content'] for r in results2])

        source1_name = results1[0]['metadata'].get('course_name', 'Source 1')
        source2_name = results2[0]['metadata'].get('course_name', 'Source 2')

        prompt = f"""Compare how these two sources explain "{concept}":

Source 1: {source1_name}
{source1_content}

Source 2: {source2_name}
{source2_content}

Provide a comparative analysis covering:
1. Common ground - what both emphasize
2. Unique to Source 1
3. Unique to Source 2
4. Complementary insights
"""

        response = self.model.generate_content(prompt)
        return response.text

    def generate_synthesis(self, concept: str, format: str = "markdown") -> str:
        """
        Generate comprehensive synthesis document (like Spiral Theory doc)

        Args:
            concept: Concept to synthesize
            format: Output format (markdown, text)

        Returns:
            Comprehensive synthesis document
        """
        # Get all relevant sources
        results = self.search(concept, limit=30)

        if not results:
            return f"No content found for '{concept}'"

        # Build comprehensive context
        all_content = []
        for result in results:
            metadata = result['metadata']
            title = metadata.get('intellectual.title', 'Unknown')
            course = metadata.get('course_name', '')
            content = result['content']

            all_content.append(f"### {title}\nCourse: {course}\n\n{content}\n")

        combined_content = "\n\n".join(all_content)

        # Generate synthesis
        prompt = f"""You are creating a comprehensive synthesis document about "{concept}" from the Objectivism Library.

Based on all these sources:

{combined_content}

Create a detailed synthesis document with:

# {concept.title()}: A Comprehensive Synthesis

## I. Core Definition
[Extract and synthesize the core definition]

## II. Essential Characteristics
[List and explain key characteristics]

## III. Theoretical Foundations
[Explain the theoretical basis]

## IV. Applications
[Show how it's applied across domains]

## V. Key Quotations
[Include important quotes with sources]

## VI. Related Concepts
[Connections to other ideas]

## VII. Sources
[List all sources consulted]

Make it comprehensive, well-organized, and include citations throughout.
"""

        response = self.model.generate_content(prompt)
        return response.text


def interactive_mode(library: ObjectivismLibrary):
    """Interactive query mode"""
    print("\n" + "="*60)
    print("Objectivism Library - Interactive Search")
    print("="*60)
    print("\nCommands:")
    print("  search <query>              - Semantic search")
    print("  ask <question>              - Ask question with synthesis")
    print("  trace <concept>             - Trace concept evolution")
    print("  compare <concept>           - Compare across sources")
    print("  navigate <year> <quarter>   - Browse by structure")
    print("  help                        - Show this help")
    print("  quit                        - Exit")
    print()

    while True:
        try:
            command = input("\n> ").strip()

            if not command:
                continue

            if command == "quit":
                break

            elif command == "help":
                continue  # Help already printed above

            elif command.startswith("search "):
                query = command[7:].strip()
                print(f"\nSearching for: {query}")
                results = library.search(query, limit=5)
                print_results(results)

            elif command.startswith("ask "):
                question = command[4:].strip()
                print(f"\nQuestion: {question}\n")
                answer = library.ask_question(question)
                print(answer)

            elif command.startswith("trace "):
                concept = command[6:].strip()
                print(f"\nTracing evolution of: {concept}")
                evolution = library.trace_concept_evolution(concept)
                print_evolution(evolution)

            else:
                print("Unknown command. Type 'help' for commands.")

        except KeyboardInterrupt:
            print("\n\nExiting...")
            break
        except Exception as e:
            print(f"Error: {e}")


def print_results(results: List[Dict[str, Any]]):
    """Pretty print search results"""
    if not results:
        print("No results found.")
        return

    for result in results:
        print(f"\n[{result['rank']}] {result['metadata'].get('intellectual.title', 'Unknown Title')}")
        if 'course_name' in result['metadata']:
            print(f"    Course: {result['metadata']['course_name']}")
        if 'difficulty_level' in result['metadata']:
            print(f"    Level: {result['metadata']['difficulty_level']}")
        print(f"\n    {result['content'][:300]}...")
        print()


def print_evolution(results: List[Dict[str, Any]]):
    """Pretty print concept evolution"""
    if not results:
        print("No results found.")
        return

    current_level = None
    for result in results:
        level = result['metadata'].get('instructional.difficulty_level', 'Unknown')

        if level != current_level:
            print(f"\n### {level} Level")
            current_level = level

        title = result['metadata'].get('intellectual.title', 'Unknown')
        course = result['metadata'].get('course_name', '')
        print(f"\n  • {title}")
        if course:
            print(f"    ({course})")


def main():
    parser = argparse.ArgumentParser(description='Query Objectivism Library')
    parser.add_argument('--corpus-name', type=str,
                       default='objectivism-library-v1',
                       help='Corpus name')
    parser.add_argument('--query', type=str,
                       help='Search query')
    parser.add_argument('--question', type=str,
                       help='Ask a question (with synthesis)')
    parser.add_argument('--trace', type=str,
                       help='Trace concept evolution')
    parser.add_argument('--interactive', action='store_true',
                       help='Interactive mode')
    parser.add_argument('--synthesize', type=str,
                       help='Generate synthesis document for concept')

    args = parser.parse_args()

    # Initialize library
    library = ObjectivismLibrary(corpus_name=args.corpus_name)

    # Execute command
    if args.interactive:
        interactive_mode(library)

    elif args.query:
        print(f"Searching for: {args.query}\n")
        results = library.search(args.query)
        print_results(results)

    elif args.question:
        print(f"Question: {args.question}\n")
        answer = library.ask_question(args.question)
        print(answer)

    elif args.trace:
        print(f"Tracing evolution of: {args.trace}\n")
        evolution = library.trace_concept_evolution(args.trace)
        print_evolution(evolution)

    elif args.synthesize:
        print(f"Generating synthesis for: {args.synthesize}\n")
        print("This may take a minute...")
        synthesis = library.generate_synthesis(args.synthesize)
        print(synthesis)

        # Save to file
        output_file = f"../output/{args.synthesize.replace(' ', '_')}_synthesis.md"
        os.makedirs("../output", exist_ok=True)
        with open(output_file, 'w') as f:
            f.write(synthesis)
        print(f"\nSaved to: {output_file}")

    else:
        print("No command specified. Use --help for options or --interactive for interactive mode.")


if __name__ == '__main__':
    main()
