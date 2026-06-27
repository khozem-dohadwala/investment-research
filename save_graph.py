#!/usr/bin/env python3
"""
Quick save / snapshot helper.

Usage:

  PYTHONPATH=backend/app python3 save_graph.py

Exports current data/graph.db contents to data/graph.json (the portable snapshot).
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend", "app"))

from models.graph import GraphStore

def main():
    db_path = "data/graph.db"
    json_path = "data/graph.json"

    print(f"Saving current state from {db_path} to {json_path} ...")
    store = GraphStore(db_path)
    out = store.export_json(json_path)
    store.close()

    print(f"Saved snapshot to {out}")

if __name__ == "__main__":
    main()
