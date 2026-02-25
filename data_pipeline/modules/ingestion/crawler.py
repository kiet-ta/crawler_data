"""
Web Crawler Module for Template Discovery

This module implements an async Playwright-based crawler to discover and download
real estate document templates from the web.

Why Playwright: Playwright provides better anti-bot evasion capabilities compared
to simple HTTP clients, handles JavaScript-heavy sites, and supports human-like
interaction patterns that reduce the risk of being blocked.
"""

import asyncio
import random
from typing import List, Optional, Dict, Any
from pathlib import Path
from playwright.async_api import async_playwright, Browser, Page, TimeoutError as PlaywrightTimeout

from config import PipelineConfig
from utils.logger import setup_logger, log_with_context


logger = setup_logger(__name__)


class TemplateCrawler:
    """
    Async web crawler for discovering real estate document templates.
    
    Why async: Asynchronous execution allows us to perform I/O-bound operations
    (network requests, page loading) concurrently, significantly reducing total
    crawling time compared to sequential execution.
    """
    
    def __init__(self):
        """Initialize the crawler with configuration settings."""
        self.user_agent = PipelineConfig.CRAWLER_USER_AGENT
        self.headless = PipelineConfig.CRAWLER_HEADLESS
        self.min_delay = PipelineConfig.CRAWLER_MIN_DELAY
        self.max_delay = PipelineConfig.CRAWLER_MAX_DELAY
        self.browser: Optional[Browser] = None
        
    async def _human_delay(self) -> None:
        """
        Introduce random delay to mimic human behavior.
        
        Why: Anti-bot systems detect automated scraping by analyzing request timing.
        Random delays between min and max values create more natural traffic patterns
        that are harder to distinguish from human users.
        """
        delay = random.uniform(self.min_delay, self.max_delay)
        log_with_context(logger, 'debug', 'Applying human-like delay', delay_seconds=delay)
        await asyncio.sleep(delay)
        
    async def _random_mouse_movement(self, page: Page) -> None:
        """
        Simulate random mouse movements on the page.
        
        Args:
            page: Playwright page instance
            
        Why: Some sophisticated anti-bot systems track mouse movements.
        Random movements add another layer of human-like behavior.
        """
        viewport_size = page.viewport_size or {"width": 1280, "height": 720}
        x = random.randint(0, viewport_size["width"])
        y = random.randint(0, viewport_size["height"])
        await page.mouse.move(x, y)
        
    async def initialize(self) -> None:
        """
        Initialize browser instance.
        
        Why: Separating initialization from __init__ allows for proper async setup
        and makes resource management more explicit. The browser instance is
        expensive to create, so we want to reuse it across multiple crawls.
        """
        logger.info("Initializing Playwright browser")
        playwright = await async_playwright().start()
        
        self.browser = await playwright.chromium.launch(
            headless=self.headless,
            args=[
                '--disable-blink-features=AutomationControlled',  # Hide automation flags
                '--disable-dev-shm-usage',
                '--no-sandbox',
            ]
        )
        logger.info("Browser initialized successfully")
        
    async def cleanup(self) -> None:
        """
        Clean up browser resources.
        
        Why: Proper resource cleanup prevents memory leaks and zombie processes.
        Always call this in a finally block or use async context managers.
        """
        if self.browser:
            logger.info("Closing browser")
            await self.browser.close()
            
    async def search_templates(self, query: str, max_results: int = 5) -> List[Dict[str, str]]:
        """
        Search for document templates using a search engine.
        
        Args:
            query: Search query string
            max_results: Maximum number of results to return
            
        Returns:
            List of dictionaries containing URL and title of found templates
            
        Why: Using a search engine as the discovery mechanism allows the crawler
        to find diverse, real-world template sources without hardcoding URLs.
        This makes the system more robust to website changes.
        
        Raises:
            RuntimeError: If browser is not initialized
            Exception: For any crawling errors (logged but not raised)
        """
        if not self.browser:
            raise RuntimeError("Browser not initialized. Call initialize() first.")
            
        results = []
        
        try:
            logger.info(f"Searching for templates: {query}")
            context = await self.browser.new_context(
                user_agent=self.user_agent,
                viewport={'width': 1280, 'height': 720},
                locale='vi-VN',  # Vietnamese locale
            )
            
            page = await context.new_page()
            
            # Navigate to search engine (using DuckDuckGo for simplicity)
            search_url = f"https://duckduckgo.com/?q={query.replace(' ', '+')}"
            await page.goto(search_url, wait_until='networkidle')
            
            await self._human_delay()
            await self._random_mouse_movement(page)
            
            # Extract search results
            # Note: In production, you'd want more sophisticated selectors
            # and error handling for different search engine layouts
            try:
                result_elements = await page.query_selector_all('article[data-testid="result"]')
                
                for i, element in enumerate(result_elements[:max_results]):
                    try:
                        # Extract title and URL
                        title_elem = await element.query_selector('h2')
                        link_elem = await element.query_selector('a[href]')
                        
                        if title_elem and link_elem:
                            title = await title_elem.inner_text()
                            url = await link_elem.get_attribute('href')
                            
                            if url:
                                results.append({
                                    'title': title.strip(),
                                    'url': url.strip()
                                })
                                log_with_context(
                                    logger, 'debug', 'Found template result',
                                    title=title.strip(), url=url.strip()
                                )
                    except Exception as elem_error:
                        # Log but continue - some results might be malformed
                        log_with_context(
                            logger, 'warning', 'Failed to parse search result element',
                            error=str(elem_error), index=i
                        )
                        continue
                        
            except PlaywrightTimeout:
                logger.warning(f"Timeout waiting for search results for query: {query}")
                
            await context.close()
            
        except Exception as e:
            # Log error but don't crash - we might still have some results
            log_with_context(
                logger, 'error', 'Error during template search',
                query=query, error=str(e), error_type=type(e).__name__
            )
            
        log_with_context(
            logger, 'info', 'Search completed',
            query=query, results_found=len(results)
        )
        return results
        
    async def crawl_all_queries(self) -> List[Dict[str, str]]:
        """
        Crawl all configured search queries.
        
        Returns:
            Combined list of all discovered templates
            
        Why: Aggregating multiple queries increases the diversity of templates
        we can discover, leading to a more robust training dataset.
        """
        all_results = []
        
        for query in PipelineConfig.TEMPLATE_SEARCH_QUERIES:
            results = await self.search_templates(query, max_results=5)
            all_results.extend(results)
            await self._human_delay()  # Delay between queries
            
        # Remove duplicates based on URL
        unique_results = {r['url']: r for r in all_results}.values()
        
        log_with_context(
            logger, 'info', 'Crawling completed',
            total_queries=len(PipelineConfig.TEMPLATE_SEARCH_QUERIES),
            unique_templates=len(unique_results)
        )
        
        return list(unique_results)


async def run_crawler() -> List[Dict[str, str]]:
    """
    Convenience function to run the crawler with proper setup and teardown.
    
    Returns:
        List of discovered template URLs and metadata
        
    Why: Encapsulates the entire crawler lifecycle in a single function,
    ensuring resources are always properly cleaned up even if errors occur.
    
    Example:
        >>> templates = await run_crawler()
        >>> print(f"Found {len(templates)} templates")
    """
    crawler = TemplateCrawler()
    
    try:
        await crawler.initialize()
        results = await crawler.crawl_all_queries()
        return results
    except Exception as e:
        log_with_context(
            logger, 'error', 'Crawler failed',
            error=str(e), error_type=type(e).__name__
        )
        raise
    finally:
        await crawler.cleanup()
