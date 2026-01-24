from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    ADMIN_LOGIN: str
    ADMIN_PASSWORD: str
    SECRET_KEY: str
    DATABASE_URL: str

    class Config:
        env_file = ".env"

settings = Settings()
