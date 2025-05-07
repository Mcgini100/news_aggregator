# news_aggregator/spiders/independent_spider.py
import scrapy
from news_aggregator.items import NewsArticleItem
from urllib.parse import urljoin

class IndependentSpider(scrapy.Spider):
    name = 'independent'
    allowed_domains = ['independent.co.uk']
    custom_settings = {
        'DOWNLOAD_DELAY': 2,
        'AUTOTHROTTLE_ENABLED': True,
    }

    category_map = {
        'business': 'https://www.independent.co.uk/news/business',
        'politics': 'https://www.independent.co.uk/news/uk/politics',
        'arts_culture_celebrities': 'https://www.independent.co.uk/arts-entertainment',
        'sports': 'https://www.independent.co.uk/sport'
    }

    def start_requests(self):
        for category_name, category_url in self.category_map.items():
            yield scrapy.Request(
                url=category_url,
                callback=self.parse_category_page,
                meta={'category': category_name, 'source': self.name}
            )

    def parse_category_page(self, response):
        category = response.meta['category']
        source = response.meta['source']
        self.logger.info(f"Parsing {source} category: {category} from {response.url}")

        promos = response.css('div.article-default, div.teaser, article.type-article, div.sc-qvZNL.hQudgO')

        if not promos:
            self.logger.warning(f"No promo blocks found for {source} {category} on {response.url}")

        for promo in promos:
            title_text = promo.css('h2 a::text, h3 a::text, a h2::text, a h3::text, a[data-behaviour="PromoLink"]::text').get()
            if not title_text:
                title_text = promo.css('a p[class*="title"]::text').get()

            relative_url = promo.css('h2 a::attr(href), h3 a::attr(href), a::attr(href)').get()

            summary_text = promo.css('div.text-wrapper p::text, div.desc ::text, p.summary::text').get()
            if not summary_text:
                 summary_text = promo.css('a > p:not([class*="title"]):not([class*="topic"]):not([class*="time"])::text').get()

            if title_text and relative_url:
                title = title_text.strip()
                url = response.urljoin(relative_url)

                if not url.startswith('https://www.independent.co.uk/'):
                    continue
                if any(x in url for x in ['/live/', '/topic/', '/vouchercodes', '/compare', '/indybest', '/extras', '/author/', '/tv/','/weather/']):
                    self.logger.debug(f"Skipping non-story URL: {url}")
                    continue
                if len(title) < 10:
                    self.logger.debug(f"Skipping potentially non-story item with short title: {title} from {url}")
                    continue

                # Prepare item data
                item_data = NewsArticleItem()
                item_data['source'] = source
                item_data['category'] = category
                item_data['title'] = title
                item_data['url'] = url
                item_data['summary'] = summary_text.strip() if summary_text else None
                item_data['full_content'] = None # Initialize

                # Instead of yielding item here, yield a request to the article page
                yield scrapy.Request(
                    url=item_data['url'],
                    callback=self.parse_article_page,
                    meta={'item_data': item_data} # Pass the partially filled item
                )
            else:
                if not title_text: self.logger.debug(f"No title for a promo in {source} {category}")
                if not relative_url: self.logger.debug(f"No URL for a promo in {source} {category}")


    def parse_article_page(self, response):
        item = response.meta['item_data']
        self.logger.info(f"Parsing article page: {item['url']}")

        article_body_element = response.css('div#main') # <--- USE THIS AS THE MAIN CONTAINER

        full_text_paragraphs = []
        if article_body_element:
            # We want to get <p> tags that are direct children of div#main,
            # or children of generic divs directly under div#main,
            # but try to avoid <p> tags inside known ad/promo/widget containers.

            # Strategy:
            # 1. Get all <p> tags directly under div#main or one level down inside a simple div.
            # 2. Filter out paragraphs that are inside elements we want to ignore (ads, newsletter, figures).

            # Select all <p> elements within div#main
            all_paragraphs_in_main = article_body_element.css('p')

            for p_tag in all_paragraphs_in_main:
                # Check if the paragraph is inside any of the known "bad" containers.
                # We can check the ancestors of the p_tag.
                # The `xpath('ancestor::*[@id="taboola-mid-article-thumbnails-ii" or contains(@class, "newsletter-component") or contains(@class, "trc_related_container") or @data-mpu1 or @data-component="Newsletter" or ancestor::figure]')`
                # checks if any ancestor has those specific attributes.
                is_inside_unwanted_element = p_tag.xpath(''
                    'ancestor::aside[contains(@class, "newsletter-component")] | '
                    'ancestor::*[@data-component="Newsletter"] | '
                    'ancestor::div[contains(@class, "sc-1048kfq-0")] | ' # MPU ad container class
                    'ancestor::div[contains(@id, "taboola-")] | '        # Taboola containers
                    'ancestor::div[contains(@class, "trc_related_container")] | '
                    'ancestor::figure | '                                 # Exclude image captions within <figure>
                    'ancestor::div[contains(@class, "sc-toncsa-0")]'      # Another Taboola container wrapper
                ).get()

                if not is_inside_unwanted_element:
                    # If not inside an unwanted element, extract its text
                    paragraph_text_nodes = p_tag.css('::text').getall()
                    cleaned_paragraph = " ".join(node.strip() for node in paragraph_text_nodes if node.strip()).strip()
                    if cleaned_paragraph and len(cleaned_paragraph) > 10: # Only keep reasonably long, non-empty paragraphs
                        full_text_paragraphs.append(cleaned_paragraph)
                # else:
                #     self.logger.debug(f"Skipping paragraph inside unwanted element: {p_tag.get()[:100]}")


            if full_text_paragraphs:
                item['full_content'] = "\n\n".join(full_text_paragraphs)
            else:
                # Fallback if the above sophisticated filtering yields nothing (unlikely with div#main but good to have)
                self.logger.warning(f"Advanced paragraph filtering yielded no content for {response.url}. Trying broader extraction from div#main, this might be noisy.")
                # This fallback will be very noisy as it includes everything, but better than nothing if the logic above fails.
                all_text_nodes = article_body_element.xpath(''
                    './/text()[not(ancestor::aside[contains(@class, "newsletter-component")]) '
                    'and not(ancestor::*[@data-component="Newsletter"]) '
                    'and not(ancestor::script) '
                    'and not(ancestor::style) '
                    'and not(ancestor::div[contains(@class, "sc-1048kfq-0")])'
                    'and not(ancestor::div[contains(@id, "taboola-")])'
                    'and not(ancestor::div[contains(@class, "trc_related_container")])'
                    'and not(ancestor::figure/figcaption)]' # Try to get text unless it's in a figcaption
                ).getall()
                item['full_content'] = "\n\n".join(text.strip() for text in all_text_nodes if text.strip() and len(text.strip()) > 10)

            if not item['full_content']:
                 self.logger.warning(f"Extracted empty full_content for URL: {response.url} from div#main.")

        else:
            self.logger.warning(f"Could not find article body container 'div#main' for URL: {response.url}")
            item['full_content'] = "CONTENT_NOT_FOUND_CONTAINER_MISSING"

        yield item