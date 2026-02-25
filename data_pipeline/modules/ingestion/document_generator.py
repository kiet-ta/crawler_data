"""
Document Generator Module

This module generates synthetic real estate documents (PDFs and images) with
realistic PII data and simulates scanned document appearance using OpenCV filters.

Why synthetic data: Generating synthetic documents allows us to create a controlled
dataset with known PII locations, which is essential for training and validating
ML models without privacy concerns.
"""

import random
import string
from typing import List, Tuple, Dict, Any
from pathlib import Path
import numpy as np
import cv2
from PIL import Image, ImageDraw, ImageFont
from datetime import datetime, timedelta
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from config import PipelineConfig
from utils.logger import setup_logger, log_with_context


logger = setup_logger(__name__)


class VietnameseNameGenerator:
    """
    Generator for realistic Vietnamese names.
    
    Why: Using authentic Vietnamese names with proper diacritics makes the
    synthetic data more representative of real-world documents.
    """
    
    # Common Vietnamese surnames
    SURNAMES = [
        "Nguyễn", "Trần", "Lê", "Phạm", "Hoàng", "Phan", "Vũ", "Võ", "Đặng", "Bùi",
        "Đỗ", "Hồ", "Ngô", "Dương", "Lý", "Đinh", "Trương", "Mai", "Lưu", "Hà"
    ]
    
    # Common Vietnamese middle names
    MIDDLE_NAMES = [
        "Văn", "Thị", "Hữu", "Đức", "Minh", "Anh", "Công", "Quang", "Thanh", "Hoài"
    ]
    
    # Common Vietnamese given names
    GIVEN_NAMES_MALE = [
        "Hùng", "Dũng", "Tùng", "Kiên", "Phong", "Hải", "Nam", "Long", "Tuấn", "Cường",
        "Khoa", "Thắng", "Huy", "Bình", "Thiện", "Đạt", "Hiếu", "Quân", "Tâm", "Nhân"
    ]
    
    GIVEN_NAMES_FEMALE = [
        "Linh", "Hoa", "Mai", "Lan", "Thu", "Hương", "Ngọc", "Hạnh", "Thảo", "Trang",
        "Huyền", "Phương", "Yến", "Chi", "My", "Vy", "Diệp", "Xuân", "Nga", "Dung"
    ]
    
    @classmethod
    def generate(cls, gender: str = "random") -> str:
        """
        Generate a random Vietnamese full name.
        
        Args:
            gender: 'male', 'female', or 'random'
            
        Returns:
            Full Vietnamese name with proper diacritics
        """
        if gender == "random":
            gender = random.choice(["male", "female"])
            
        surname = random.choice(cls.SURNAMES)
        middle = random.choice(cls.MIDDLE_NAMES)
        
        if gender == "male":
            given = random.choice(cls.GIVEN_NAMES_MALE)
        else:
            given = random.choice(cls.GIVEN_NAMES_FEMALE)
            
        return f"{surname} {middle} {given}"


class DocumentDataGenerator:
    """
    Generates realistic PII data for Vietnamese real estate documents.
    
    Why: Centralized data generation ensures consistency across all synthetic
    documents and makes it easy to control the distribution of different data types.
    """
    
    @staticmethod
    def generate_cccd() -> str:
        """
        Generate a random 12-digit Citizen ID (CCCD).
        
        Returns:
            12-digit string
            
        Why 12 digits: Vietnamese CCCD follows a specific 12-digit format.
        While these are random, they match the pattern OCR will be trained to detect.
        """
        return ''.join(random.choices(string.digits, k=12))
        
    @staticmethod
    def generate_dob() -> str:
        """
        Generate a random date of birth in Vietnamese format.
        
        Returns:
            Date string in DD/MM/YYYY format
        """
        # Generate DOB between 1960 and 2000
        start_date = datetime(1960, 1, 1)
        end_date = datetime(2000, 12, 31)
        
        delta = end_date - start_date
        random_days = random.randint(0, delta.days)
        dob = start_date + timedelta(days=random_days)
        
        return dob.strftime("%d/%m/%Y")
        
    @staticmethod
    def generate_phone() -> str:
        """
        Generate a Vietnamese mobile phone number.
        
        Returns:
            10-digit phone number starting with 0
        """
        prefixes = ['09', '08', '07', '05', '03']  # Common Vietnamese mobile prefixes
        prefix = random.choice(prefixes)
        remaining = ''.join(random.choices(string.digits, k=8))
        return f"{prefix}{remaining}"
        
    @staticmethod
    def generate_address() -> str:
        """
        Generate a synthetic Vietnamese address.
        
        Returns:
            Address string
        """
        streets = ["Nguyễn Trãi", "Lê Lợi", "Trần Hưng Đạo", "Hai Bà Trưng", "Cách Mạng Tháng 8"]
        districts = ["Quận 1", "Quận 3", "Quận 5", "Quận Bình Thạnh", "Quận Tân Bình"]
        cities = ["TP. Hồ Chí Minh", "Hà Nội", "Đà Nẵng", "Cần Thơ"]
        
        number = random.randint(1, 500)
        street = random.choice(streets)
        district = random.choice(districts)
        city = random.choice(cities)
        
        return f"{number} {street}, {district}, {city}"


