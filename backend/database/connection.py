"""
Database connection setup using SQLAlchemy with async support.

This module handles:
- Async database engine creation
- Async session management
- Database initialization with retry logic
- Sync fallback for compatibility
- Automatic table creation for local debug mode
"""

import os
import time
import asyncio
from typing import AsyncGenerator
from urllib.parse import quote_plus
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import QueuePool, NullPool
from sqlalchemy.exc import OperationalError
from contextlib import contextmanager, asynccontextmanager

from .models import Base
from backend.config.db_config import SYNC_DATABASE_URL, ASYNC_DATABASE_URL, DB_CONNECT_RETRIES, DB_CONNECT_RETRY_DELAY

from backend.utils import log

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


def wait_for_db(max_retries: int = DB_CONNECT_RETRIES, retry_delay: int = DB_CONNECT_RETRY_DELAY) -> bool:
    """
    Wait for database to be ready with retry logic.
    
    Args:
        max_retries: Maximum number of connection attempts
        retry_delay: Seconds to wait between retries
        
    Returns:
        True if connection successful, False otherwise
    """
    for attempt in range(1, max_retries + 1):
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            log.info(f"✓ Database connection established (attempt {attempt})")
            return True
        except OperationalError as e:
            if attempt < max_retries:
                log.info(f"⏳ Waiting for database... (attempt {attempt}/{max_retries})")
                time.sleep(retry_delay)
            else:
                log.error(f"✗ Database connection failed after {max_retries} attempts: {e}")
                return False
    # This should never be reached, but satisfies type checker
    return False


def init_db(retry: bool = True) -> bool:
    """
    Initialize the database by creating all tables.
    
    Waits for database to be ready and creates all tables defined in models.
    
    Args:
        retry: Whether to retry connection if database is not ready
        
    Returns:
        True if initialization successful, False otherwise
    """
    if retry:
        if not wait_for_db():
            return False
    
    try:
        Base.metadata.create_all(bind=engine)
        log.info("✓ Database tables created successfully")
        return True
    except Exception as e:
        log.error(f"✗ Database initialization failed: {e}")
        return False


async def async_wait_for_db(max_retries: int = DB_CONNECT_RETRIES, retry_delay: int = DB_CONNECT_RETRY_DELAY) -> bool:
    """
    Async version: Wait for database to be ready with retry logic.
    
    Args:
        max_retries: Maximum number of connection attempts
        retry_delay: Seconds to wait between retries
        
    Returns:
        True if connection successful, False otherwise
    """
    if async_engine is None:
        # Fallback to sync version
        return wait_for_db(max_retries, retry_delay)
    
    for attempt in range(1, max_retries + 1):
        try:
            async with async_engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            log.info(f"✓ Database connection established (attempt {attempt})")
            return True
        except OperationalError as e:
            if attempt < max_retries:
                log.info(f"⏳ Waiting for database... (attempt {attempt}/{max_retries})")
                await asyncio.sleep(retry_delay)
            else:
                log.error(f"✗ Database connection failed after {max_retries} attempts: {e}")
                return False
    # This should never be reached, but satisfies type checker
    return False


async def async_init_db(retry: bool = True) -> bool:
    """
    Async version of database initialization.
    
    Waits for database to be ready and creates all tables asynchronously.
    
    Args:
        retry: Whether to retry connection if database is not ready
        
    Returns:
        True if initialization successful, False otherwise
    """
    if async_engine is None:
        # Fallback to sync initialization
        return init_db(retry)
    
    if retry:
        if not await async_wait_for_db():
            return False
    
    try:
        async with async_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        log.info("✓ Database tables created successfully (async)")
        return True
    except Exception as e:
        log.error(f"✗ Async database initialization failed: {e}")
        return False


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
