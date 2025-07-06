from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import os
import socket

hostname = socket.gethostname()
if "macbook" in hostname.lower() or os.getenv("ENV") == "local":
    DATABASE_URL = "postgresql://user:password@localhost:5432/stockdb"
else:
    DATABASE_URL = "postgresql://user:password@bip-postgres:5432/stockdb"

#DATABASE_URL = "postgresql://user:password@postgres:5432/stockdb"

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
