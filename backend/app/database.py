import os
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///./redealer.db')
# Hosts such as Render hand out postgres:// or postgresql:// URLs; SQLAlchemy needs the driver named.
for _prefix in ('postgres://', 'postgresql://'):
    if DATABASE_URL.startswith(_prefix):
        DATABASE_URL = 'postgresql+psycopg://' + DATABASE_URL[len(_prefix):]
        break
connect_args = {'check_same_thread': False} if DATABASE_URL.startswith('sqlite') else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

class Base(DeclarativeBase):
    pass

def get_db():
    with SessionLocal() as session:
        yield session
