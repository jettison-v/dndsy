# PDF Link Extraction Process

## Overview

The data ingestion system, primarily within `processor.py`, is responsible for extracting hyperlink information from source PDF documents during processing. This process utilizes the `PyMuPDF` (fitz) library.

**Key functions include:**

1.  **Link Detection:** Identifying internal document links (GOTO) and external web links (URI) using `page.get_links()`.
2.  **Text Extraction:** Attempting to extract the visible text associated with each link's bounding box (`link['from']`).
3.  **Color/Category Extraction:** Analyzing text span colors or annotation colors near the link to determine its display color and infer a semantic category (see below).
4.  **Target Information:** Recording the target page number (for internal links) or target URL (for external links).
5.  **Snippet Generation:** For internal links, attempting to extract a contextual snippet from the target page.
6.  **Output:** Saving the extracted link data for *each processed PDF* as a separate JSON file to AWS S3 under the `extracted_links/` prefix (e.g., `s3://<bucket>/extracted_links/path/to/document.pdf.links.json`).

This extracted link data is later aggregated and queried by the backend application (`app.py`/`llm.py`) to dynamically insert relevant links into AI chat responses.

## Link Data JSON Format

Extracted links for a single PDF are saved as a JSON array, where each object represents one link found in the document.

```json
[
  {
    "link_text": "Fireball", // The visible text associated with the link
    "source_page": 218,      // The page number in the source PDF where the link was found
    "source_rect": [         // Bounding box [x0, y0, x1, y1] of the link on the source page
      222.6,
      588.0,
      294.0,
      602.0
    ],
    "color": "#704cd9",      // Detected color of the link text (hex format, optional)
    "link_category": "spell",// Semantic category inferred from color (optional)
    "link_type": "external", // "internal" (GOTO) or "external" (URI)
    "target_page": null,     // Target page number (for internal links only)
    "target_url": "https://www.dndbeyond.com/spells/fireball", // Target URL (for external links only)
    "target_snippet": null   // Text snippet from target page (for internal links only, optional)
  },
  {
    "link_text": "Chapter 9",
    "source_page": 5,
    "source_rect": [ ... ],
    "color": "#0053a3",
    "link_category": "reference",
    "link_type": "internal",
    "target_page": 173,
    "target_url": null,
    "target_snippet": "Chapter 9: Combat..." // Example snippet
  }
  // ... more link objects
]
```

## Color Extraction and Categorization

The system attempts to determine the display color of the link text to aid categorization and potentially frontend styling.

*   **Primary Method:** Extracts color directly from the text spans (`page.get_text('dict')`) that overlap with the link's bounding box.
*   **Fallback Method:** If no color is found via text spans, it checks nearby PDF annotations for color information (`annot.colors`).
*   **Normalization:** Colors are normalized to a standard hex format (`#RRGGBB`).
*   **Categorization:** If a color is successfully extracted, it's mapped to a semantic category using the `COLOR_CATEGORY_MAP` defined in `processor.py`:

| Category   | Example Colors                 | Examples                          |
|------------|--------------------------------|-----------------------------------|
| monster    | `#a70000`, `#bc0f0f`           | Rat, Dragon                       |
| spell      | `#704cd9`                      | Fireball, Bless                   |
| skill      | `#036634`, `#11884c`           | Acrobatics, Perception            |
| item       | `#623a1e`, `#774521`, `#0f5cbc`| Dagger, Potion of Healing         |
| rule       | `#6a5009`, `#9b740b`, `#efb311`| D20 Test, Total Cover, Hostile    |
| sense      | `#a41b96`                      | Blindsight, Darkvision            |
| condition  | `#364d00`, `#5a8100`           | Blinded, Incapacitated            |
| lore       | `#a83e3e`                      | Far Realm, Nine Hells             |
| reference  | `#0053a3`, `#006abe`           | chapter references, page links    |
| navigation | `#141414`                      | section markers, page anchors     |
| footer     | `#9a9a9a`, `#e8f6ff`           | Help Portal, Privacy Policy       |

*(Note: The exact color mapping is defined in `processor.py`)*

## Data Duplication

*   **Within a File:** If a PDF links the same text/target multiple times on different pages or locations, each instance will likely result in a separate entry in that PDF's `.links.json` file.
*   **Across Files:** Common terms (e.g., "Player's Handbook", "Armor Class") will appear in the link files for multiple different source PDFs, leading to duplication of link data across the `extracted_links/` directory. The backend retrieval logic is responsible for handling this when selecting links for a specific chat response.

## Debugging and Testing

*(Note: Verify if `link_extractor_test.py` exists and update/remove this section as needed)*

To test the link extraction independently, use the `link_extractor_test.py` script in the `tests/` directory:

```bash
# List all PDFs in the bucket, sorted by size
python tests/data_ingestion/link_extractor_test.py --list-pdfs

# Process a specific PDF
python tests/data_ingestion/link_extractor_test.py --pdf-key source-pdfs/your-file.pdf

# Process the 5 smallest PDFs
python tests/data_ingestion/link_extractor_test.py --process-all --limit 5
```

The test script provides detailed logs and saves extracted links to S3. 