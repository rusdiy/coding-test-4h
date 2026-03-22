"""
Application configuration
"""
from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    # API Settings
    API_V1_STR: str = "/api"
    PROJECT_NAME: str = "Multimodal Document Chat"
    
    # Database
    DATABASE_URL: str = "postgresql://docuser:docpass@localhost:5432/docdb"
    
    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"
    
    # Gemini (Google AI)
    GEMINI_API_KEY: Optional[str] = None
    GEMINI_MODEL: str = "gemini-2.0-flash"
    GEMINI_EMBEDDING_MODEL: str = "text-embedding-004"
    
    # Upload Settings
    UPLOAD_DIR: str = "./uploads"
    MAX_FILE_SIZE: int = 50 * 1024 * 1024  # 50 MB
    
    # Vector Store Settings
    EMBEDDING_DIMENSION: int = 768  # Gemini text-embedding-004
    CHUNK_SIZE: int = 1000
    CHUNK_OVERLAP: int = 200
    TOP_K_RESULTS: int = 5
    
    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
