#!/usr/bin/env python3
"""
Link Extractor Test Tool

This tool extracts links from PDF files in an S3 bucket and generates JSON files
containing link information, without running the full vector store processing pipeline.
It's designed for testing and debugging the link extraction functionality.

Usage:
    python link_extractor_test.py --pdf-key path/to/pdf.pdf
    python link_extractor_test.py --list-pdfs
    python link_extractor_test.py --process-all
    python link_extractor_test.py --limit 5
"""

import os
import json
import sys
import fitz  # PyMuPDF
import re
import boto3
import argparse
import logging
from pathlib import Path
from botocore.exceptions import NoCredentialsError, PartialCredentialsError, ClientError
from dotenv import load_dotenv
from tqdm import tqdm
from datetime import datetime

# Add parent directory to path for imports
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(project_root / 'logs' / 'link_extractor_test.log')
    ]
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv(dotenv_path=project_root / '.env', override=True)

# S3 Configuration
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
AWS_S3_BUCKET_NAME = os.getenv("AWS_S3_BUCKET_NAME")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
AWS_S3_PDF_PREFIX = os.getenv("AWS_S3_PDF_PREFIX", "source-pdfs/")
EXTRACTED_LINKS_S3_PREFIX = "extracted_links/"

# Ensure prefix ends with a slash
if AWS_S3_PDF_PREFIX and not AWS_S3_PDF_PREFIX.endswith('/'):
    AWS_S3_PDF_PREFIX += '/'

# Color to category mapping
COLOR_CATEGORY_MAP = {
    # Monster colors
    "#a70000": "monster",
    "#bc0f0f": "monster",
    
    # Spell colors
    "#704cd9": "spell",
    
    # Skill colors
    "#036634": "skill",
    "#11884c": "skill",
    
    # Item colors
    "#623a1e": "item", 
    "#774521": "item",
    "#0f5cbc": "item",  # Light blue color for magic items/potions
    
    # Rule colors
    "#6a5009": "rule",
    "#9b740b": "rule",
    "#efb311": "rule",  # Adding the new yellow color for rules
    
    # Sense colors
    "#a41b96": "sense",
    
    # Condition colors
    "#364d00": "condition",
    "#5a8100": "condition",
    
    # Lore colors
    "#a83e3e": "lore",
    
    # Default - fallback
    "#0053a3": "reference",
    "#006abe": "reference",
    "#141414": "navigation",
    "#9a9a9a": "footer",
    "#e8f6ff": "footer"
}

