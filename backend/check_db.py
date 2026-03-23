import asyncio
from sqlalchemy.orm import Session
from app.db.session import SessionLocal
from app.models.document import DocumentImage, DocumentChunk, DocumentTable

def check_db():
    db = SessionLocal()
    try:
        images = db.query(DocumentImage).all()
        print(f"Total images in DB: {len(images)}")
        for img in images:
            print(f"ID={img.id}, Doc={img.document_id}, Page={img.page_number}, Path={img.file_path}, Caption={img.caption}")
    finally:
        db.close()

if __name__ == "__main__":
    check_db()