class PDFDocumentGenerator:
    """
    Generates synthetic PDF documents simulating real estate contracts.
    
    Why PDF: PDFs are the most common format for official documents in Vietnam.
    Using ReportLab allows precise control over text placement, which is crucial
    for tracking PII locations.
    """
    
    def __init__(self):
        """Initialize the PDF generator."""
        self.data_generator = DocumentDataGenerator()
        self.name_generator = VietnameseNameGenerator()
        
    def _create_contract_template(
        self, 
        pdf_canvas: canvas.Canvas, 
        doc_type: str,
        page_num: int
    ) -> List[Dict[str, Any]]:
        """
        Create a contract page template with PII placeholders.
        
        Args:
            pdf_canvas: ReportLab canvas object
            doc_type: Type of document (sales_contract, deposit_contract, etc.)
            page_num: Current page number
            
        Returns:
            List of dictionaries tracking PII locations
            
        Why: Templates provide structure while allowing us to inject controlled
        PII data and track its exact location for later redaction.
        """
        pii_locations = []
        width, height = A4
        
        # Title
        pdf_canvas.setFont("Helvetica-Bold", 16)
        title_map = {
            "sales_contract": "HỢP ĐỒNG MUA BÁN NHÀ ĐẤT",
            "deposit_contract": "HỢP ĐỒNG ĐẶT CỌC BẤT ĐỘNG SẢN",
            "lease_agreement": "HỢP ĐỒNG THUÊ NHÀ"
        }
        title = title_map.get(doc_type, "HỢP ĐỒNG")
        pdf_canvas.drawCentredString(width / 2, height - 80, title)
        
        # Only add PII data on first page to avoid duplication
        if page_num == 0:
            pdf_canvas.setFont("Helvetica", 11)
            y_position = height - 150
            
            # Party A (Seller/Landlord)
            pdf_canvas.drawString(100, y_position, "BÊN A (Bên bán/cho thuê):")
            y_position -= 25
            
            name_a = self.name_generator.generate()
            pdf_canvas.drawString(100, y_position, f"Ông/Bà: {name_a}")
            pii_locations.append({
                "type": "name",
                "value": name_a,
                "page": page_num,
                "approx_position": (100, height - y_position)
            })
            y_position -= 20
            
            cccd_a = self.data_generator.generate_cccd()
            pdf_canvas.drawString(100, y_position, f"CCCD số: {cccd_a}")
            pii_locations.append({
                "type": "cccd",
                "value": cccd_a,
                "value_length": 12,
                "page": page_num,
                "approx_position": (100, height - y_position)
            })
            y_position -= 20
            
            dob_a = self.data_generator.generate_dob()
            pdf_canvas.drawString(100, y_position, f"Ngày sinh: {dob_a}")
            pii_locations.append({
                "type": "dob",
                "value": dob_a,
                "page": page_num,
                "approx_position": (100, height - y_position)
            })
            y_position -= 20
            
            phone_a = self.data_generator.generate_phone()
            pdf_canvas.drawString(100, y_position, f"Điện thoại: {phone_a}")
            pii_locations.append({
                "type": "phone",
                "value": phone_a,
                "page": page_num,
                "approx_position": (100, height - y_position)
            })
            y_position -= 40
            
            # Party B (Buyer/Tenant)
            pdf_canvas.drawString(100, y_position, "BÊN B (Bên mua/thuê):")
            y_position -= 25
            
            name_b = self.name_generator.generate()
            pdf_canvas.drawString(100, y_position, f"Ông/Bà: {name_b}")
            pii_locations.append({
                "type": "name",
                "value": name_b,
                "page": page_num,
                "approx_position": (100, height - y_position)
            })
            y_position -= 20
            
            cccd_b = self.data_generator.generate_cccd()
            pdf_canvas.drawString(100, y_position, f"CCCD số: {cccd_b}")
            pii_locations.append({
                "type": "cccd",
                "value": cccd_b,
                "value_length": 12,
                "page": page_num,
                "approx_position": (100, height - y_position)
            })
            y_position -= 20
            
            dob_b = self.data_generator.generate_dob()
            pdf_canvas.drawString(100, y_position, f"Ngày sinh: {dob_b}")
            pii_locations.append({
                "type": "dob",
                "value": dob_b,
                "page": page_num,
                "approx_position": (100, height - y_position)
            })
            
            # Add some boilerplate contract text
            y_position -= 40
            pdf_canvas.drawString(100, y_position, "Hai bên thỏa thuận ký kết hợp đồng với các điều khoản sau:")
            
        else:
            # Subsequent pages - just boilerplate
            pdf_canvas.setFont("Helvetica", 11)
            y_position = height - 150
            pdf_canvas.drawString(100, y_position, f"Trang {page_num + 1}")
            y_position -= 30
            pdf_canvas.drawString(100, y_position, "Điều khoản chi tiết về quyền và nghĩa vụ của các bên...")
            
        return pii_locations
        
    def generate_pdf(
        self, 
        output_path: Path, 
        doc_type: str, 
        num_pages: int
    ) -> Dict[str, Any]:
        """
        Generate a complete multi-page PDF document.
        
        Args:
            output_path: Where to save the PDF
            doc_type: Type of contract
            num_pages: Number of pages to generate
            
        Returns:
            Dictionary containing filename, doc_type, and PII locations
            
        Why multi-page: Real contracts are typically multi-page documents.
        This tests the pipeline's ability to handle pagination correctly.
        """
        logger.info(f"Generating PDF: {output_path.name}")
        
        pdf = canvas.Canvas(str(output_path), pagesize=A4)
        all_pii_locations = []
        
        for page_num in range(num_pages):
            pii_locs = self._create_contract_template(pdf, doc_type, page_num)
            all_pii_locations.extend(pii_locs)
            pdf.showPage()
            
        pdf.save()
        
        log_with_context(
            logger, 'info', 'PDF generated',
            filename=output_path.name,
            pages=num_pages,
            pii_count=len(all_pii_locations)
        )
        
        return {
            "filename": output_path.name,
            "doc_type": doc_type,
            "page_count": num_pages,
            "pii_locations": all_pii_locations,
            "generated_at": datetime.utcnow().isoformat()
        }