class LinkExtractorTest:
    """Test class for extracting links from PDFs and generating JSON files."""
    
    def __init__(self, add_categories=True):
        """
        Initialize the link extractor test.
        
        Args:
            add_categories: Whether to add category information based on link colors
        """
        # Initialize S3 client
        self.s3_client = self._init_s3_client()
        if not self.s3_client:
            logger.error("S3 client initialization failed. Exiting.")
            sys.exit(1)
        
        self.add_categories = add_categories
            
    def _init_s3_client(self):
        """Initialize the S3 client."""
        if AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY and AWS_S3_BUCKET_NAME:
            try:
                s3_client = boto3.client(
                    's3',
                    aws_access_key_id=AWS_ACCESS_KEY_ID,
                    aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
                    region_name=AWS_REGION
                )
                logger.info(f"Initialized S3 client for bucket: {AWS_S3_BUCKET_NAME} in region: {AWS_REGION}")
                return s3_client
            except (NoCredentialsError, PartialCredentialsError) as e:
                logger.error(f"AWS Credentials not found or incomplete: {e}")
            except Exception as e:
                logger.error(f"Failed to initialize S3 client: {e}")
        else:
            logger.error("AWS S3 credentials/bucket name not fully configured.")
        return None
        
    def list_pdfs(self):
        """List all PDFs in the S3 bucket with their sizes."""
        pdf_files_info = []
        try:
            logger.info(f"Listing PDFs from bucket '{AWS_S3_BUCKET_NAME}' with prefix '{AWS_S3_PDF_PREFIX}'")
            paginator = self.s3_client.get_paginator('list_objects_v2')
            pages = paginator.paginate(Bucket=AWS_S3_BUCKET_NAME, Prefix=AWS_S3_PDF_PREFIX)
            for page in pages:
                if "Contents" in page:
                    for obj in page["Contents"]:
                        key = obj["Key"]
                        if key.lower().endswith('.pdf') and key != AWS_S3_PDF_PREFIX:
                            size_mb = obj.get("Size", 0) / (1024 * 1024)
                            pdf_files_info.append((key, obj.get("Size", 0), f"{size_mb:.2f} MB"))
            
            # Sort by size
            pdf_files_info.sort(key=lambda x: x[1])
            
            # Print sorted list
            logger.info(f"Found {len(pdf_files_info)} PDFs:")
            for i, (key, size, size_mb) in enumerate(pdf_files_info):
                logger.info(f"{i+1}. {key} - {size_mb}")
                
            return [info[0] for info in pdf_files_info]
        except Exception as e:
            logger.error(f"Error listing PDFs from S3: {e}")
            return []
            
    def extract_links_from_pdf(self, s3_pdf_key):
        """
        Extract links from a PDF and generate a JSON file with link information.
        
        Args:
            s3_pdf_key: The S3 key for the PDF file.
            
        Returns:
            bool: True if successful, False otherwise.
        """
        logger.info(f"Processing PDF: {s3_pdf_key}")
        
        # Enable more verbose debugging for this run
        debug_mode = True
        
        try:
            # Download PDF from S3
            try:
                pdf_object = self.s3_client.get_object(Bucket=AWS_S3_BUCKET_NAME, Key=s3_pdf_key)
                pdf_bytes = pdf_object['Body'].read()
                logger.info(f"Downloaded PDF: {s3_pdf_key} ({len(pdf_bytes)} bytes)")
            except ClientError as e:
                logger.error(f"Failed to download PDF '{s3_pdf_key}' from S3: {e}")
                return False
            except Exception as e:
                logger.error(f"Unexpected error downloading PDF '{s3_pdf_key}': {e}")
                return False
                
            # Extract relative path for output filename
            rel_path = s3_pdf_key[len(AWS_S3_PDF_PREFIX):] if s3_pdf_key.startswith(AWS_S3_PDF_PREFIX) else s3_pdf_key
            
            # Process PDF and extract links
            pdf_links_data = []
            doc = None
            
            try:
                doc = fitz.open(stream=pdf_bytes, filetype="pdf")
                total_pages = len(doc)
                logger.info(f"Opened PDF: {total_pages} pages")
                
                # First, perform a preliminary scan of annotations in the document
                if debug_mode:
                    logger.info("===== ANNOTATION SCAN =====")
                    total_annots = 0
                    link_annots = 0
                    has_colors = 0
                    
                    for page_idx, page in enumerate(doc):
                        page_annots = list(page.annots())
                        if page_annots:
                            logger.info(f"Page {page_idx+1}: Found {len(page_annots)} annotations")
                            total_annots += len(page_annots)
                            
                            for i, annot in enumerate(page_annots):
                                annot_type = annot.type[1] if hasattr(annot, 'type') and len(annot.type) > 1 else "Unknown"
                                if annot_type == "Link":
                                    link_annots += 1
                                    # Try to print various properties of the annotation
                                    rect_info = f"Rect: ({annot.rect.x0:.1f}, {annot.rect.y0:.1f}, {annot.rect.x1:.1f}, {annot.rect.y1:.1f})"
                                    color_info = "No color info"
                                    
                                    # Get detailed colors information
                                    if hasattr(annot, "colors") and annot.colors:
                                        has_colors += 1
                                        color_info = f"Colors: {annot.colors}"
                                    
                                    # Get other potentially useful properties
                                    props = []
                                    if hasattr(annot, "uri") and annot.uri:
                                        props.append(f"URI: {annot.uri}")
                                    if hasattr(annot, "xref") and annot.xref:
                                        props.append(f"XREF: {annot.xref}")
                                    if hasattr(annot, "info"):
                                        props.append(f"Info keys: {list(annot.info.keys()) if annot.info else 'None'}")
                                    
                                    logger.info(f"  - Annot {i+1}: Type={annot_type}, {rect_info}, {color_info}, {', '.join(props) if props else 'No additional properties'}")
                                    
                                    # Direct property access - debug any available property
                                    try:
                                        all_props = {key: getattr(annot, key) for key in dir(annot) 
                                                  if not key.startswith('_') and not callable(getattr(annot, key))}
                                        logger.debug(f"All properties: {all_props}")
                                    except Exception as e:
                                        logger.debug(f"Error getting all properties: {e}")
                    
                    logger.info(f"Annotation summary: {total_annots} total, {link_annots} links, {has_colors} with color info")
                    logger.info("===== END ANNOTATION SCAN =====\n")
                
                # Now process links and try to extract colors
                for page_num, page in enumerate(tqdm(doc, desc=f"Extracting links from pages", leave=False)):
                    # Log the annots available on this page
                    if debug_mode:
                        annots_list = list(page.annots())
                        logger.info(f"Page {page_num+1}: Processing {len(annots_list)} annotations and extracting links")
                    
                    # Extract Links from Page
                    try:
                        links = page.get_links()
                        if debug_mode:
                            logger.info(f"Page {page_num+1}: Found {len(links)} links")
                            
                        for link_idx, link in enumerate(links):
                            link_text = ""
                            link_rect = fitz.Rect(link['from'])
                            
                            # Extract link text
                            words = page.get_text("words", clip=link_rect)
                            words.sort(key=lambda w: (w[1], w[0]))
                            if words:
                                link_text = " ".join(w[4] for w in words).strip()
                                
                            if not link_text:
                                try:
                                    expanded_rect = link_rect + (-1, -1, 1, 1)
                                    link_text = page.get_textbox(expanded_rect).strip()
                                except Exception:
                                    pass
                                    
                            if link_text:
                                link_text = re.sub(r'\\s+', ' ', link_text).strip()
                                
                                link_info = {
                                    "link_text": link_text,
                                    "source_page": page_num + 1,
                                    "source_rect": [link_rect.x0, link_rect.y0, link_rect.x1, link_rect.y1]
                                }
                                
                                if debug_mode:
                                    link_kind = "GOTO (internal)" if link.get('kind') == fitz.LINK_GOTO else "URI (external)" if link.get('kind') == fitz.LINK_URI else str(link.get('kind'))
                                    link_target = f"Page {link.get('page')+1}" if link.get('kind') == fitz.LINK_GOTO else link.get('uri') if link.get('kind') == fitz.LINK_URI else "Unknown"
                                    logger.info(f"  Link {link_idx+1}: Text='{link_text}', Kind={link_kind}, Target={link_target}, Rect=({link_rect.x0:.1f}, {link_rect.y0:.1f}, {link_rect.x1:.1f}, {link_rect.y1:.1f})")
                                
                                # Extract link color information with enhanced logging
                                try:
                                    # New approach: Extract color directly from the text spans
                                    if debug_mode:
                                        logger.info(f"  Getting text color for link: '{link_text}'")
                                        
                                    # Get the text with detailed information including color
                                    page_dict = page.get_text("dict")
                                    
                                    # Track if we found a color
                                    found_color = False
                                    
                                    # Look for text blocks that overlap with our link rectangle
                                    for block in page_dict.get("blocks", []):
                                        if block.get("type") == 0:  # Text block
                                            for line in block.get("lines", []):
                                                line_rect = fitz.Rect(line.get("bbox"))
                                                
                                                # Check if this line overlaps with our link
                                                if line_rect.intersects(link_rect):
                                                    if debug_mode:
                                                        logger.info(f"    Found overlapping text line: {line_rect}")
                                                    
                                                    # Check the spans in this line
                                                    for span in line.get("spans", []):
                                                        span_rect = fitz.Rect(span.get("bbox"))
                                                        span_text = span.get("text", "")
                                                        
                                                        # If the span's rectangle intersects with our link and contains part of the link text
                                                        if span_rect.intersects(link_rect) and span_text and (span_text in link_text or link_text in span_text):
                                                            # Get the color of this span
                                                            span_color = span.get("color")
                                                            
                                                            if debug_mode:
                                                                logger.info(f"    Found matching span: '{span_text}' with color info: {span_color}")
                                                            
                                                            if span_color:
                                                                # Convert the color to our hex format
                                                                # In PyMuPDF, text colors are typically RGB integers
                                                                if isinstance(span_color, int):
                                                                    # Convert from integer RGB value (0xRRGGBB)
                                                                    r = (span_color >> 16) & 0xFF
                                                                    g = (span_color >> 8) & 0xFF
                                                                    b = span_color & 0xFF
                                                                    color_hex = f"#{r:02x}{g:02x}{b:02x}"
                                                                else:
                                                                    # For other color formats
                                                                    if isinstance(span_color, (list, tuple)):
                                                                        if len(span_color) == 3:  # RGB color
                                                                            r, g, b = [max(0, min(255, int(c * 255))) for c in span_color]
                                                                            color_hex = f"#{r:02x}{g:02x}{b:02x}"
                                                                        elif len(span_color) == 1:  # Gray
                                                                            gray = max(0, min(255, int(span_color[0] * 255)))
                                                                            color_hex = f"#{gray:02x}{gray:02x}{gray:02x}"
                                                                    else:
                                                                        if debug_mode:
                                                                            logger.info(f"    Unhandled color format: {span_color}")
                                                                        continue
                                                                
                                                                link_info["color"] = color_hex
                                                                found_color = True
                                                                
                                                                if debug_mode:
                                                                    logger.info(f"    ✓ Extracted text color: {color_hex}")
                                                                
                                                                # Once we find a color, we can stop looking
                                                                break
                                                    
                                                    if found_color:
                                                        break
                                        
                                        if found_color:
                                            break
                                    
                                    # If we didn't find a color through spans, as a fallback, try to extract 
                                    # a color from the annotation (original method)
                                    if not found_color and page.annots():
                                        if debug_mode:
                                            logger.info(f"  No color found in text spans, checking annotations as fallback...")
                                            
                                        # Direct approach - try to match URI in link with annotation URI
                                        found_matching_annot = False
                                        
                                        # Get all annotations on the page for matching
                                        page_annots = list(page.annots())
                                        if debug_mode:
                                            logger.info(f"  Matching against {len(page_annots)} annotations on page {page_num+1}")
                                            
                                        for annot_idx, annot in enumerate(page_annots):
                                            annot_type = annot.type[1] if hasattr(annot, 'type') and len(annot.type) > 1 else "Unknown"
                                            
                                            # First check if it's a link annotation
                                            if annot_type == "Link":
                                                # More reliable matching based on rectangle overlap
                                                annot_rect = annot.rect
                                                
                                                # Debug the rectangles we're comparing
                                                if debug_mode:
                                                    logger.info(f"    Comparing Link rect ({link_rect.x0:.1f}, {link_rect.y0:.1f}, {link_rect.x1:.1f}, {link_rect.y1:.1f}) with Annot rect ({annot_rect.x0:.1f}, {annot_rect.y0:.1f}, {annot_rect.x1:.1f}, {annot_rect.y1:.1f})")
                                                    # Calculate overlap metrics to help with debugging
                                                    x_overlap = max(0, min(link_rect.x1, annot_rect.x1) - max(link_rect.x0, annot_rect.x0))
                                                    y_overlap = max(0, min(link_rect.y1, annot_rect.y1) - max(link_rect.y0, annot_rect.y0))
                                                    overlap_area = x_overlap * y_overlap
                                                    link_area = (link_rect.x1 - link_rect.x0) * (link_rect.y1 - link_rect.y0)
                                                    annot_area = (annot_rect.x1 - annot_rect.x0) * (annot_rect.y1 - annot_rect.y0)
                                                    overlap_percent_link = (overlap_area / link_area) * 100 if link_area > 0 else 0
                                                    overlap_percent_annot = (overlap_area / annot_area) * 100 if annot_area > 0 else 0
                                                    logger.info(f"    Overlap: {overlap_area:.1f} sq units ({overlap_percent_link:.1f}% of link, {overlap_percent_annot:.1f}% of annotation)")
                                                    
                                                    # Distance between centers
                                                    link_center_x = (link_rect.x0 + link_rect.x1) / 2
                                                    link_center_y = (link_rect.y0 + link_rect.y1) / 2
                                                    annot_center_x = (annot_rect.x0 + annot_rect.x1) / 2
                                                    annot_center_y = (annot_rect.y0 + annot_rect.y1) / 2
                                                    center_distance = ((link_center_x - annot_center_x)**2 + (link_center_y - annot_center_y)**2)**0.5
                                                    logger.info(f"    Distance between centers: {center_distance:.1f} units")
                                                
                                                # Check for significant overlap (rectangles are very close)
                                                # Use less strict matching for debugging
                                                rect_match = False
                                                
                                                # Traditional approach - check corners are within tolerance
                                                corners_match = (abs(annot_rect.x0 - link_rect.x0) < 10 and 
                                                              abs(annot_rect.y0 - link_rect.y0) < 10 and
                                                              abs(annot_rect.x1 - link_rect.x1) < 10 and
                                                              abs(annot_rect.y1 - link_rect.y1) < 10)
                                                             
                                                # Alternative: check if there's significant overlap as percentage of area
                                                significant_overlap = (overlap_area > 0 and 
                                                            (overlap_percent_link > 50 or overlap_percent_annot > 50))
                                                                
                                                # Another alternative: check if centers are close
                                                centers_close = center_distance < 20
                                                
                                                # Combined approach
                                                rect_match = corners_match or significant_overlap or centers_close
                                                
                                                if debug_mode:
                                                    logger.info(f"    Match metrics: corners_match={corners_match}, significant_overlap={significant_overlap}, centers_close={centers_close}")
                                                    logger.info(f"    Overall rect_match={rect_match}")
                                                
                                                if rect_match:
                                                    # For external links, also confirm URL matches
                                                    url_match = True
                                                    if link.get('kind') == fitz.LINK_URI:
                                                        uri = link.get('uri')
                                                        annot_uri = annot.uri if hasattr(annot, 'uri') else None
                                                        
                                                        # If both URIs exist and don't match, skip
                                                        if uri and annot_uri and uri != annot_uri:
                                                            url_match = False
                                                            if debug_mode:
                                                                logger.info(f"    URL mismatch: link URI={uri}, annot URI={annot_uri}")
                                                
                                                    if url_match:
                                                        # Extract color information
                                                        found_matching_annot = True
                                                        
                                                        if debug_mode:
                                                            logger.info(f"    ✓ MATCH FOUND! Annotation {annot_idx+1} matches link {link_idx+1}")
                                                        
                                                        # Try getting color from appearance (more reliable)
                                                        color = None
                                                        
                                                        # Debug all available properties of the annotation
                                                        if debug_mode:
                                                            try:
                                                                logger.info(f"    Annotation properties:")
                                                                for key in dir(annot):
                                                                    if not key.startswith('_') and not callable(getattr(annot, key)):
                                                                        try:
                                                                            value = getattr(annot, key)
                                                                            logger.info(f"      {key} = {value}")
                                                                        except Exception as prop_e:
                                                                            logger.info(f"      {key} = <error: {prop_e}>")
                                                            except Exception as e:
                                                                logger.info(f"    Error inspecting annotation properties: {e}")
                                                        
                                                        # Look for colors in the annotation
                                                        if hasattr(annot, "colors") and annot.colors:
                                                            colors = annot.colors
                                                            if debug_mode:
                                                                logger.info(f"    Found colors attribute: {colors}")
                                                                
                                                            if "stroke" in colors and colors["stroke"]:
                                                                color = colors["stroke"]
                                                                if debug_mode:
                                                                    logger.info(f"    Using stroke color: {color}")
                                                            elif "fill" in colors and colors["fill"]:
                                                                color = colors["fill"]
                                                                if debug_mode:
                                                                    logger.info(f"    Using fill color: {color}")
                                                        else:
                                                            if debug_mode:
                                                                logger.info(f"    No colors attribute found on annotation")
                                                                # Try alternative color access method
                                                                try:
                                                                    if hasattr(annot, "get_colors"):
                                                                        alt_colors = annot.get_colors()
                                                                        logger.info(f"    Alternative colors via get_colors(): {alt_colors}")
                                                                except Exception as alt_e:
                                                                    logger.info(f"    Error getting alternative colors: {alt_e}")
                                                            
                                                        # If we found a color
                                                        if color:
                                                            # Process different color formats
                                                            if debug_mode:
                                                                logger.info(f"    Processing color value: {color}, type: {type(color)}")
                                                                
                                                            if isinstance(color, (list, tuple)):
                                                                if len(color) == 3:  # RGB color
                                                                    r, g, b = [max(0, min(255, int(c * 255))) for c in color]
                                                                    color_hex = f"#{r:02x}{g:02x}{b:02x}"
                                                                    link_info["color"] = color_hex
                                                                    if debug_mode:
                                                                        logger.info(f"    Converted RGB {color} to hex: {color_hex}")
                                                                elif len(color) == 1:  # Gray color
                                                                    gray = max(0, min(255, int(color[0] * 255)))
                                                                    color_hex = f"#{gray:02x}{gray:02x}{gray:02x}"
                                                                    link_info["color"] = color_hex
                                                                    if debug_mode:
                                                                        logger.info(f"    Converted Gray {color} to hex: {color_hex}")
                                                                elif len(color) == 4:  # CMYK color - approximate conversion to RGB
                                                                    c, m, y, k = color
                                                                    # Simple CMYK to RGB conversion
                                                                    r = max(0, min(255, int((1 - c) * (1 - k) * 255)))
                                                                    g = max(0, min(255, int((1 - m) * (1 - k) * 255)))
                                                                    b = max(0, min(255, int((1 - y) * (1 - k) * 255)))
                                                                    color_hex = f"#{r:02x}{g:02x}{b:02x}"
                                                                    link_info["color"] = color_hex
                                                                    if debug_mode:
                                                                        logger.info(f"    Converted CMYK {color} to hex: {color_hex}")
                                                                elif isinstance(color, (int, float)):  # Single value for gray
                                                                    gray = max(0, min(255, int(color * 255)))
                                                                    color_hex = f"#{gray:02x}{gray:02x}{gray:02x}"
                                                                    link_info["color"] = color_hex
                                                                    if debug_mode:
                                                                        logger.info(f"    Converted Gray scalar {color} to hex: {color_hex}")
                                                                else:
                                                                    if debug_mode:
                                                                        logger.info(f"    Unsupported color format: {color} (type: {type(color)})")
                                                            
                                                            # If we found a color, we can stop looking
                                                            break
                                                        else:
                                                            if debug_mode:
                                                                logger.info(f"    No valid color value found in annotation")
                                                            
                                    # Fallback approach for highlight annotations near the link
                                    if (not found_matching_annot or "color" not in link_info) and debug_mode:
                                        logger.info(f"  No matching direct link annotation found or no color extracted. Trying highlight annotations...")
                                        
                                    if not found_matching_annot or "color" not in link_info:
                                        # Look for highlight annotations that might overlap with link
                                        highlight_found = False
                                        for annot_idx, annot in enumerate(page_annots):
                                            annot_type = annot.type[1] if hasattr(annot, 'type') and len(annot.type) > 1 else "Unknown"
                                            
                                            if annot_type == "Highlight":
                                                # Check if highlight overlaps with link
                                                annot_rect = annot.rect
                                                
                                                if debug_mode:
                                                    logger.info(f"    Checking highlight annotation {annot_idx+1}")
                                                    x_overlap = max(0, min(link_rect.x1, annot_rect.x1) - max(link_rect.x0, annot_rect.x0))
                                                    y_overlap = max(0, min(link_rect.y1, annot_rect.y1) - max(link_rect.y0, annot_rect.y0))
                                                    overlap_area = x_overlap * y_overlap
                                                    logger.info(f"    Overlap area with link: {overlap_area:.1f} sq units")
                                                    
                                                if annot_rect.intersects(link_rect):
                                                    highlight_found = True
                                                    if debug_mode:
                                                        logger.info(f"    ✓ Found intersecting highlight annotation")
                                                        
                                                    if hasattr(annot, "colors") and annot.colors:
                                                        colors = annot.colors
                                                        color = None
                                                        
                                                        if debug_mode:
                                                            logger.info(f"    Highlight colors: {colors}")
                                                            
                                                        if "stroke" in colors and colors["stroke"]:
                                                            color = colors["stroke"]
                                                            if debug_mode:
                                                                logger.info(f"    Using highlight stroke color: {color}")
                                                        elif "fill" in colors and colors["fill"]:
                                                            color = colors["fill"]
                                                            if debug_mode:
                                                                logger.info(f"    Using highlight fill color: {color}")
                                                                
                                                        if color:
                                                            # Process color as above, but shortened for brevity
                                                            if isinstance(color, (list, tuple)):
                                                                if len(color) == 3:  # RGB
                                                                    r, g, b = [max(0, min(255, int(c * 255))) for c in color]
                                                                    color_hex = f"#{r:02x}{g:02x}{b:02x}"
                                                                    link_info["color"] = color_hex
                                                                    if debug_mode:
                                                                        logger.info(f"    Converted highlight RGB {color} to hex: {color_hex}")
                                                                    break
                                                            elif isinstance(color, (int, float)):
                                                                gray = max(0, min(255, int(color * 255)))
                                                                color_hex = f"#{gray:02x}{gray:02x}{gray:02x}"
                                                                link_info["color"] = color_hex
                                                                if debug_mode:
                                                                    logger.info(f"    Converted highlight Gray {color} to hex: {color_hex}")
                                                                break
                                                                
                                        if not highlight_found and debug_mode:
                                            logger.info(f"    No intersecting highlight annotations found")
                                
                                    if debug_mode and "color" in link_info:
                                        logger.info(f"  FINAL COLOR for link '{link_text}': {link_info['color']}")
                                    elif debug_mode:
                                        logger.info(f"  NO COLOR FOUND for link '{link_text}'")
                                        
                                except Exception as color_e:
                                    logger.warning(f"Error extracting link color: {color_e}", exc_info=True if debug_mode else False)
                                
                                # If we found a color and categories are enabled, add category info
                                if "color" in link_info and self.add_categories:
                                    color = link_info["color"].lower()
                                    if color in COLOR_CATEGORY_MAP:
                                        link_info["link_category"] = COLOR_CATEGORY_MAP[color]
                                    else:
                                        # Use 'unknown' for colors not in our mapping
                                        link_info["link_category"] = "unknown"
                                        if debug_mode:
                                            logger.info(f"    Unknown color category for: {color}")
                                
                                # Process link by type
                                if link['kind'] == fitz.LINK_GOTO:
                                    target_page_num = link['page']
                                    target_page_label = target_page_num + 1
                                    link_info['link_type'] = "internal"
                                    link_info['target_page'] = target_page_label
                                    
                                    target_snippet = None
                                    if 0 <= target_page_num < total_pages:
                                        target_page = doc[target_page_num]
                                        target_page_text = target_page.get_text("text")
                                        match_start = -1
                                        try:
                                            pattern = r"\\b" + re.escape(link_info['link_text']) + r"\\b"
                                            match = re.search(pattern, target_page_text, re.IGNORECASE | re.DOTALL)
                                            if match: match_start = match.start()
                                            else: match_start = target_page_text.lower().find(link_info['link_text'].lower())
                                        except re.error:
                                            match_start = target_page_text.lower().find(link_info['link_text'].lower())
                                            
                                        if match_start != -1:
                                            start_para = target_page_text.rfind('\\n\\n', 0, match_start)
                                            start_para = 0 if start_para == -1 else start_para + 2
                                            end_para = target_page_text.find('\\n\\n', match_start)
                                            end_para = len(target_page_text) if end_para == -1 else end_para
                                            target_snippet = target_page_text[start_para:end_para].strip().replace('\\n', ' ')
                                            snippet_max_len = 750
                                            if len(target_snippet) > snippet_max_len:
                                                trunc_point = target_snippet.rfind('.', 0, snippet_max_len)
                                                if trunc_point > snippet_max_len * 0.7: target_snippet = target_snippet[:trunc_point+1] + "..."
                                                else: target_snippet = target_snippet[:snippet_max_len] + "..."
                                        else:
                                            logger.warning(f"Link text '{link_info['link_text']}' not found on target page {target_page_label} for {s3_pdf_key}. Using fallback snippet.")
                                            first_para_end = target_page_text.find('\\n\\n')
                                            if first_para_end != -1 and first_para_end > 50: target_snippet = target_page_text[:first_para_end].strip().replace('\\n', ' ')
                                            else:
                                                fallback_len = 350
                                                target_snippet = target_page_text[:fallback_len].strip().replace('\\n', ' ') + ("..." if len(target_page_text) > fallback_len else "")
                                        if not target_snippet: target_snippet = f"Content from page {target_page_label}"
                                    else:
                                        logger.warning(f"Internal link target page {target_page_label} out of bounds for {s3_pdf_key}")
                                        target_snippet = f"Error: Target page {target_page_label} invalid."
                                        
                                    link_info['target_snippet'] = target_snippet
                                    link_info['target_url'] = None
                                    pdf_links_data.append(link_info)
                                    
                                elif link['kind'] == fitz.LINK_URI:
                                    link_info['link_type'] = "external"
                                    link_info['target_url'] = link['uri']
                                    link_info['target_page'] = None
                                    link_info['target_snippet'] = None
                                    pdf_links_data.append(link_info)
                            else:
                                logger.warning(f"Could not extract text for link on {s3_pdf_key} page {page_num+1}. Skipping.")
                                
                    except Exception as link_e:
                        logger.error(f"Error processing links on {s3_pdf_key} page {page_num+1}: {link_e}")
                
                # Save extracted links to S3
                if pdf_links_data:
                    links_s3_key_suffix = f"{rel_path}.links.json"
                    s3_prefix = EXTRACTED_LINKS_S3_PREFIX
                    if s3_prefix and not s3_prefix.endswith('/'): s3_prefix += '/'
                    links_json_s3_key = f"{s3_prefix}{links_s3_key_suffix}"
                    links_json_content = json.dumps(pdf_links_data, indent=2)
                    
                    try:
                        self.s3_client.put_object(
                            Bucket=AWS_S3_BUCKET_NAME, 
                            Key=links_json_s3_key, 
                            Body=links_json_content, 
                            ContentType='application/json'
                        )
                        
                        logger.info(f"Saved {len(pdf_links_data)} extracted links to S3: {links_json_s3_key}")
                        # Also save locally for inspection
                        local_json_path = project_root / 'test_output'
                        local_json_path.mkdir(exist_ok=True)
                        with open(local_json_path / f"{Path(rel_path).stem}.links.json", 'w') as f:
                            f.write(links_json_content)
                        logger.info(f"Saved local copy to {local_json_path / f'{Path(rel_path).stem}.links.json'}")
                        
                        # Print color stats
                        colored_links = sum(1 for link in pdf_links_data if 'color' in link)
                        categorized_links = sum(1 for link in pdf_links_data if 'link_category' in link)
                        logger.info(f"Color stats: {colored_links}/{len(pdf_links_data)} links have color information")
                        logger.info(f"Category stats: {categorized_links}/{len(pdf_links_data)} links have category information")
                        
                        if colored_links > 0:
                            logger.info(f"Sample colors: {[link.get('color') for link in pdf_links_data if 'color' in link][:5]}")
                            
                        # Analyze color distribution
                        self._analyze_link_colors(pdf_links_data)
                        
                        # Also analyze categories if enabled
                        if self.add_categories:
                            self._analyze_link_categories(pdf_links_data)
                        
                        return True
                    except Exception as save_e:
                        logger.error(f"Failed to save extracted links to S3: {save_e}")
                else:
                    logger.warning(f"No links were extracted from {s3_pdf_key}")
                
            except Exception as pdf_proc_e:
                logger.error(f"Error processing PDF content for {s3_pdf_key}: {pdf_proc_e}")
            finally:
                if doc: doc.close()
                
        except Exception as outer_e:
            logger.error(f"Unhandled error during processing of {s3_pdf_key}: {outer_e}")
            
        return False
        
    def process_all_pdfs(self, limit=None):
        """Process all PDFs in the S3 bucket."""
        pdfs = self.list_pdfs()
        if not pdfs:
            logger.error("No PDFs found to process.")
            return
            
        # If limit is set, only process that many PDFs
        if limit and limit > 0:
            logger.info(f"Limiting processing to {limit} PDFs")
            pdfs = pdfs[:limit]
            
        start_time = datetime.now()
        successful = 0
        
        for i, pdf_key in enumerate(pdfs):
            logger.info(f"\n[{i+1}/{len(pdfs)}] Processing {pdf_key}")
            if self.extract_links_from_pdf(pdf_key):
                successful += 1
                
        end_time = datetime.now()
        elapsed = (end_time - start_time).total_seconds()
        logger.info(f"\nProcessed {len(pdfs)} PDFs in {elapsed:.2f} seconds")
        logger.info(f"Successfully extracted links from {successful}/{len(pdfs)} PDFs")
        
    def _analyze_link_colors(self, links_data):
        """
        Analyze and report statistics about link colors.
        
        Args:
            links_data: List of extracted link dictionaries
        """
        if not links_data:
            logger.info("No links to analyze")
            return
            
        # Count colors
        color_counts = {}
        color_examples = {}
        link_types_by_color = {}
        
        for link in links_data:
            color = link.get('color')
            if color:
                # Count this color
                color_counts[color] = color_counts.get(color, 0) + 1
                
                # Save an example link text for this color
                if color not in color_examples:
                    color_examples[color] = link.get('link_text', '')[:30]
                
                # Track link types for each color
                link_type = link.get('link_type', 'unknown')
                if color not in link_types_by_color:
                    link_types_by_color[color] = {}
                link_types_by_color[color][link_type] = link_types_by_color[color].get(link_type, 0) + 1
        
        # Sort colors by frequency
        sorted_colors = sorted(color_counts.items(), key=lambda x: x[1], reverse=True)
        
        # Report statistics
        logger.info("\n===== LINK COLOR ANALYSIS =====")
        logger.info(f"Found {len(color_counts)} unique colors across {sum(color_counts.values())} colored links")
        
        # Print table header
        logger.info(f"{'Color':<10} | {'Count':<6} | {'Percent':<8} | {'Example':<30} | {'Types'}")
        logger.info("-" * 80)
        
        # Print each color with stats
        for color, count in sorted_colors:
            percent = (count / sum(color_counts.values())) * 100
            example = color_examples.get(color, '')
            
            # Format type distribution
            type_info = []
            for link_type, type_count in link_types_by_color.get(color, {}).items():
                type_percent = (type_count / count) * 100
                type_info.append(f"{link_type}: {type_count} ({type_percent:.1f}%)")
            
            logger.info(f"{color:<10} | {count:<6} | {percent:>6.1f}% | {example:<30} | {', '.join(type_info)}")
        
        logger.info("============================\n")

    def _analyze_link_categories(self, links_data):
        """
        Analyze and report statistics about link categories.
        
        Args:
            links_data: List of extracted link dictionaries
        """
        if not links_data:
            logger.info("No links to analyze")
            return
            
        # Count categories
        category_counts = {}
        category_examples = {}
        
        # Store specific examples for certain categories
        target_categories = ["navigation", "reference", "unknown"]
        category_detailed_examples = {cat: [] for cat in target_categories}
        
        for link in links_data:
            category = link.get('link_category')
            if category:
                # Count this category
                category_counts[category] = category_counts.get(category, 0) + 1
                
                # Save an example link text for this category
                if category not in category_examples:
                    category_examples[category] = link.get('link_text', '')[:30]
                
                # Store detailed examples for target categories
                if category in target_categories and len(category_detailed_examples[category]) < 5:
                    example_detail = {
                        'text': link.get('link_text', '')[:50],
                        'page': link.get('source_page', 'Unknown'),
                        'color': link.get('color', 'No color'),
                        'type': link.get('link_type', 'Unknown type')
                    }
                    category_detailed_examples[category].append(example_detail)
        
        # Sort categories by frequency
        sorted_categories = sorted(category_counts.items(), key=lambda x: x[1], reverse=True)
        
        # Report statistics
        logger.info("\n===== LINK CATEGORY ANALYSIS =====")
        logger.info(f"Found {len(category_counts)} unique categories across {sum(category_counts.values())} categorized links")
        
        # Print table header
        logger.info(f"{'Category':<15} | {'Count':<6} | {'Percent':<8} | {'Example':<30}")
        logger.info("-" * 65)
        
        # Print each category with stats
        for category, count in sorted_categories:
            percent = (count / sum(category_counts.values())) * 100
            example = category_examples.get(category, '')
            
            logger.info(f"{category:<15} | {count:<6} | {percent:>6.1f}% | {example:<30}")
        
        logger.info("============================\n")
        
        # Print detailed examples for target categories
        for category in target_categories:
            if category in category_counts and category_detailed_examples[category]:
                logger.info(f"\n===== DETAILED EXAMPLES FOR '{category.upper()}' CATEGORY =====")
                for i, example in enumerate(category_detailed_examples[category], 1):
                    logger.info(f"Example {i}:")
                    logger.info(f"  Text: '{example['text']}'")
                    logger.info(f"  Page: {example['page']}")
                    logger.info(f"  Color: {example['color']}")
                    logger.info(f"  Link Type: {example['type']}")
                logger.info("======================\n")

def main():
    """Main entry point for the script."""
    parser = argparse.ArgumentParser(description='Link Extractor Test Tool')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--pdf-key', help='S3 key of a specific PDF to process')
    group.add_argument('--list-pdfs', action='store_true', help='List all PDFs in the S3 bucket')
    group.add_argument('--process-all', action='store_true', help='Process all PDFs in the S3 bucket')
    parser.add_argument('--limit', type=int, help='Limit the number of PDFs to process')
    parser.add_argument('--no-categories', action='store_true', help='Disable adding category information based on link colors')
    
    args = parser.parse_args()
    extractor = LinkExtractorTest(add_categories=not args.no_categories)
    
    if args.list_pdfs:
        extractor.list_pdfs()
    elif args.pdf_key:
        extractor.extract_links_from_pdf(args.pdf_key)
    elif args.process_all:
        extractor.process_all_pdfs(limit=args.limit)
        
if __name__ == "__main__":
    main() 