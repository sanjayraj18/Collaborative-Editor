from sqlalchemy import create_engine
from config import settings
from sqlalchemy.orm import sessionmaker,declarative_base


engine = create_engine(settings.DATABASE_URL)
sessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = sessionLocal()
    try:
        yield db
    finally:
        db.close()
