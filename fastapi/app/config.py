import os
from dataclasses import dataclass


@dataclass
class Settings:
    database_url: str = 'sqlite:///./willow.db'
    webhook_secret: str = ''
    frontend_origin: str = 'http://localhost:5173'
    programs_path: str = 'fixtures/programs.json'

    @classmethod
    def from_env(cls):
        from dotenv import load_dotenv
        load_dotenv()
        return cls(**{name: os.environ[name.upper()] for name in cls.__dataclass_fields__
                      if os.getenv(name.upper()) is not None})
