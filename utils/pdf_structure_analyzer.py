import fitz
import json
import os
import boto3
import sys
from dotenv import load_dotenv
from collections import defaultdict

# Load environment variables
load_dotenv()

# Initialize S3 client
s3_client = boto3.client(
    's3',
    aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
    aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
    region_name=os.getenv('AWS_REGION', 'us-east-1')
)

bucket = os.getenv('AWS_S3_BUCKET_NAME')
prefix = 'source-pdfs/'

def list_pdfs():
    """List all PDFs in the S3 bucket under the source-pdfs prefix"""
    print(f"Listing PDFs in bucket {bucket} under prefix {prefix}")
    
    pdf_keys = []
    paginator = s3_client.get_paginator('list_objects_v2')
    pages = paginator.paginate(Bucket=bucket, Prefix=prefix)
    
    for page in pages:
        if "Contents" in page:
            for obj in page["Contents"]:
                key = obj["Key"]
                if key.lower().endswith('.pdf'):
                    pdf_keys.append(key)
    
    if not pdf_keys:
        print("No PDFs found in the bucket")
        return []
        
    # Sort and display the PDFs
    pdf_keys.sort()
    for i, key in enumerate(pdf_keys):
        print(f"{i+1}. {key}")
    
    return pdf_keys

def analyze_pdf_page(doc, page_num, all_font_styles=None):
    """Analyze the formatting of a single PDF page"""
    if all_font_styles is None:
        all_font_styles = defaultdict(lambda: {"count": 0, "examples": []})
        
    page = doc[page_num]
    dict_text = page.get_text('dict')
    
    # Extract text spans with their font information
    for block in dict_text['blocks']:
        if block.get("type") == 0:  # Text blocks only
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    size = span.get("size", 0)
                    font = span.get("font", "unknown")
                    text = span.get("text", "").strip()
                    flags = span.get("flags", 0)
                    color = span.get("color", 0)
                    
                    if not text:
                        continue
                        
                    # Create a key for this font style
                    style_key = f"{font}_{size}_{flags}_{color}"
                    
                    if style_key not in all_font_styles:
                        all_font_styles[style_key] = {
                            "font": font,
                            "size": size,
                            "flags": flags,
                            "color": color,
                            "count": 0,
                            "examples": [],
                            "pages_seen": set()
                        }
                    
                    all_font_styles[style_key]["count"] += 1
                    all_font_styles[style_key]["pages_seen"].add(page_num)
                    
                    if len(all_font_styles[style_key]["examples"]) < 3:
                        display_text = text[:50] + ("..." if len(text) > 50 else "")
                        all_font_styles[style_key]["examples"].append(display_text)
    
    # Also collect block-level text for structure analysis
    page_headings = []
    
    for block in dict_text['blocks']:
        if block.get("type") == 0:  # Text blocks only
            block_text = ""
            max_size = 0
            is_bold = False
            
            for line in block.get("lines", []):
                line_text = ""
                
                for span in line.get("spans", []):
                    span_text = span.get("text", "").strip()
                    size = span.get("size", 0)
                    flags = span.get("flags", 0)
                    
                    if size > max_size:
                        max_size = size
                    
                    if flags & 16:  # Bold flag
                        is_bold = True
                        
                    line_text += span_text
                
                block_text += line_text + " "
            
            block_text = block_text.strip()
            if not block_text:
                continue
                
            # Store block info for later structure analysis
            page_headings.append({
                "text": block_text,
                "font_size": max_size,
                "is_bold": is_bold,
                "page": page_num
            })
    
    return all_font_styles, page_headings

