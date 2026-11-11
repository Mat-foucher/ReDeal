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

def add_missing_columns():
    """Tiny forward-only migration: add new nullable columns to tables that already exist.
    create_all() makes new tables but never alters old ones, so older local databases keep working."""
    from sqlalchemy import inspect, text
    insp = inspect(engine)
    for table in Base.metadata.sorted_tables:
        if not insp.has_table(table.name):
            continue
        existing = {c['name'] for c in insp.get_columns(table.name)}
        for col in table.columns:
            if col.name not in existing and col.nullable:
                with engine.begin() as conn:
                    conn.execute(text(f'ALTER TABLE {table.name} ADD COLUMN {col.name} {col.type.compile(engine.dialect)}'))

def get_db():
    with SessionLocal() as session:
        yield session
