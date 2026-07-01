"""Vercel serverless function for /api/stage — SPARK: LANES."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from spark.webapi import make_handler  # noqa: E402

handler = make_handler("stage")