def analyze_pdf_batch(pdf_key, num_pages=20):
    """Analyze multiple pages of a PDF to identify document structure"""
    print(f'\nFetching PDF: {pdf_key}')
    try:
        response = s3_client.get_object(Bucket=bucket, Key=pdf_key)
        pdf_data = response['Body'].read()
    except Exception as e:
        print(f"Error fetching PDF: {e}")
        return
    
    # Open the PDF
    doc = fitz.open(stream=pdf_data, filetype='pdf')
    total_pages = len(doc)
    
    print(f'PDF has {total_pages} total pages')
    pages_to_analyze = min(num_pages, total_pages)
    
    # Sample pages throughout the document instead of just the first few
    if total_pages <= num_pages:
        # If document is short, analyze all pages
        page_numbers = list(range(total_pages))
    else:
        # Otherwise, sample pages throughout the document
        # Take first few, last few, and some from the middle
        first_pages = list(range(min(5, total_pages // 4)))
        middle_pages = list(range(total_pages // 3, total_pages * 2 // 3, max(1, total_pages // (num_pages - 10))))
        last_pages = list(range(max(0, total_pages - 5), total_pages))
        
        # Combine and ensure we don't exceed desired number of pages
        page_numbers = sorted(set(first_pages + middle_pages + last_pages))[:num_pages]
    
    print(f'Analyzing {len(page_numbers)} pages: {page_numbers}')
    
    # Collect font style information across all analyzed pages
    all_font_styles = {}
    all_headings = []
    
    for i, page_num in enumerate(page_numbers):
        print(f'Processing page {page_num+1}/{total_pages} ({i+1}/{len(page_numbers)})')
        all_font_styles, page_headings = analyze_pdf_page(doc, page_num, all_font_styles)
        all_headings.extend(page_headings)
    
    # Convert font styles to list and sort by size
    font_styles_list = list(all_font_styles.values())
    font_styles_list.sort(key=lambda x: (x["size"], len(x["pages_seen"]), x["count"]), reverse=True)
    
    # Display font style statistics
    print("\n=========== FONT STYLES ANALYSIS ===========")
    print(f"Found {len(font_styles_list)} distinct font styles across {len(page_numbers)} pages")
    
    print("\nTop font styles by size:")
    print("-" * 70)
    
    for i, style in enumerate(font_styles_list[:10]):  # Show top 10
        flag_desc = []
        if style["flags"] & 1: flag_desc.append("superscript")
        if style["flags"] & 2: flag_desc.append("italic")
        if style["flags"] & 4: flag_desc.append("serifed")
        if style["flags"] & 8: flag_desc.append("monospaced")
        if style["flags"] & 16: flag_desc.append("bold")
        flags_str = ", ".join(flag_desc) if flag_desc else "normal"
        
        print(f"{i+1}. Font: {style['font']}, Size: {style['size']}, Style: {flags_str}")
        print(f"   Count: {style['count']}, Pages seen: {len(style['pages_seen'])}")
        for example in style["examples"]:
            print(f"   - {example}")
        print()
    
    # Analyze document structure based on font sizes
    print("\n=========== DOCUMENT STRUCTURE ANALYSIS ===========")
    
    # Identify likely heading levels by analyzing font size distribution
    # Focus on styles that appear across multiple pages (likely to be heading styles)
    heading_candidates = [s for s in font_styles_list 
                         if len(s["pages_seen"]) > 1 and s["size"] > 0]
    
    if not heading_candidates:
        print("No consistent heading styles identified across pages")
        doc.close()
        return
    
    # Group by size to find clusters of similar sizes (may indicate heading levels)
    sizes = sorted(set(s["size"] for s in heading_candidates), reverse=True)
    
    # Map sizes to heading levels - heuristically using the top 6 distinct sizes
    # This assumes a hierarchical document structure with at most 6 heading levels
    size_clusters = []
    prev_size = None
    
    for size in sizes:
        if prev_size is None or (prev_size - size) > 1.0:  # New cluster if diff > 1pt
            size_clusters.append([size])
        else:
            size_clusters[-1].append(size)  # Add to current cluster
        prev_size = size
    
    # Take the largest size from each cluster
    heading_sizes = [cluster[0] for cluster in size_clusters][:6]  # Up to 6 heading levels
    
    print(f"Identified {len(heading_sizes)} potential heading levels:")
    for i, size in enumerate(heading_sizes):
        level_name = "H" + str(i+1)
        print(f"{level_name}: Font size ~{size}")
    
    # Create mapping of font sizes to heading levels
    size_to_level = {}
    for i, size_cluster in enumerate(size_clusters[:6]):
        for size in size_cluster:
            size_to_level[size] = i+1
    
    # Find examples of each heading level
    print("\nExamples of each heading level:")
    print("-" * 70)
    
    # Extract all blocks that appear to be headings
    all_heading_blocks = []
    
    for heading in all_headings:
        size = heading["font_size"]
        
        # Check if this block is a heading based on font size and other heuristics
        level = size_to_level.get(size)
        if level is not None:
            # Check additional criteria for lower level headings
            is_heading = False
            
            if level == 1:  # Top level - almost certainly a heading
                is_heading = True
            elif heading["is_bold"]:  # Bold text is likely a heading
                is_heading = True
            elif len(heading["text"]) < 100:  # Short text might be a heading
                is_heading = True
            elif heading["text"].endswith(':'):  # Ends with colon suggests a heading
                is_heading = True
                
            if is_heading:
                all_heading_blocks.append({
                    "level": level,
                    "text": heading["text"][:100] + ("..." if len(heading["text"]) > 100 else ""),
                    "page": heading["page"] + 1,  # Convert to 1-indexed
                    "font_size": size,
                    "is_bold": heading["is_bold"]
                })
    
    # Sort by page and position (assuming headings appear in order on pages)
    all_heading_blocks.sort(key=lambda x: x["page"])
    
    # Print examples of each heading level
    example_counts = defaultdict(int)
    for heading in all_heading_blocks:
        level = heading["level"]
        if example_counts[level] < 3:  # Show up to 3 examples of each level
            print(f"Level {level} (Page {heading['page']}): {heading['text']}")
            print(f"   [size: {heading['font_size']}, {'bold' if heading['is_bold'] else 'normal'}]")
            example_counts[level] += 1
            if example_counts[level] == 3:
                print()  # Add spacing after examples
    
    # Close the document
    doc.close()
    print('\nAnalysis complete!')

def analyze_pdf_formatting(pdf_key, page_num=0):
    """Analyze the formatting of a single PDF page (original function)"""
    print(f'\nFetching PDF: {pdf_key}')
    try:
        response = s3_client.get_object(Bucket=bucket, Key=pdf_key)
        pdf_data = response['Body'].read()
    except Exception as e:
        print(f"Error fetching PDF: {e}")
        return
    
    # Open the PDF
    doc = fitz.open(stream=pdf_data, filetype='pdf')
    total_pages = len(doc)
    
    if page_num >= total_pages:
        print(f"Error: Page {page_num} out of range (PDF has {total_pages} pages)")
        doc.close()
        return
    
    # Get text with formatting information
    page = doc[page_num]
    print(f'Analyzing page {page_num+1}/{total_pages}')
    print(f'Page size: {page.rect}')
    
    # Extract text with formatting information
    print('\n1. DICT FORMAT (with formatting):')
    dict_text = page.get_text('dict')
    # Print just a summary of blocks to avoid overwhelming output
    print(f"Number of blocks: {len(dict_text['blocks'])}")
    
    # Collect all text spans with their font information
    spans_by_font = {}
    
    for block in dict_text['blocks']:
        if block.get("type") == 0:  # Text blocks only
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    size = span.get("size", 0)
                    font = span.get("font", "unknown")
                    text = span.get("text", "").strip()
                    flags = span.get("flags", 0)  # Font flags (bold, italic, etc.)
                    color = span.get("color", 0)
                    
                    # Skip empty text
                    if not text:
                        continue
                        
                    # Create a key for this font style
                    style_key = f"{font}_{size}_{flags}_{color}"
                    if style_key not in spans_by_font:
                        spans_by_font[style_key] = {
                            "font": font,
                            "size": size,
                            "flags": flags,
                            "color": color,
                            "count": 0,
                            "examples": []
                        }
                    
                    spans_by_font[style_key]["count"] += 1
                    if len(spans_by_font[style_key]["examples"]) < 3:
                        # Truncate long text examples
                        display_text = text[:50] + ("..." if len(text) > 50 else "")
                        spans_by_font[style_key]["examples"].append(display_text)
    
    # Create a list of font styles sorted by size (largest first)
    font_styles = list(spans_by_font.values())
    font_styles.sort(key=lambda x: (x["size"], x["flags"]), reverse=True)
    
    # Display font styles as potential heading indicators
    print("\nFont styles found (potential heading indicators):")
    print("-" * 70)
    for style in font_styles:
        flag_desc = []
        if style["flags"] & 1:
            flag_desc.append("superscript")
        if style["flags"] & 2:
            flag_desc.append("italic")
        if style["flags"] & 4:
            flag_desc.append("serifed")
        if style["flags"] & 8:
            flag_desc.append("monospaced")
        if style["flags"] & 16:
            flag_desc.append("bold")
            
        flags_str = ", ".join(flag_desc) if flag_desc else "normal"
        
        print(f"Font: {style['font']}, Size: {style['size']}, Style: {flags_str}, Count: {style['count']}")
        for example in style["examples"]:
            print(f"  - {example}")
        print()
    
    # Extract a basic hierarchy by analyzing font styles
    print("\nAttempting to extract document hierarchy:")
    print("-" * 70)
    
    # Infer heading levels based on font sizes
    unique_sizes = sorted(set(style["size"] for style in font_styles), reverse=True)
    size_to_level = {size: i+1 for i, size in enumerate(unique_sizes[:6])}  # Map top 6 sizes to heading levels
    
    # Map each block to its likely heading level based on text size
    hierarchical_view = []
    
    for block in dict_text['blocks']:
        if block.get("type") == 0:  # Text blocks only
            block_text = ""
            block_level = 0
            
            for line in block.get("lines", []):
                line_text = ""
                max_size = 0
                is_bold = False
                
                for span in line.get("spans", []):
                    span_text = span.get("text", "").strip()
                    size = span.get("size", 0)
                    flags = span.get("flags", 0)
                    
                    if size > max_size:
                        max_size = size
                    
                    if flags & 16:  # Bold flag
                        is_bold = True
                        
                    line_text += span_text
                
                block_text += line_text + " "
            
            block_text = block_text.strip()
            if not block_text:
                continue
                
            # Determine if this block is likely a heading
            is_heading = max_size in size_to_level
            
            # For larger font size headings, they might be short
            # For smaller headings, we also check if they're bold or end with a colon
            if max_size in size_to_level:
                if max_size == unique_sizes[0]:  # Largest size
                    is_heading = True
                elif is_bold or block_text.endswith(':') or len(block_text) < 100:
                    is_heading = True
                    
            if is_heading:
                heading_level = size_to_level.get(max_size, 0)
                hierarchical_view.append({
                    "level": heading_level,
                    "text": block_text[:100] + ("..." if len(block_text) > 100 else ""),
                    "font_size": max_size,
                    "is_bold": is_bold
                })
    
    # Print the hierarchical view
    for item in hierarchical_view:
        indent = "  " * (item["level"] - 1)
        print(f"{indent}{'#' * item['level']} {item['text']} [size: {item['font_size']}, {'bold' if item['is_bold'] else 'normal'}]")
    
    # Close the document
    doc.close()
    print('\nAnalysis complete!')

def main():
    pdf_keys = list_pdfs()
    
    if not pdf_keys:
        print("No PDFs found to analyze")
        return
    
    try:
        while True:
            print("\nAnalysis options:")
            print("1. Single page analysis")
            print("2. Multi-page batch analysis (recommended for structure detection)")
            print("q. Quit")
            
            mode = input("Select an option: ")
            
            if mode.lower() == 'q':
                break
                
            if mode not in ['1', '2']:
                print("Invalid option")
                continue
                
            try:
                pdf_choice = input("\nEnter the number of the PDF to analyze: ")
                index = int(pdf_choice) - 1
                
                if 0 <= index < len(pdf_keys):
                    if mode == '1':
                        # Single page analysis
                        page_num = 0
                        try:
                            page_input = input("Enter page number to analyze (0-based, default=0): ")
                            if page_input.strip():
                                page_num = int(page_input)
                        except ValueError:
                            print("Invalid page number, using default (0)")
                            
                        analyze_pdf_formatting(pdf_keys[index], page_num)
                    else:
                        # Batch analysis
                        num_pages = 20
                        try:
                            pages_input = input("Number of pages to analyze (default=20): ")
                            if pages_input.strip():
                                num_pages = int(pages_input)
                        except ValueError:
                            print("Invalid number, using default (20)")
                            
                        analyze_pdf_batch(pdf_keys[index], num_pages)
                else:
                    print("Invalid PDF choice")
            except ValueError:
                print("Please enter a valid number")
    except KeyboardInterrupt:
        print("\nExiting...")
    
if __name__ == "__main__":
    main() 