# Link Extraction and Categorization

## Overview

The data ingestion system now includes enhanced support for extracting and categorizing links from PDF documents. This functionality allows for:

1. **Color-based extraction** - Extracts the actual color of the link text as displayed in the PDF
2. **Semantic categorization** - Categorizes links based on their color into categories like "spell", "item", "rule", etc.
3. **Consistent JSON format** - Outputs standardized JSON files with link text, target, color, and category information

## Link Categories

Links are automatically categorized based on their color:

| Category   | Colors                         | Examples                          |
|------------|--------------------------------|-----------------------------------|
| monster    | #a70000, #bc0f0f               | Rat, Dragon                       |
| spell      | #704cd9                        | Fireball, Bless                   |
| skill      | #036634, #11884c               | Acrobatics, Perception            |
| item       | #623a1e, #774521, #0f5cbc      | Dagger, Potion of Healing         |
| rule       | #6a5009, #9b740b, #efb311      | D20 Test, Total Cover, Hostile    |
| sense      | #a41b96                        | Blindsight, Darkvision            |
| condition  | #364d00, #5a8100               | Blinded, Incapacitated            |
| lore       | #a83e3e                        | Far Realm, Nine Hells             |
| reference  | #0053a3, #006abe               | chapter references, page links    |
| navigation | #141414                        | section markers, page anchors     |
| footer     | #9a9a9a, #e8f6ff               | Help Portal, Privacy Policy       |

## JSON Format

Extracted links are saved in a JSON format with this structure:

```json
[
  {
    "link_text": "Fireball",
    "source_page": 218,
    "source_rect": [222.6, 588.0, 294.0, 602.0],
    "color": "#704cd9",
    "link_category": "spell",
    "link_type": "external",
    "target_url": "https://www.dndbeyond.com/spells/fireball"
  }
]
```

## Implementation Notes

- The system extracts colors directly from the text spans in the PDF rather than relying on annotations, which ensures more accurate color detection
- As a fallback, the system will check annotation colors if no text color can be found
- Colors are normalized to a standard hex format (#RRGGBB) for consistency
- Categories are applied automatically based on the detected colors

## Debugging and Testing

To test the link extraction independently, use the `link_extractor_test.py` script in the tests directory:

```bash
# List all PDFs in the bucket, sorted by size
python tests/data_ingestion/link_extractor_test.py --list-pdfs

# Process a specific PDF
python tests/data_ingestion/link_extractor_test.py --pdf-key source-pdfs/your-file.pdf

# Process the 5 smallest PDFs
python tests/data_ingestion/link_extractor_test.py --process-all --limit 5
```

The test script provides detailed logs and saves extracted links to S3. 