class ImageDocumentGenerator:
    """
    Generates standalone document images with PII data.
    
    Why images: Some documents are scanned as standalone images rather than PDFs.
    Supporting both formats makes the pipeline more versatile.
    """
    
    def __init__(self):
        """Initialize the image generator."""
        self.data_generator = DocumentDataGenerator()
        self.name_generator = VietnameseNameGenerator()
        
    def generate_image(self, output_path: Path, doc_type: str) -> Dict[str, Any]:
        """
        Generate a document image with PII.
        
        Args:
            output_path: Where to save the image
            doc_type: Type of document
            
        Returns:
            Dictionary with metadata and PII locations
        """
        logger.info(f"Generating image: {output_path.name}")
        
        # Create blank image (A4 proportions)
        width, height = 2480, 3508  # A4 at 300 DPI
        image = Image.new('RGB', (width, height), color='white')
        draw = ImageDraw.Draw(image)
        
        # Try to use a default font (fallback to default if not available)
        # Font size 80/55 at 2480x3508 (A4@300DPI) ensures EasyOCR can read the text
        # reliably even after scan simulation effects are applied.
        FONT_PATHS_BOLD = [
            "/usr/share/fonts/TTF/Roboto-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/Adwaita/AdwaitaSans-Regular.ttf",
        ]
        FONT_PATHS_REGULAR = [
            "/usr/share/fonts/TTF/Roboto-Regular.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/Adwaita/AdwaitaSans-Regular.ttf",
        ]
        font_title = None
        font_text = None
        for path in FONT_PATHS_BOLD:
            try:
                font_title = ImageFont.truetype(path, 80)
                break
            except IOError:
                continue
        for path in FONT_PATHS_REGULAR:
            try:
                font_text = ImageFont.truetype(path, 55)
                break
            except IOError:
                continue
        if font_title is None or font_text is None:
            font_title = ImageFont.load_default(size=80)
            font_text = ImageFont.load_default(size=55)
            logger.warning("Could not load any TrueType font, using PIL default")
        
        pii_locations = []
        
        # Title
        title = "HỢP ĐỒNG BẤT ĐỘNG SẢN"
        draw.text((width // 2 - 300, 200), title, fill='black', font=font_title)
        
        # Generate PII content
        y_pos = 400
        
        name = self.name_generator.generate()
        draw.text((200, y_pos), f"Ông/Bà: {name}", fill='black', font=font_text)
        pii_locations.append({"type": "name", "value": name, "approx_position": (200, y_pos)})
        y_pos += 80
        
        cccd = self.data_generator.generate_cccd()
        draw.text((200, y_pos), f"CCCD: {cccd}", fill='black', font=font_text)
        pii_locations.append({"type": "cccd", "value": cccd, "value_length": 12, "approx_position": (200, y_pos)})
        y_pos += 80
        
        dob = self.data_generator.generate_dob()
        draw.text((200, y_pos), f"Ngày sinh: {dob}", fill='black', font=font_text)
        pii_locations.append({"type": "dob", "value": dob, "approx_position": (200, y_pos)})
        
        # Save image
        image.save(output_path)
        
        log_with_context(
            logger, 'info', 'Image generated',
            filename=output_path.name,
            pii_count=len(pii_locations)
        )
        
        return {
            "filename": output_path.name,
            "doc_type": doc_type,
            "pii_locations": pii_locations,
            "generated_at": datetime.utcnow().isoformat()
        }


class ScannedDocumentSimulator:
    """
    Applies OpenCV filters to simulate scanned document appearance.
    
    Why: Real-world documents are often scanned with imperfections (noise, rotation,
    grayscale conversion). Simulating these effects makes training data more realistic.
    """
    
    @staticmethod
    def apply_scan_effects(image_path: Path) -> None:
        """
        Apply realistic scanning effects to an image.
        
        Args:
            image_path: Path to the image file to modify
            
        Why in-place: Modifying the file in-place saves memory and disk space
        compared to creating copies.
        """
        logger.debug(f"Applying scan effects to {image_path.name}")
        
        # Read image
        img = cv2.imread(str(image_path))
        
        if img is None:
            logger.error(f"Failed to read image: {image_path}")
            return
            
        # Convert to grayscale (common for scans)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        
        # Add slight Gaussian noise
        noise = np.random.normal(0, 5, gray.shape).astype(np.uint8)
        noisy = cv2.add(gray, noise)
        
        # Apply slight blur (simulates scan quality)
        blurred = cv2.GaussianBlur(noisy, (3, 3), 0)
        
        # Slight random rotation (-2 to +2 degrees)
        angle = random.uniform(-2, 2)
        h, w = blurred.shape
        center = (w // 2, h // 2)
        rotation_matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
        rotated = cv2.warpAffine(blurred, rotation_matrix, (w, h), 
                                  borderMode=cv2.BORDER_CONSTANT, 
                                  borderValue=255)
        
        # Adjust contrast (simulate scan settings variation)
        alpha = random.uniform(0.9, 1.1)  # Contrast
        beta = random.randint(-10, 10)     # Brightness
        adjusted = cv2.convertScaleAbs(rotated, alpha=alpha, beta=beta)
        
        # Save processed image
        cv2.imwrite(str(image_path), adjusted)
        
        logger.debug(f"Scan effects applied to {image_path.name}")


def generate_all_documents() -> List[Dict[str, Any]]:
    """
    Generate all required documents (PDFs and images).
    
    Returns:
        List of metadata dictionaries for all generated documents
        
    Why: Orchestrates the entire document generation process, ensuring
    proper distribution across document types and formats.
    """
    PipelineConfig.ensure_directories()
    
    pdf_generator = PDFDocumentGenerator()
    image_generator = ImageDocumentGenerator()
    scanner = ScannedDocumentSimulator()
    
    all_metadata = []
    
    # Generate PDFs
    logger.info(f"Generating {PipelineConfig.TARGET_PDF_COUNT} PDF documents")
    for i in range(PipelineConfig.TARGET_PDF_COUNT):
        doc_type = random.choice(PipelineConfig.DOCUMENT_TYPES)
        num_pages = random.randint(
            PipelineConfig.PDF_PAGE_COUNT_MIN,
            PipelineConfig.PDF_PAGE_COUNT_MAX
        )
        
        filename = f"{doc_type}_{i+1:02d}.pdf"
        output_path = PipelineConfig.get_output_path(filename)
        
        metadata = pdf_generator.generate_pdf(output_path, doc_type, num_pages)
        all_metadata.append(metadata)
        
    # Generate standalone images
    logger.info(f"Generating {PipelineConfig.TARGET_IMAGE_COUNT} image documents")
    for i in range(PipelineConfig.TARGET_IMAGE_COUNT):
        doc_type = random.choice(PipelineConfig.DOCUMENT_TYPES)
        filename = f"{doc_type}_img_{i+1:02d}.png"
        output_path = PipelineConfig.get_output_path(filename)
        
        metadata = image_generator.generate_image(output_path, doc_type)
        all_metadata.append(metadata)
        
        # Apply scan effects to images
        scanner.apply_scan_effects(output_path)
        
    log_with_context(
        logger, 'info', 'Document generation completed',
        total_documents=len(all_metadata),
        pdfs=PipelineConfig.TARGET_PDF_COUNT,
        images=PipelineConfig.TARGET_IMAGE_COUNT
    )
    
    return all_metadata
