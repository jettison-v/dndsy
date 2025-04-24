# D&D 2024 External Sources Enhancement Roadmap

## Current Implementation Status

The current external sources integration provides a proof of concept with:

- A vector store architecture (`DnDBeyondForumStore`) that integrates with the main application
- A basic data model for forum posts with threading, authors, timestamps, etc.
- A simple crawling script for Stack Exchange data
- A sample data fetching script for retrieving specific questions by ID
- A custom data insertion script for manually adding high-quality content
- UI integration showing external sources with distinct styling (red source pills)
- 28 total documents in the store (12 initial + 13 from fetch script + 3 custom)

## Enhancement Goals

The goal is to scale this proof of concept into a comprehensive external knowledge system specifically focused on D&D 2024 rules, including:

1. **Richer Content**: Detailed explanations, clarifications, and examples of the 2024 rules
2. **Diverse Sources**: Official sources, community discussions, designer insights, and expert analysis
3. **High Quality**: Curated, accurate information that complements the official rules
4. **Freshness**: Regular updates to capture evolving interpretations and clarifications
5. **Contextual Relevance**: Ability to find the most relevant external content for specific queries

## Technical Implementation Plan

### 1. Enhanced Crawling Infrastructure

- **Multi-Source Support**:
  ```python
  class BaseCrawler:
      """Base crawler class with common functionality."""
      
  class StackExchangeCrawler(BaseCrawler):
      """Specialized crawler for Stack Exchange sites."""
      
  class RedditCrawler(BaseCrawler):
      """Specialized crawler for Reddit communities."""
  ```

- **Authentication & Rate Limiting**:
  ```python
  class AuthenticatedCrawler(BaseCrawler):
      """Base class for crawlers requiring authentication."""
      def __init__(self, credentials):
          self.session = self._create_authenticated_session(credentials)
          self.rate_limiter = RateLimiter(requests_per_minute=30)
  ```

- **Scheduling System**:
  ```python
  from apscheduler.schedulers.background import BackgroundScheduler
  
  scheduler = BackgroundScheduler()
  scheduler.add_job(crawl_dnd_beyond, 'interval', days=1)
  scheduler.add_job(crawl_reddit, 'interval', hours=12)
  scheduler.start()
  ```

### 2. Additional Data Sources

- **Reddit Communities**:
  - r/dndnext, r/UnearthedArcana, r/DnDBehindTheScreen
  - Use PRAW (Python Reddit API Wrapper) or Reddit's official API

- **Twitter/X Content**:
  - Follow key D&D designers and official accounts
  - Filter for threads discussing 2024 rules

- **YouTube Transcripts**:
  - Channels like "Web DM," "Dungeon Dudes," "Treantmonk's Temple"
  - Use youtube-transcript-api for extraction

- **D&D Beyond Articles and Forums**:
  - Expand existing crawler to capture official articles
  - Add forum section filtering for 2024 rules discussions

- **WotC Official Content**:
  - Blog posts, Sage Advice, errata documents
  - Dragon+ magazine articles

### 3. Content Curation System

- **Web Interface**:
  - Flask-based admin panel for content management
  - Authentication for curators

- **Data Structure**:
  ```python
  class CuratedContent:
      """Model for manually curated content."""
      id: str
      title: str
      content: str
      source: str
      source_url: str
      tags: List[str]
      rules_references: List[str]  # References to specific rules
      curator: str
      date_added: datetime
      status: Literal["pending", "approved", "rejected"]
  ```

- **Moderation Workflow**:
  1. Content submission (manual or automated)
  2. Initial filtering (relevance, quality)
  3. Curator review
  4. Approval and tagging
  5. Addition to vector store

### 4. Synthetic Content Generation

- **Rules Comparison Content**:
  ```python
  def generate_rule_comparison(rule_name, old_text, new_text):
      """Generate comparison between 5e and 2024 rules."""
      prompt = f"""
      Compare the following D&D rules:
      
      5E RULE: {old_text}
      
      2024 RULE: {new_text}
      
      Explain the key differences, implications for gameplay, 
      and provide 2-3 examples of how this changes in practice.
      """
      # Call OpenAI API with prompt
  ```

- **FAQ Generation**:
  - Identify common questions from existing sources
  - Use GPT-4 to generate comprehensive answers based on 2024 rules
  - Have human reviewers fact-check and approve

## Implementation Timeline

### Phase 1: Infrastructure Enhancement (1-2 weeks)
- Refactor current crawler into modular architecture
- Implement authentication and rate limiting
- Set up scheduler for regular updates
- Enhance error handling and logging

### Phase 2: Source Expansion (2-4 weeks)
- Add Reddit crawler integration
- Add Twitter/X integration
- Implement YouTube transcript extraction
- Expand D&D Beyond crawling

### Phase 3: Curation System (3-5 weeks)
- Design and implement admin interface
- Create moderation workflow
- Set up authentication for curators
- Build content submission forms

### Phase 4: Content Generation & Population (Ongoing)
- Generate synthetic comparisons between editions
- Create FAQs for common rules questions
- Build example library of character builds using 2024 rules

## Challenges and Considerations

### Technical Challenges
- **Rate Limiting**: Many APIs have strict rate limits that will require careful management
- **Data Freshness**: Need to balance update frequency with system resources
- **Content Extraction**: Different sources require different parsing strategies
- **Scalability**: Vector store performance as content grows

### Content Challenges
- **Accuracy**: Ensuring external content correctly interprets the 2024 rules
- **Redundancy**: Avoiding duplicate or nearly-identical content
- **Staleness**: Removing outdated content as rules clarifications emerge
- **Context Preservation**: Maintaining the nuance and context of discussions

### Legal/Ethical Considerations
- **Copyright**: Ensure content usage complies with fair use and attribution requirements
- **Terms of Service**: Respect the ToS of each source platform
- **Privacy**: Handle attribution appropriately
- **Transparency**: Clearly mark content sources and synthetic content

## Immediate Next Steps

1. **Forum Expansion**: Add crawlers for 2-3 additional D&D forums focused on 2024 rules
2. **Filtering System**: Implement better tagging and filtering of content by topic
3. **Quality Metrics**: Create a scoring system to prioritize high-quality external content
4. **UI Enhancement**: Improve how external sources are displayed and accessed

## Long-term Vision

The eventual goal is to create the most comprehensive and accurate external knowledge base for D&D 2024 rules, serving as a community-driven companion to the official documentation. This system will not only answer rules questions but provide context, examples, and practical applications that help players and DMs understand and enjoy the new edition. 