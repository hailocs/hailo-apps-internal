#!/usr/bin/env python3
"""
Knowledge base manager for pipeline profiling insights.

Usage:
    python knowledge_base.py show
    python knowledge_base.py add-recipe --app <app> --change <desc> --before <json> --after <json> [--tags <tags>]
    python knowledge_base.py add-insight --text <text> [--tags <tags>]
    python knowledge_base.py query --element <name>
    python knowledge_base.py query --tags <tags>
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import yaml


KB_PATH = Path(__file__).parent.parent / "knowledge" / "knowledge_base.yaml"


def load_kb():
    """Load the knowledge base, creating default if missing."""
    if KB_PATH.exists():
        with open(KB_PATH) as f:
            return yaml.safe_load(f) or _default_kb()
    return _default_kb()


def save_kb(kb):
    """Save the knowledge base."""
    KB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(KB_PATH, "w") as f:
        yaml.dump(kb, f, default_flow_style=False, sort_keys=False, width=120)


def _default_kb():
    return {
        "version": "1.0",
        "tuning_recipes": [],
        "bottleneck_patterns": [],
        "insights": [],
        "experiment_history": [],
    }


def show(kb):
    """Display the knowledge base."""
    print(f"=== Pipeline Profiling Knowledge Base ===")
    print(f"Version: {kb.get('version', '?')}")

    recipes = kb.get("tuning_recipes", [])
    print(f"\n--- Tuning Recipes ({len(recipes)}) ---")
    for r in recipes:
        print(f"  [{r.get('id', '?')}] {r.get('app', '?')}: {r.get('change', '?')}")
        if r.get("improvement"):
            print(f"    Result: {r['improvement']}")

    patterns = kb.get("bottleneck_patterns", [])
    print(f"\n--- Bottleneck Patterns ({len(patterns)}) ---")
    for p in patterns:
        print(f"  Pattern: {p.get('pattern', '?')}")
        print(f"    Suggestion: {p.get('suggestion', '?')} (confidence: {p.get('confidence', '?')})")

    insights = kb.get("insights", [])
    print(f"\n--- Insights ({len(insights)}) ---")
    for i in insights:
        print(f"  - {i.get('text', '?')} [{', '.join(i.get('tags', []))}]")

    history = kb.get("experiment_history", [])
    print(f"\n--- Experiment History ({len(history)} entries) ---")


def add_recipe(kb, app, change, before_json, after_json, tags=None):
    """Add a tuning recipe."""
    recipes = kb.setdefault("tuning_recipes", [])
    recipe_id = f"recipe_{len(recipes) + 1:03d}"

    before = json.loads(before_json) if isinstance(before_json, str) else before_json
    after = json.loads(after_json) if isinstance(after_json, str) else after_json

    # Compute improvement summary
    improvements = []
    if "fps" in before and "fps" in after:
        delta = (after["fps"] - before["fps"]) / before["fps"] * 100
        improvements.append(f"FPS {delta:+.0f}%")
    if "latency_ms" in before and "latency_ms" in after:
        delta = (after["latency_ms"] - before["latency_ms"]) / before["latency_ms"] * 100
        improvements.append(f"latency {delta:+.0f}%")

    recipe = {
        "id": recipe_id,
        "timestamp": datetime.now().isoformat(),
        "app": app,
        "change": change,
        "metrics_before": before,
        "metrics_after": after,
        "improvement": ", ".join(improvements) if improvements else "see metrics",
        "tags": tags or [],
    }

    recipes.append(recipe)
    save_kb(kb)
    print(f"Added recipe {recipe_id}: {change}")
    return recipe_id


def add_insight(kb, text, tags=None):
    """Add an insight."""
    insights = kb.setdefault("insights", [])
    insight = {
        "text": text,
        "tags": tags or [],
        "timestamp": datetime.now().strftime("%Y-%m-%d"),
    }
    insights.append(insight)
    save_kb(kb)
    print(f"Added insight: {text}")


def query(kb, element=None, tags=None):
    """Query the knowledge base."""
    results = {"recipes": [], "patterns": [], "insights": []}

    for recipe in kb.get("tuning_recipes", []):
        if element and element.lower() in recipe.get("change", "").lower():
            results["recipes"].append(recipe)
        if tags:
            if set(tags) & set(recipe.get("tags", [])):
                results["recipes"].append(recipe)

    for pattern in kb.get("bottleneck_patterns", []):
        if element and element.lower() in pattern.get("pattern", "").lower():
            results["patterns"].append(pattern)
        if element and element.lower() in pattern.get("suggestion", "").lower():
            results["patterns"].append(pattern)

    for insight in kb.get("insights", []):
        if element and element.lower() in insight.get("text", "").lower():
            results["insights"].append(insight)
        if tags:
            if set(tags) & set(insight.get("tags", [])):
                results["insights"].append(insight)

    # Deduplicate
    for key in results:
        seen = set()
        deduped = []
        for item in results[key]:
            item_str = str(item)
            if item_str not in seen:
                seen.add(item_str)
                deduped.append(item)
        results[key] = deduped

    return results


def add_experiment(kb, baseline_dir, experiment_dir, change_description, comparison_data):
    """Record an experiment in history."""
    history = kb.setdefault("experiment_history", [])
    history.append({
        "timestamp": datetime.now().isoformat(),
        "baseline": str(baseline_dir),
        "experiment": str(experiment_dir),
        "change": change_description,
        "results": comparison_data,
    })
    save_kb(kb)


def main():
    parser = argparse.ArgumentParser(description="Pipeline profiling knowledge base")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("show", help="Display knowledge base")

    add_r = sub.add_parser("add-recipe", help="Add a tuning recipe")
    add_r.add_argument("--app", required=True)
    add_r.add_argument("--change", required=True)
    add_r.add_argument("--before", required=True, help="JSON metrics before")
    add_r.add_argument("--after", required=True, help="JSON metrics after")
    add_r.add_argument("--tags", nargs="*", default=[])

    add_i = sub.add_parser("add-insight", help="Add an insight")
    add_i.add_argument("--text", required=True)
    add_i.add_argument("--tags", nargs="*", default=[])

    q = sub.add_parser("query", help="Query knowledge base")
    q.add_argument("--element", default=None)
    q.add_argument("--tags", nargs="*", default=None)

    args = parser.parse_args()
    kb = load_kb()

    if args.command == "show":
        show(kb)
    elif args.command == "add-recipe":
        add_recipe(kb, args.app, args.change, args.before, args.after, args.tags)
    elif args.command == "add-insight":
        add_insight(kb, args.text, args.tags)
    elif args.command == "query":
        results = query(kb, args.element, args.tags)
        print(json.dumps(results, indent=2, default=str))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
