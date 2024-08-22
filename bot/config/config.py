from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_ignore_empty=True)

    API_ID: int
    API_HASH: str

    AUTO_TAP: bool = True
    AUTO_MISSION: bool = True
    AUTO_LVL_UP: bool = True
    PLAY_WALK_GAME: bool = True
    PLAY_SHOOT_GAME: bool = True
    PLAY_RPG_GAME: bool = True
    PLAY_DIRTY_JOB_GAME: bool = True
    PLAY_HURTMEPLEASE_GAME: bool = True

    AUTO_BUY_PASS: bool = True

    REF_ID: str = ''

    USE_PROXY_FROM_FILE: bool = False


settings = Settings()


