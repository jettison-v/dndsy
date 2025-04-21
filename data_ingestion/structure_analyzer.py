import re
from typing import Dict, List, Tuple, Any, Optional, Set


class DocumentStructureAnalyzer:
    """
    Utility class to analyze and extract document structure from PDFs.
    Identifies heading levels based on font sizes and other attributes.
    """
    
    def __init__(self):
        # Initialize with empty structure
        self.heading_sizes = []  # List of sizes for heading levels (largest to smallest)
        self.size_to_level = {}  # Mapping of font sizes to heading levels
        self.heading_styles = {}  # Information about each heading level
        
        # Store document structure
        self.toc = []  # Table of contents with hierarchical structure
        self.current_path = []  # Current heading path as we process the document
        
        # Track heading sizes we've seen
        self.font_sizes = {}  # Font size distribution data
        self.heading_candidates = set()  # Set of sizes that are likely headings
        
        # Active document metadata
        self.current_doc = ""  # Current document being processed
        self.pages_seen = 0
        
    def analyze_font_style(self, font: str, size: float, flags: int, text: str) -> None:
        """Track font styles to identify potential headings"""
        # Create a key for this font style
        style_key = f"{font}_{size}_{flags}"
        
        if style_key not in self.font_sizes:
            self.font_sizes[style_key] = {
                "font": font,
                "size": size,
                "flags": flags,
                "count": 0,
                "pages": set(),
                "examples": []
            }
        
        self.font_sizes[style_key]["count"] += 1
        
        # Keep a few example texts for this style
        if len(self.font_sizes[style_key]["examples"]) < 3 and text.strip():
            display_text = text.strip()[:50] + ("..." if len(text) > 50 else "")
            if display_text not in self.font_sizes[style_key]["examples"]:
                self.font_sizes[style_key]["examples"].append(display_text)
    
    def analyze_page(self, page_dict: Dict[str, Any], page_num: int) -> None:
        """Analyze a page's text formatting to build style statistics"""
        if not page_dict or 'blocks' not in page_dict:
            return
            
        # Track this as a page we've analyzed
        self.pages_seen += 1
        
        # Process all text spans to gather font statistics
        for block in page_dict['blocks']:
            if block.get("type") == 0:  # Text blocks only
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        size = span.get("size", 0)
                        font = span.get("font", "unknown")
                        text = span.get("text", "").strip()
                        flags = span.get("flags", 0)
                        
                        if text:  # Skip empty text
                            self.analyze_font_style(font, size, flags, text)
                            
                            # Track the page this style appears on
                            style_key = f"{font}_{size}_{flags}"
                            self.font_sizes[style_key]["pages"].add(page_num)
    
    def determine_heading_levels(self, min_pages_seen: int = 2) -> None:
        """Determine heading levels based on collected font statistics"""
        # Consider styles that appear on multiple pages as potential headings
        candidates = []
        for style_key, info in self.font_sizes.items():
            # A style should appear on multiple pages to be a heading
            if len(info["pages"]) >= min_pages_seen:
                candidates.append(info)
        
        # Sort by font size (largest first)
        candidates.sort(key=lambda x: x["size"], reverse=True)
        
        # Group sizes into clusters
        size_clusters = []
        prev_size = None
        
        for candidate in candidates:
            size = candidate["size"]
            
            # Start a new cluster if this is the first size or significantly different
            if prev_size is None or (prev_size - size) > 1.0:
                size_clusters.append([size])
            else:
                # Add to current cluster if close to previous size
                size_clusters[-1].append(size)
                
            prev_size = size
        
        # Take the largest size from each cluster as a heading level
        self.heading_sizes = [cluster[0] for cluster in size_clusters[:6]]  # Up to 6 levels
        
        # Create mapping of sizes to heading levels
        self.size_to_level = {}
        for i, cluster in enumerate(size_clusters[:6]):
            level = i + 1  # 1-based heading levels
            for size in cluster:
                self.size_to_level[size] = level
                self.heading_candidates.add(size)
    
    def is_heading(self, text: str, font_size: float, is_bold: bool) -> Tuple[bool, int]:
        """Determine if text is a heading and its level"""
        if font_size not in self.size_to_level:
            return False, 0
            
        level = self.size_to_level[font_size]
        
        # Top level headings are almost certainly headings
        if level == 1:
            return True, level
            
        # For lower levels, use additional heuristics
        if is_bold:
            return True, level
        if len(text) < 100:  # Short text might be a heading
            return True, level
        if text.endswith(':'):  # Ends with colon suggests a heading
            return True, level
            
        # Less certain for longer text without special formatting
        return False, 0
    
    def get_heading_info(self, block_dict: Dict[str, Any]) -> Tuple[str, float, bool, int]:
        """Extract heading information from a block"""
        block_text = ""
        max_size = 0
        is_bold = False
        
        for line in block_dict.get("lines", []):
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
        
        # Determine if this is a heading and its level
        is_heading, level = self.is_heading(block_text, max_size, is_bold)
        
        return block_text, max_size, is_bold, level
    
    def process_page_headings(self, page_dict: Dict[str, Any], page_num: int) -> List[Dict[str, Any]]:
        """Process headings on a page and update document structure"""
        if not self.heading_sizes:
            # If we haven't determined heading levels yet, can't process headings
            return []
            
        page_headings = []
        
        for block in page_dict.get('blocks', []):
            if block.get("type") == 0:  # Text blocks only
                block_text, font_size, is_bold, level = self.get_heading_info(block)
                
                if not block_text or level == 0:
                    continue
                    
                # This is a heading - add to our structure
                heading = {
                    "level": level,
                    "text": block_text,
                    "page": page_num,
                    "font_size": font_size,
                    "is_bold": is_bold
                }
                
                page_headings.append(heading)
                
                # Add to table of contents
                self._add_to_toc(heading)
                
                # Update current path for context tracking
                self._update_current_path(heading)
        
        return page_headings
    
    def _add_to_toc(self, heading: Dict[str, Any]) -> None:
        """Add a heading to the table of contents"""
        self.toc.append(heading)
    
    def _update_current_path(self, heading: Dict[str, Any]) -> None:
        """Update the current heading path with a new heading"""
        level = heading["level"]
        
        # Truncate path to one level above this heading's level
        if level <= len(self.current_path):
            self.current_path = self.current_path[:level-1]
            
        # Add this heading to the path
        self.current_path.append(heading)
    
    def get_current_context(self) -> Dict[str, Any]:
        """Get the current hierarchical context as structured metadata"""
        result = {
            "document": self.current_doc,
            "heading_path": [],
            "section": None,
            "subsection": None
        }
        
        # Build heading path
        if self.current_path:
            result["heading_path"] = [h["text"] for h in self.current_path]
            
            # Set section (highest level)
            if len(self.current_path) > 0:
                result["section"] = self.current_path[0]["text"]
                
            # Set subsection (second level if available)
            if len(self.current_path) > 1:
                result["subsection"] = self.current_path[1]["text"]
                
            # Create full hierarchical context
            for i, heading in enumerate(self.current_path):
                level_key = f"h{heading['level']}"
                result[level_key] = heading["text"]
        
        return result
    
    def reset_for_document(self, document_name: str) -> None:
        """Reset the analyzer for a new document"""
        # Keep heading level information if we've analyzed docs before
        
        # Reset document-specific state
        self.current_doc = document_name
        self.current_path = [] 
        self.toc = []
        self.pages_seen = 0 