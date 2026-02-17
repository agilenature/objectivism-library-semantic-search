"""Semantic topic selection using sentence-transformers hybrid scoring.

Implements deterministic, offline topic reduction when AI extraction returns
more topics than desired. Combines multiple signals:
- Semantic similarity to document (sentence-transformers embeddings)
- TF-IDF statistical relevance
- Frequency-based occurrence counting
- Topic diversity penalty (avoid removing unique topics)

Based on research: Perplexity Deep Research Feb 2026
Library: sentence-transformers (all-MiniLM-L6-v2 model)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import numpy as np
from sentence_transformers import SentenceTransformer
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Lazy-load model (expensive initialization, ~90MB download on first use)
_model = None


def _get_model() -> SentenceTransformer:
    """Lazy-load sentence-transformers model.

    Returns:
        SentenceTransformer instance (all-MiniLM-L6-v2).
    """
    global _model
    if _model is None:
        logger.info("Loading sentence-transformers model (all-MiniLM-L6-v2)...")
        _model = SentenceTransformer('all-MiniLM-L6-v2')
        logger.info("Model loaded successfully")
    return _model


def select_top_topics(
    topics: list[str],
    document_text: str,
    max_topics: int = 8,
    weights: dict[str, float] | None = None,
) -> list[str]:
    """Select top N topics using hybrid semantic scoring.

    Combines multiple signals to intelligently reduce topic list:
    1. Semantic similarity - How relevant is each topic to the document?
    2. TF-IDF relevance - Statistical importance in document
    3. Frequency - How often is topic explicitly mentioned?
    4. Diversity - Penalize topics similar to others (encourage variety)

    Args:
        topics: List of topic strings to select from.
        document_text: Full source document text.
        max_topics: Maximum number of topics to return (default: 8).
        weights: Optional weight config for scoring components.
            Defaults to {'semantic': 0.4, 'tfidf': 0.25, 'frequency': 0.20, 'diversity': 0.15}

    Returns:
        List of top N topics, ordered by relevance score (highest first).

    Example:
        >>> topics = ["epistemology", "metaphysics", "ethics", "reason",
        ...           "objectivity", "concept_formation", "knowledge",
        ...           "perception", "certainty"]
        >>> document = "A philosophical text discussing knowledge and perception..."
        >>> selected = select_top_topics(topics, document, max_topics=8)
        >>> len(selected)
        8
        >>> "knowledge" in selected
        True
    """
    if len(topics) <= max_topics:
        # No reduction needed
        return topics

    # Default weights (from Perplexity research recommendations)
    if weights is None:
        weights = {
            'semantic': 0.4,      # Semantic relevance to document
            'tfidf': 0.25,        # Statistical relevance
            'frequency': 0.20,    # Explicit mention frequency
            'diversity': 0.15     # Encourage topic diversity
        }

    logger.info(
        "Selecting top %d topics from %d candidates using hybrid scoring...",
        max_topics,
        len(topics),
    )

    # 1. Semantic Similarity Score
    model = _get_model()
    topic_embeddings = model.encode(topics, normalize_embeddings=True)
    document_embedding = model.encode(document_text, normalize_embeddings=True)
    semantic_scores = cosine_similarity([document_embedding], topic_embeddings)[0]

    # 2. TF-IDF Relevance Score
    vectorizer = TfidfVectorizer(stop_words='english', max_features=500)
    corpus = [document_text] + topics
    tfidf_matrix = vectorizer.fit_transform(corpus)
    document_tfidf = tfidf_matrix[0].toarray().flatten()

    tfidf_scores = []
    for i in range(len(topics)):
        topic_tfidf = tfidf_matrix[i + 1].toarray().flatten()
        similarity = np.dot(document_tfidf, topic_tfidf) / (
            np.linalg.norm(document_tfidf) * np.linalg.norm(topic_tfidf) + 1e-10
        )
        tfidf_scores.append(similarity)

    tfidf_scores = np.array(tfidf_scores)

    # 3. Frequency-Based Score
    doc_lower = document_text.lower()
    frequency_scores = []
    for topic in topics:
        count = doc_lower.count(topic.lower())
        # Also count topic with underscores replaced by spaces
        if '_' in topic:
            alt_topic = topic.replace('_', ' ')
            count += doc_lower.count(alt_topic.lower())
        frequency_scores.append(count)

    # Normalize to 0-1 scale
    if max(frequency_scores) > 0:
        frequency_scores = np.array(frequency_scores) / max(frequency_scores)
    else:
        frequency_scores = np.zeros(len(topics))

    # 4. Topic Diversity Score
    # Penalize topics that are too similar to other topics
    # (encourages selection of diverse topics)
    pairwise_sims = cosine_similarity(topic_embeddings)
    topic_diversity = []
    for i in range(len(topics)):
        # Average similarity to all other topics (higher = less diverse)
        avg_sim_to_others = np.mean([pairwise_sims[i][j] for j in range(len(topics)) if j != i])
        # Inverse: lower similarity to others = higher diversity score
        diversity_score = 1 - avg_sim_to_others
        topic_diversity.append(diversity_score)

    topic_diversity = np.array(topic_diversity)

    # 5. Combine Scores with Weighted Average
    combined_scores = (
        weights['semantic'] * semantic_scores +
        weights['tfidf'] * tfidf_scores +
        weights['frequency'] * frequency_scores +
        weights['diversity'] * topic_diversity
    )

    # Score and rank topics
    topic_scores = list(zip(topics, combined_scores))
    topic_scores.sort(key=lambda x: x[1], reverse=True)

    # Select top N
    selected = [t[0] for t in topic_scores[:max_topics]]
    removed = [t[0] for t in topic_scores[max_topics:]]

    logger.info("Topic selection complete:")
    logger.info("  Selected: %s", selected)
    logger.info("  Removed: %s", removed)

    # Debug: Log detailed scores for removed topics
    for topic, score in topic_scores[max_topics:]:
        idx = topics.index(topic)
        logger.debug(
            "  Removed '%s' (score=%.4f): semantic=%.4f, tfidf=%.4f, freq=%.4f, div=%.4f",
            topic,
            score,
            semantic_scores[idx],
            tfidf_scores[idx],
            frequency_scores[idx],
            topic_diversity[idx],
        )

    return selected


def suggest_topics_from_vocabulary(
    document_text: str,
    existing_topics: list[str],
    vocabulary: list[str],
    min_topics: int = 3,
    max_topics: int = 8,
) -> list[str]:
    """Suggest additional topics from controlled vocabulary using semantic analysis.

    When AI extraction returns too few topics, this function analyzes the document
    to suggest the most semantically relevant topics from the controlled vocabulary.

    Args:
        document_text: Full source document text.
        existing_topics: Topics already extracted (may be empty or < min_topics).
        vocabulary: Controlled vocabulary to select from (e.g., CONTROLLED_VOCABULARY).
        min_topics: Minimum number of topics to return (default: 3).
        max_topics: Maximum number of topics to return (default: 8).

    Returns:
        Combined list of existing topics + suggested topics (up to max_topics total).

    Example:
        >>> document = "A philosophical discussion of knowledge and perception..."
        >>> existing = ["reason"]  # Model only returned 1 topic
        >>> vocabulary = ["epistemology", "metaphysics", "ethics", "knowledge", ...]
        >>> suggested = suggest_topics_from_vocabulary(document, existing, vocabulary, min_topics=3)
        >>> len(suggested) >= 3
        True
        >>> "reason" in suggested
        True
    """
    if len(existing_topics) >= min_topics:
        # Already have enough topics
        return existing_topics

    logger.info(
        "Suggesting topics from vocabulary: have %d, need %d-%d",
        len(existing_topics),
        min_topics,
        max_topics,
    )

    # Filter vocabulary to exclude topics already selected
    candidate_topics = [t for t in vocabulary if t not in existing_topics]

    if not candidate_topics:
        logger.warning("No candidate topics available in vocabulary")
        return existing_topics

    # Generate embeddings for document and all candidate topics
    model = _get_model()
    document_embedding = model.encode(document_text, normalize_embeddings=True)
    candidate_embeddings = model.encode(candidate_topics, normalize_embeddings=True)

    # Calculate semantic similarity between document and each candidate topic
    from sklearn.metrics.pairwise import cosine_similarity
    similarities = cosine_similarity([document_embedding], candidate_embeddings)[0]

    # Also calculate TF-IDF relevance for additional signal
    from sklearn.feature_extraction.text import TfidfVectorizer
    import numpy as np

    vectorizer = TfidfVectorizer(stop_words='english', max_features=500)
    corpus = [document_text] + candidate_topics
    tfidf_matrix = vectorizer.fit_transform(corpus)
    document_tfidf = tfidf_matrix[0].toarray().flatten()

    tfidf_scores = []
    for i in range(len(candidate_topics)):
        topic_tfidf = tfidf_matrix[i + 1].toarray().flatten()
        similarity = np.dot(document_tfidf, topic_tfidf) / (
            np.linalg.norm(document_tfidf) * np.linalg.norm(topic_tfidf) + 1e-10
        )
        tfidf_scores.append(similarity)

    tfidf_scores = np.array(tfidf_scores)

    # Combine semantic similarity (70%) and TF-IDF (30%)
    combined_scores = 0.7 * similarities + 0.3 * tfidf_scores

    # Rank candidate topics by combined score
    topic_scores = list(zip(candidate_topics, combined_scores))
    topic_scores.sort(key=lambda x: x[1], reverse=True)

    # Calculate how many topics to add
    topics_needed = min(min_topics - len(existing_topics), max_topics - len(existing_topics))
    topics_needed = max(0, topics_needed)  # Ensure non-negative

    # Select top N candidates
    suggested = [t[0] for t in topic_scores[:topics_needed]]

    # Combine existing + suggested
    final_topics = existing_topics + suggested

    logger.info("Topic suggestion complete:")
    logger.info("  Existing: %s", existing_topics)
    logger.info("  Suggested: %s", suggested)
    logger.info("  Final: %s", final_topics)

    # Debug: Log scores for suggested topics
    for topic in suggested:
        idx = candidate_topics.index(topic)
        logger.debug(
            "  Suggested '%s' (score=%.4f): semantic=%.4f, tfidf=%.4f",
            topic,
            combined_scores[idx],
            similarities[idx],
            tfidf_scores[idx],
        )

    return final_topics
