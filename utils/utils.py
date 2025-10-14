# utils/config.py
from dotenv import load_dotenv
from pydantic import BaseSettings

load_dotenv()

class Settings(BaseSettings):
    BOT_TOKEN: str
    ADMINS: str
    MARZBAN_HOST: str
    MARZBAN_USER_VIP: str
    MARZBAN_PASS_VIP: str
    MARZBAN_USER_TEST: str
    MARZBAN_PASS_TEST: str
    MARZBAN_USER_FREE: str
    MARZBAN_PASS_FREE: str
    DB_HOST: str
    DB_PORT: int
    DB_NAME: str
    DB_USER: str
    DB_PASSWORD: str

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

settings = Settings()
