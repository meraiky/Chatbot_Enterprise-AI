from sqlalchemy import Column, Integer, Text, Boolean, DateTime, JSON, String, func
from sqlalchemy.sql import func as sql_func
from pgvector.sqlalchemy import Vector
from app.models.base import Base

class QACache(Base):
    __tablename__ = "qa_cache"

    id = Column(Integer, primary_key=True, autoincrement=True)
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    sources = Column(JSON, nullable=False, server_default='[]')
    mode = Column(Text, nullable=False)
    embedding = Column(Vector(768))
    question_tokens = Column(Integer, nullable=False, default=0)
    answer_tokens = Column(Integer, nullable=False, default=0)
    total_tokens = Column(Integer, nullable=False, default=0)
    hit_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=sql_func.now())
    last_hit_at = Column(DateTime(timezone=True))

class TopicGuard(Base):
    __tablename__ = "topic_guard"

    id = Column(Integer, primary_key=True, autoincrement=True)
    pattern = Column(Text, nullable=False)
    mode = Column(Text)
    reason = Column(Text)
    is_regex = Column(Boolean, nullable=False, default=False)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=sql_func.now())

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(Text, nullable=False, unique=True)
    hashed_password = Column(Text, nullable=False)
    role = Column(Text, nullable=False, default="user")
    can_manage_models = Column(Boolean, nullable=False, default=False)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=sql_func.now())
