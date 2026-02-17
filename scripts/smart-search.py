#!/usr/bin/env python3
"""Smart Search - Intelligent query expansion for Objectivism Library.

This script takes a simple query and intelligently expands it before searching,
following the workflow:
1. Analyze the user's intent
2. Expand with domain vocabulary and multiple angles
3. Execute search against Gemini File Search
4. Present results with sources

Usage:
    ./scripts/smart-search.py "your simple question"
    python scripts/smart-search.py "context dropping"
"""
import sys
import subprocess
import json
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from google import genai
import keyring


def expand_query_with_gemini(user_query: str, api_key: str) -> str:
    """Expand a simple query into a comprehensive search query using Gemini.

    Args:
        user_query: The user's simple question or topic
        api_key: Gemini API key

    Returns:
        Expanded query optimized for semantic search
    """
    expansion_prompt = f"""You are a query expansion assistant for an Objectivist philosophy library semantic search system.

The user wants to search for: "{user_query}"

Your task: Expand this into a comprehensive search query (150-250 words) that will help retrieve the most relevant information from a library of Objectivist philosophy materials (books, lectures, courses).

Follow this structure:
1. State the core concept/question clearly
2. Add related terms and philosophical vocabulary
3. Ask multiple angles of the question (What is it? How does it work? Why is it important? Examples?)
4. Include both abstract principles and concrete applications
5. Use proper Objectivist terminology

Example:
User query: "context dropping"
Expanded query: "The epistemological error of context dropping: ignoring or evading relevant context when forming judgments or evaluating ideas. What is context dropping? Examples of context dropping in philosophy and everyday reasoning. How does dropping context lead to invalid conclusions? The importance of maintaining full context in thought."

Now expand: "{user_query}"

Return ONLY the expanded query text, no explanations or meta-commentary."""

    try:
        # Use Gemini via genai SDK
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model="gemini-2.0-flash-thinking-exp-01-21",
            contents=expansion_prompt,
        )
        expanded = response.text.strip()

        # Remove any thinking tags if present
        if "<thinking>" in expanded:
            expanded = expanded.split("</thinking>")[-1].strip()

        return expanded
    except Exception as e:
        print(f"⚠️  Query expansion failed: {e}", file=sys.stderr)
        print(f"⚠️  Using original query: {user_query}", file=sys.stderr)
        return user_query


def execute_search(expanded_query: str, store_name: str = "objectivism-library-test") -> int:
    """Execute the search using objlib CLI.

    Args:
        expanded_query: The expanded search query
        store_name: Gemini File Search store name

    Returns:
        Exit code from search command
    """
    cmd = [
        sys.executable, "-m", "objlib",
        "--store", store_name,
        "search", expanded_query
    ]

    result = subprocess.run(cmd)
    return result.returncode


def main():
    """Main entry point for smart search."""
    if len(sys.argv) < 2:
        print("Usage: smart-search.py <query>", file=sys.stderr)
        print("\nExamples:", file=sys.stderr)
        print('  smart-search.py "context dropping"', file=sys.stderr)
        print('  smart-search.py "what is the virtue of rationality?"', file=sys.stderr)
        print('  smart-search.py "deserveness and earning"', file=sys.stderr)
        return 1

    # Get user query
    user_query = " ".join(sys.argv[1:])

    # Get API key
    api_key = keyring.get_password("objlib-gemini", "api_key")
    if not api_key:
        print("❌ Error: No Gemini API key found in keyring", file=sys.stderr)
        print("   Set with: keyring set objlib-gemini api_key", file=sys.stderr)
        return 1

    print(f"\n🔍 Original query: \"{user_query}\"")
    print("⚙️  Expanding query with domain knowledge...\n")

    # Expand query
    expanded_query = expand_query_with_gemini(user_query, api_key)

    if expanded_query != user_query:
        print("📝 Expanded query:")
        # Show first 200 chars
        display_query = expanded_query[:200] + ("..." if len(expanded_query) > 200 else "")
        print(f"   {display_query}\n")

    # Execute search
    print("🔎 Searching...\n")
    exit_code = execute_search(expanded_query)

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
