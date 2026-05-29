"""
Document Classifier
===================
Heuristic content-type detection based on filename and a text sample.

No ML dependencies — keyword scoring only.  Sufficient to segment
analytics by "fiction vs. textbook vs. self-help" at product-analytics
granularity without needing a GPU or an external API.

Returns one of: fiction | academic | textbook | self_help | research |
                essay   | unknown
"""
from __future__ import annotations

# ── Keyword lists ─────────────────────────────────────────────────────────────
# Each list covers strong signal words; generic words (like "the") are excluded.

_SIGNALS: dict[str, list[str]] = {
    "fiction": [
        "novel", "short story", "she said", "he said", "protagonist", "chapter one",
        "narrative", "the hero", "villain", "fantasy", "romance", "thriller",
        "mystery", "dialogue", "fiction", "tale", "story", "plot",
    ],
    "academic": [
        "abstract", "methodology", "hypothesis", "peer review", "citation",
        "bibliography", "literature review", "research question", "academic",
        "scholarly", "theoretical framework", "qualitative", "quantitative",
        "epistemology", "ontology",
    ],
    "textbook": [
        "learning objectives", "key terms", "review questions", "exercises",
        "textbook", "chapter summary", "unit test", "exam preparation",
        "student", "curriculum", "course material", "syllabus", "lecture",
        "introduction to", "fundamentals of", "principles of",
    ],
    "self_help": [
        "success", "habits", "mindset", "motivation", "goal setting", "achieve",
        "productivity", "self-help", "personal development", "life coach",
        "growth mindset", "positive thinking", "confidence", "overcome",
        "transform your", "unlock your", "master your",
    ],
    "research": [
        "study", "findings", "data analysis", "sample size", "p-value",
        "statistical", "journal", "experiment", "control group", "survey",
        "interview", "observation", "measurement", "conclusion", "research paper",
        "working paper", "white paper",
    ],
    "essay": [
        "introduction", "in this essay", "i argue", "in conclusion",
        "furthermore", "however", "thesis statement", "opinion", "perspective",
        "argument", "rhetoric", "discourse", "critical analysis", "commentary",
    ],
}


def classify_document(filename: str, text_sample: str = "") -> str:
    """
    Return the most likely content category for a document.

    Args:
        filename:    Original filename (e.g. "atomic_habits.pdf")
        text_sample: Up to ~3 000 chars of extracted text for better accuracy.

    Returns:
        One of: fiction | academic | textbook | self_help | research | essay | unknown
    """
    combined = (filename.lower() + " " + text_sample.lower())

    scores: dict[str, int] = {}
    for category, keywords in _SIGNALS.items():
        scores[category] = sum(1 for kw in keywords if kw in combined)

    best_category = max(scores, key=lambda k: scores[k])
    return best_category if scores[best_category] > 0 else "unknown"
