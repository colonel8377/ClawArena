"""
Database connection setup using SQLAlchemy with async support.

This module handles:
- Async database engine creation
- Async session management
- Database initialization
- Sync fallback for compatibility
"""

import os
from typing import AsyncGenerator
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import QueuePool, NullPool
from contextlib import contextmanager, asynccontextmanager

from .models import Base

# Database configuration from environment
DB_USER = os.getenv('DB_USER', 'root')
DB_PASSWORD = os.getenv('DB_PASSWORD', '')
DB_HOST = os.getenv('DB_HOST', 'localhost')
DB_PORT = os.getenv('DB_PORT', '3306')
DB_NAME = os.getenv('DB_NAME', 'agent_arena')

# Create sync database URL (for backwards compatibility)
SYNC_DATABASE_URL = f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# Create async database URL
ASYNC_DATABASE_URL = f"mysql+aiomysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# Create sync engine with connection pooling (for backwards compatibility)
engine = create_engine(
    SYNC_DATABASE_URL,
    poolclass=QueuePool,
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,  # Verify connections before using
    echo=False  # Set to True for SQL logging during development
)

# Create async engine
# Note: Using NullPool for async connections because:
# 1. Async SQLAlchemy connections cannot be safely shared across event loop iterations
# 2. Connection pooling with async can cause "connection is closed" errors during idle periods
# 3. NullPool creates fresh connections for each operation, avoiding stale connection issues
try:
    async_engine = create_async_engine(
        ASYNC_DATABASE_URL,
        poolclass=NullPool,
        echo=False
    )
except Exception:
    # Fallback if aiomysql is not installed
    async_engine = None

# Create sync session factory (for backwards compatibility)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Create async session factory
if async_engine:
    AsyncSessionLocal = async_sessionmaker(
        async_engine, 
        class_=AsyncSession, 
        expire_on_commit=False,
        autocommit=False,
        autoflush=False
    )
else:
    AsyncSessionLocal = None


def init_db():
    """
    Initialize the database by creating all tables.
    
    This should be called once at application startup.
    """
    Base.metadata.create_all(bind=engine)
    print("Database initialized successfully")


async def async_init_db():
    """
    Async version of database initialization.
    
    Creates all tables asynchronously.
    """
    if async_engine is None:
        # Fallback to sync initialization
        init_db()
        return
    
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("Async database initialized successfully")


@contextmanager
def get_db_session() -> Session:
    """
    Context manager for database sessions (sync).
    
    Yields:
        Session: SQLAlchemy database session
        
    Usage:
        with get_db_session() as db:
            user = db.query(User).filter_by(wallet_address=address).first()
    """
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@asynccontextmanager
async def get_async_db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Async context manager for database sessions.
    
    Yields:
        AsyncSession: SQLAlchemy async database session
        
    Usage:
        async with get_async_db_session() as db:
            result = await db.execute(select(User).filter_by(wallet_address=address))
            user = result.scalar_one_or_none()
    """
    if AsyncSessionLocal is None:
        raise RuntimeError("Async database not configured. Install aiomysql.")
    
    session = AsyncSessionLocal()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


def get_db():
    """
    Dependency for FastAPI endpoints (sync).
    
    Yields:
        Session: SQLAlchemy database session
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


async def get_async_db():
    """
    Async dependency for FastAPI endpoints.
    
    Yields:
        AsyncSession: SQLAlchemy async database session
    """
    if AsyncSessionLocal is None:
        raise RuntimeError("Async database not configured. Install aiomysql.")
    
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
