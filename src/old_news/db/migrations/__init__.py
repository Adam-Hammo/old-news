"""Piccolo migrations.

This file exists so the directory survives a clone: git does not track empty
directories, and `piccolo_app.py` points `migrations_folder_path` here. Without it a
fresh checkout — CI, or the Docker image — fails with FileNotFoundError before any
migration runs.
"""
