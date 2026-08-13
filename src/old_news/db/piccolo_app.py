from pathlib import Path

from piccolo.conf.apps import AppConfig

# No tables yet. Procrastinate's mirrors in tables/procrastinate.py are
# deliberately absent — procrastinate owns that schema and migrates it itself.
APP_CONFIG = AppConfig(
    app_name="old_news",
    table_classes=[],
    migrations_folder_path=str(Path(__file__).parent / "migrations"),
)
