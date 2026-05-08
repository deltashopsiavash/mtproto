from datetime import datetime
from sqlalchemy import Boolean, Column, DateTime, Integer, String, BigInteger
from .db import Base

class Admin(Base):
    __tablename__ = "admins"
    id = Column(Integer, primary_key=True)
    username = Column(String(80), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)

class ProxyUser(Base):
    __tablename__ = "proxy_users"
    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True, nullable=False)
    secret = Column(String(128), unique=True, nullable=False)
    port = Column(Integer, unique=True, nullable=False)
    traffic_limit_bytes = Column(BigInteger, default=0) # 0 = unlimited
    traffic_used_bytes = Column(BigInteger, default=0)
    expires_at = Column(DateTime, nullable=True)
    sponsor_tag = Column(String(128), nullable=True)
    container_name = Column(String(128), unique=True, nullable=False)
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_seen = Column(DateTime, nullable=True)
