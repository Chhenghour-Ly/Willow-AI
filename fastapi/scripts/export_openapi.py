"""Generate the same OpenAPI document served by FastAPI without touching case data."""
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import Settings
from app.main import create_app


def main():
    with TemporaryDirectory() as directory:
        app = create_app(Settings(database_url=f'sqlite:///{Path(directory) / "schema.db"}'))
        schema = app.openapi()
        Path('docs/openapi.json').write_text(json.dumps(schema, indent=2)+'\n', encoding='utf-8')
        app.state.db.engine.dispose()


if __name__ == '__main__':
    main()
