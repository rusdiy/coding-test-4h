"""
Document processing service using Docling.

Implements structure-aware PDF parsing with multimodal extraction:
- Text chunking with section-level granularity
- Image extraction with caption linking
- Table extraction with structured data and rendered images
"""
import os
import re
import time
import uuid
import logging
from typing import Dict, Any, List, Optional, Tuple
from sqlalchemy.orm import Session
from PIL import Image as PILImage, ImageDraw, ImageFont

from app.models.document import Document, DocumentChunk, DocumentImage, DocumentTable
from app.services.vector_store import VectorStore
from app.core.config import settings

logger = logging.getLogger(__name__)


class DocumentProcessor:
    """
    Process PDF documents and extract multimodal content using Docling.

    Architecture:
        PDF → Docling → Structured Document
            → Text chunks (with section-aware splitting)
            → Images (saved to disk with captions)
            → Tables (structured JSON + rendered image)
            → Cross-references via metadata
    """

    def __init__(self, db: Session):
        self.db = db
        self.vector_store = VectorStore(db)

    async def process_document(self, file_path: str, document_id: int) -> Dict[str, Any]:
        """
        Process a PDF document end-to-end.

        Steps:
        1. Parse PDF with Docling
        2. Extract images and tables (saving to disk + DB)
        3. Extract text and create structure-aware chunks
        4. Generate embeddings for each chunk
        5. Store everything with cross-referencing metadata
        """
        start_time = time.time()

        try:
            await self._update_document_status(document_id, "processing")

            # Import Docling lazily to avoid slow startup
            from docling.document_converter import DocumentConverter, PdfFormatOption
            from docling.datamodel.base_models import InputFormat
            from docling.datamodel.pipeline_options import PdfPipelineOptions

            # Configure Docling pipeline
            pipeline_options = PdfPipelineOptions()
            pipeline_options.generate_picture_images = True
            pipeline_options.generate_table_images = True
            pipeline_options.images_scale = 2.0

            converter = DocumentConverter(
                format_options={
                    InputFormat.PDF: PdfFormatOption(
                        pipeline_options=pipeline_options
                    )
                }
            )

            logger.info(f"Starting Docling conversion for document {document_id}")
            result = converter.convert(file_path)
            doc = result.document
            logger.info(f"Docling conversion complete for document {document_id}")

            # Count pages
            total_pages = len(doc.pages) if hasattr(doc, 'pages') and doc.pages else 0

            # Phase 1: Extract and save images
            saved_images = await self._extract_and_save_images(doc, result, document_id)

            # Phase 2: Extract and save tables
            saved_tables = await self._extract_and_save_tables(doc, result, document_id)

            # Build page → media ID mappings for cross-referencing
            page_to_images = self._build_page_media_map(saved_images)
            page_to_tables = self._build_page_media_map(saved_tables)

            # Phase 3: Extract text and create structure-aware chunks
            chunks = self._extract_and_chunk_text(
                doc, document_id, page_to_images, page_to_tables
            )

            # Phase 4: Save chunks with embeddings
            await self._save_text_chunks(chunks, document_id)

            # Update document metadata
            document = self.db.query(Document).filter(Document.id == document_id).first()
            if document:
                document.total_pages = total_pages
                document.text_chunks_count = len(chunks)
                document.images_count = len(saved_images)
                document.tables_count = len(saved_tables)
                self.db.commit()

            await self._update_document_status(document_id, "completed")

            processing_time = round(time.time() - start_time, 2)
            logger.info(
                f"Document {document_id} processed: "
                f"{len(chunks)} chunks, {len(saved_images)} images, "
                f"{len(saved_tables)} tables in {processing_time}s"
            )

            return {
                "status": "success",
                "text_chunks": len(chunks),
                "images": len(saved_images),
                "tables": len(saved_tables),
                "processing_time": processing_time,
            }

        except Exception as e:
            error_msg = str(e)
            logger.error(
                f"Error processing document {document_id}: {error_msg}",
                exc_info=True,
            )
            await self._update_document_status(document_id, "error", error_msg)
            return {
                "status": "error",
                "error": error_msg,
                "processing_time": round(time.time() - start_time, 2),
            }

    # =========================================================================
    # Text Extraction & Chunking
    # =========================================================================

    def _extract_and_chunk_text(
        self,
        doc,
        document_id: int,
        page_to_images: Dict[int, List[int]],
        page_to_tables: Dict[int, List[int]],
    ) -> List[Dict[str, Any]]:
        """
        Structure-aware text extraction and chunking.

        Strategy (from DESIGN.md):
        1. Use Docling's document structure (headings, paragraphs)
        2. Group consecutive text elements under the same heading
        3. Split oversized groups with overlap
        4. Attach page + section + cross-reference metadata
        """
        from docling_core.types.doc import TextItem, TableItem, PictureItem

        chunks: List[Dict[str, Any]] = []
        current_section = ""
        current_text_buffer = ""
        current_page = 1
        chunk_index = 0
        caption_texts: List[Tuple[int, str]] = []

        for item, level in doc.iterate_items():
            # Collect captions from tables/pictures for "semantic halo" injection
            if isinstance(item, (TableItem, PictureItem)):
                caption = self._extract_caption(item)
                if caption:
                    page_no = self._get_page_number(item)
                    caption_texts.append((page_no, caption))
                continue

            if not isinstance(item, TextItem):
                continue

            text = item.text.strip() if hasattr(item, 'text') and item.text else ""
            if not text:
                continue

            page_no = self._get_page_number(item)
            current_page = page_no or current_page

            # Check if this is a heading/section header
            if self._is_heading(item, level):
                # Flush current buffer as chunk(s)
                if current_text_buffer.strip():
                    new_chunks = self._create_chunks(
                        current_text_buffer.strip(), document_id, current_page,
                        current_section, chunk_index,
                        page_to_images, page_to_tables, caption_texts,
                    )
                    chunks.extend(new_chunks)
                    chunk_index += len(new_chunks)

                current_section = text
                current_text_buffer = f"## {text}\n\n"
            else:
                current_text_buffer += text + "\n\n"

        # Flush remaining buffer
        if current_text_buffer.strip():
            new_chunks = self._create_chunks(
                current_text_buffer.strip(), document_id, current_page,
                current_section, chunk_index,
                page_to_images, page_to_tables, caption_texts,
            )
            chunks.extend(new_chunks)

        return chunks

    def _is_heading(self, item, level: int) -> bool:
        """Determine if a text item is a heading."""
        label_str = str(getattr(item, 'label', '')).lower()
        heading_labels = ('section_header', 'title', 'heading', 'subtitle')
        if any(h in label_str for h in heading_labels):
            return True
        if level <= 1 and hasattr(item, 'text') and len(item.text.strip()) < 100:
            return True
        return False

    def _create_chunks(
        self, text: str, document_id: int, page_number: int,
        section_heading: str, chunk_start_index: int,
        page_to_images: Dict[int, List[int]],
        page_to_tables: Dict[int, List[int]],
        caption_texts: List[Tuple[int, str]],
    ) -> List[Dict[str, Any]]:
        """Split text into chunks respecting CHUNK_SIZE with CHUNK_OVERLAP."""
        chunk_size = settings.CHUNK_SIZE
        chunk_overlap = settings.CHUNK_OVERLAP

        # Inject relevant captions ("semantic halo" from DESIGN.md)
        relevant_captions = [cap for pg, cap in caption_texts if pg == page_number]
        if relevant_captions:
            text += "\n[Related figures/tables: " + "; ".join(relevant_captions) + "]"

        # If text fits in one chunk, no splitting needed
        if len(text) <= chunk_size:
            return [self._make_chunk(
                text, document_id, page_number, chunk_start_index,
                section_heading, page_to_images, page_to_tables,
            )]

        # Split at paragraph boundaries with overlap
        result_chunks: List[Dict[str, Any]] = []
        paragraphs = text.split("\n\n")
        current_chunk = ""

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue

            if current_chunk and len(current_chunk) + len(para) + 2 > chunk_size:
                result_chunks.append(self._make_chunk(
                    current_chunk.strip(), document_id, page_number,
                    chunk_start_index + len(result_chunks),
                    section_heading, page_to_images, page_to_tables,
                ))
                # Overlap: carry tail of previous chunk
                overlap = current_chunk[-chunk_overlap:] if len(current_chunk) > chunk_overlap else current_chunk
                current_chunk = overlap.strip() + "\n\n" + para
            else:
                current_chunk = (current_chunk + "\n\n" + para).strip() if current_chunk else para

        if current_chunk.strip():
            result_chunks.append(self._make_chunk(
                current_chunk.strip(), document_id, page_number,
                chunk_start_index + len(result_chunks),
                section_heading, page_to_images, page_to_tables,
            ))

        return result_chunks

    def _make_chunk(
        self, content: str, document_id: int, page_number: int,
        chunk_index: int, section_heading: str,
        page_to_images: Dict[int, List[int]],
        page_to_tables: Dict[int, List[int]],
    ) -> Dict[str, Any]:
        """Create a chunk dictionary with cross-reference metadata."""
        return {
            "content": content,
            "document_id": document_id,
            "page_number": page_number,
            "chunk_index": chunk_index,
            "metadata": {
                "section_heading": section_heading,
                "related_images": page_to_images.get(page_number, []),
                "related_tables": page_to_tables.get(page_number, []),
            },
        }

    # =========================================================================
    # Chunk Storage
    # =========================================================================

    async def _save_text_chunks(self, chunks: List[Dict[str, Any]], document_id: int):
        """Save text chunks to database with embeddings via VectorStore."""
        for chunk in chunks:
            try:
                await self.vector_store.store_chunk(
                    content=chunk["content"],
                    document_id=document_id,
                    page_number=chunk["page_number"],
                    chunk_index=chunk["chunk_index"],
                    metadata=chunk["metadata"],
                )
            except Exception as e:
                logger.error(
                    f"Failed to store chunk {chunk['chunk_index']} "
                    f"for document {document_id}: {e}"
                )

    # =========================================================================
    # Image Extraction
    # =========================================================================

    async def _extract_and_save_images(
        self, doc, result, document_id: int
    ) -> List[Dict[str, Any]]:
        """Extract images from Docling document and save to disk + DB."""
        from docling_core.types.doc import PictureItem

        saved: List[Dict[str, Any]] = []

        for item, _level in doc.iterate_items():
            if not isinstance(item, PictureItem):
                continue
            try:
                page_no = self._get_page_number(item)
                caption = self._extract_caption(item)

                pil_image = self._get_item_image(item, result)
                if pil_image is None:
                    logger.warning(f"Could not extract image on page {page_no}")
                    continue

                # Save to disk
                filename = f"{uuid.uuid4()}.png"
                file_path = os.path.join(settings.UPLOAD_DIR, "images", filename)
                pil_image.save(file_path, "PNG")
                width, height = pil_image.size

                db_image = DocumentImage(
                    document_id=document_id, file_path=file_path,
                    page_number=page_no, caption=caption,
                    width=width, height=height,
                    metadata={"source": "docling"},
                )
                self.db.add(db_image)
                self.db.commit()
                self.db.refresh(db_image)

                saved.append({"id": db_image.id, "page_number": page_no, "caption": caption})
                logger.info(f"Saved image {db_image.id} from page {page_no}")

            except Exception as e:
                logger.error(f"Failed to extract image: {e}")

        return saved

    # =========================================================================
    # Table Extraction
    # =========================================================================

    async def _extract_and_save_tables(
        self, doc, result, document_id: int
    ) -> List[Dict[str, Any]]:
        """Extract tables from Docling document and save to disk + DB."""
        from docling_core.types.doc import TableItem

        saved: List[Dict[str, Any]] = []

        for item, _level in doc.iterate_items():
            if not isinstance(item, TableItem):
                continue
            try:
                page_no = self._get_page_number(item)
                caption = self._extract_caption(item)

                # Extract structured data
                table_data = None
                num_rows, num_cols = 0, 0

                if hasattr(item, 'export_to_dataframe'):
                    try:
                        df = item.export_to_dataframe()
                        table_data = df.to_dict(orient='records')
                        num_rows, num_cols = len(df), len(df.columns)
                    except Exception:
                        logger.warning(f"Could not export table to dataframe on page {page_no}")

                # Try to get table image from Docling
                pil_image = self._get_item_image(item, result)

                # Fallback: render from structured data
                if pil_image is None and table_data:
                    pil_image = self._render_table_image(table_data, caption)

                # Fallback: render from HTML
                if pil_image is None and hasattr(item, 'export_to_html'):
                    try:
                        html = item.export_to_html()
                        if html:
                            pil_image = self._render_html_table_image(html, caption)
                    except Exception:
                        pass

                if pil_image is None:
                    logger.warning(f"Could not create table image for page {page_no}")
                    continue

                # Save image
                filename = f"{uuid.uuid4()}.png"
                file_path = os.path.join(settings.UPLOAD_DIR, "tables", filename)
                pil_image.save(file_path, "PNG")

                db_table = DocumentTable(
                    document_id=document_id, image_path=file_path,
                    data=table_data, page_number=page_no,
                    caption=caption, rows=num_rows, columns=num_cols,
                    metadata={"source": "docling"},
                )
                self.db.add(db_table)
                self.db.commit()
                self.db.refresh(db_table)

                saved.append({"id": db_table.id, "page_number": page_no, "caption": caption})
                logger.info(f"Saved table {db_table.id} from page {page_no}")

            except Exception as e:
                logger.error(f"Failed to extract table: {e}")

        return saved

    # =========================================================================
    # Helpers
    # =========================================================================

    def _get_page_number(self, item) -> int:
        """Extract page number from a Docling item's provenance."""
        if hasattr(item, 'prov') and item.prov:
            return item.prov[0].page_no
        return 1

    def _extract_caption(self, item) -> Optional[str]:
        """Extract caption text from a Docling item (multiple strategies)."""
        if hasattr(item, 'caption_text') and item.caption_text:
            return item.caption_text
        if hasattr(item, 'captions') and item.captions:
            texts = []
            for cap in item.captions:
                t = cap.text if hasattr(cap, 'text') else str(cap) if cap else None
                if t:
                    texts.append(t)
            if texts:
                return " ".join(texts)
        if hasattr(item, 'caption') and item.caption:
            if isinstance(item.caption, str):
                return item.caption
            if hasattr(item.caption, 'text'):
                return item.caption.text
        return None

    def _get_item_image(self, item, result) -> Optional[PILImage.Image]:
        """Try multiple strategies to get a PIL Image from a Docling item."""
        # Strategy 1: Direct .image attribute
        if hasattr(item, 'image') and item.image is not None:
            img = item.image
            if isinstance(img, PILImage.Image):
                return img
            if hasattr(img, 'pil_image'):
                return img.pil_image

        # Strategy 2: get_image method
        if hasattr(item, 'get_image'):
            try:
                img = item.get_image(result)
                if img is not None:
                    return img if isinstance(img, PILImage.Image) else getattr(img, 'pil_image', None)
            except Exception:
                pass

        # Strategy 3: Crop from page render
        try:
            if hasattr(item, 'prov') and item.prov and hasattr(result, 'pages'):
                prov = item.prov[0]
                page = result.pages.get(prov.page_no)
                if page and hasattr(page, 'image') and isinstance(page.image, PILImage.Image):
                    if hasattr(prov, 'bbox') and prov.bbox:
                        bbox = prov.bbox
                        if hasattr(bbox, 'l'):
                            return page.image.crop((bbox.l, bbox.t, bbox.r, bbox.b))
                        elif isinstance(bbox, (list, tuple)) and len(bbox) == 4:
                            return page.image.crop(tuple(bbox))
        except Exception:
            pass

        return None

    def _render_table_image(
        self, table_data: List[Dict[str, Any]], caption: Optional[str] = None
    ) -> PILImage.Image:
        """Render structured table data as a PNG image using Pillow."""
        if not table_data:
            img = PILImage.new('RGB', (400, 100), 'white')
            ImageDraw.Draw(img).text((10, 10), "Empty table", fill='black')
            return img

        headers = list(table_data[0].keys())
        rows = [[str(row.get(h, '')) for h in headers] for row in table_data]

        cell_pad = 10
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 12)
            bold = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 12)
        except (IOError, OSError):
            font = bold = ImageFont.load_default()

        col_widths = [
            min(max(len(h) * 8, max((len(r[i]) * 7 for r in rows), default=0)) + cell_pad * 2, 250)
            for i, h in enumerate(headers)
        ]
        row_h, hdr_h = 30, 35
        w = sum(col_widths) + 20
        h = hdr_h + row_h * len(rows) + 20 + (30 if caption else 0)

        img = PILImage.new('RGB', (w, h), 'white')
        draw = ImageDraw.Draw(img)
        y = 10

        if caption:
            draw.text((10, y), caption, fill='#333', font=bold)
            y += 30

        # Header
        draw.rectangle([(10, y), (w - 10, y + hdr_h)], fill='#E8E8E8')
        x = 10
        for i, hdr in enumerate(headers):
            draw.text((x + cell_pad, y + 8), str(hdr)[:30], fill='#333', font=bold)
            x += col_widths[i]
        y += hdr_h

        # Rows
        for ri, row in enumerate(rows):
            bg = '#F8F8F8' if ri % 2 == 0 else 'white'
            draw.rectangle([(10, y), (w - 10, y + row_h)], fill=bg)
            x = 10
            for i, cell in enumerate(row):
                if i < len(col_widths):
                    draw.text((x + cell_pad, y + 6), str(cell)[:35], fill='#555', font=font)
                    x += col_widths[i]
            y += row_h

        return img

    def _render_html_table_image(self, html: str, caption: Optional[str] = None) -> PILImage.Image:
        """Fallback: render HTML table as plain text image."""
        text = re.sub(r'<[^>]+>', ' ', html)
        text = re.sub(r'\s+', ' ', text).strip()
        if caption:
            text = f"{caption}\n\n{text}"

        lines = []
        for line in text.split('\n'):
            while len(line) > 80:
                lines.append(line[:80])
                line = line[80:]
            lines.append(line)

        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 12)
        except (IOError, OSError):
            font = ImageFont.load_default()

        img = PILImage.new('RGB', (680, max(len(lines) * 18 + 40, 60)), 'white')
        draw = ImageDraw.Draw(img)
        for i, line in enumerate(lines[:50]):
            draw.text((20, 20 + i * 18), line, fill='#333', font=font)
        return img

    def _build_page_media_map(self, saved_items: List[Dict[str, Any]]) -> Dict[int, List[int]]:
        """Build a mapping of page_number → list of media IDs."""
        page_map: Dict[int, List[int]] = {}
        for item in saved_items:
            page = item.get("page_number", 1)
            page_map.setdefault(page, []).append(item["id"])
        return page_map

    async def _update_document_status(
        self, document_id: int, status: str, error_message: str = None
    ):
        """Update document processing status in database."""
        document = self.db.query(Document).filter(Document.id == document_id).first()
        if document:
            document.processing_status = status
            if error_message:
                document.error_message = error_message
            self.db.commit()
