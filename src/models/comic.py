from sqlalchemy import Column, Integer, String, Enum, JSON, Text, TIMESTAMP
from sqlalchemy.orm import declarative_base

Base = declarative_base()

class Comic(Base):
    __tablename__ = 'comics'

    id = Column(Integer, primary_key=True)
    title = Column(String, nullable=False)
    author = Column(String, nullable=False)
    type = Column(Enum('manga', 'manhwa', 'manhua', name='comic_type'), nullable=False)
    status = Column(Enum('ongoing', 'completed', name='comic_status'), nullable=False)
    release = Column(String, nullable=False)
    updated_on = Column(TIMESTAMP, nullable=False)
    genres = Column(JSON, nullable=False)
    synopsis = Column(Text, nullable=False)
    rating = Column(String)
    cover_image_url = Column(String, nullable=False)
    slug = Column(String, nullable=False, unique=True)

    def __repr__(self):
        return f"<Comic(title='{self.title}', author='{self.author}', type='{self.type}')>"
