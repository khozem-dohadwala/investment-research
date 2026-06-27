#!/usr/bin/env python3
"""
Quick restore helper for the Investment Research graph.

Usage (from project root):

  PYTHONPATH=backend/app python3 restore_graph.py

This loads the latest data/graph.json snapshot into data/graph.db.
"""

import os
import sys

# Make sure we can import the models
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend", "app"))

from models.graph import GraphStore

def main():
    json_path = "data/graph.json"
    db_path = "data/graph.db"

    if not os.path.exists(json_path):
        print(f"ERROR: {json_path} not found. Nothing to restore.")
        sys.exit(1)

    print(f"Restoring graph from {json_path} into {db_path} ...")
    store = GraphStore(db_path)
    n, e = store.import_json(json_path, clear_first=True)
    store.close()

    print(f"Done. Graph now has {n} nodes and {e} edges.")
    print("You can now run discovery commands, example_graph, or start the API.")

if __name__ == "__main__":
    main()
