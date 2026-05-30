from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "Fund Holdings Analyzer"
    secret_key: str = "change-me"
    database_url: str = "mysql+pymysql://root:password@127.0.0.1:3306/fund_app"
    session_cookie_name: str = "fund_session"


settings = Settings()
