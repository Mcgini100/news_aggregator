# news_aggregator/pipelines.py
import csv
from itemadapter import ItemAdapter
import os

class PerSourceCategoryCsvPipeline:
    def open_spider(self, spider):
        self.spider = spider
        self.output_folder = "scraped_data"
        os.makedirs(self.output_folder, exist_ok=True)

        self.source_category_files = {}
        self.source_category_writers = {}
        # Define the fieldnames for CSV header, must match item fields
        self.fieldnames = ['title', 'url', 'summary', 'category', 'source', 'full_content'] # <--- ADD 'full_content' HERE

    def close_spider(self, spider):
        for f in self.source_category_files.values():
            f.close()

    def process_item(self, item, spider):
        adapter = ItemAdapter(item)
        source = adapter.get('source')
        category = adapter.get('category')

        if not source or not category:
            spider.logger.error(f"Missing source or category in item: {item}")
            return item

        file_key = f"{source}_{category}"

        if file_key not in self.source_category_writers:
            filename = os.path.join(self.output_folder, f"{source.lower()}_{category.lower().replace(' ', '_')}.csv")
            self.source_category_files[file_key] = open(filename, 'w', newline='', encoding='utf-8')
            self.source_category_writers[file_key] = csv.DictWriter(
                self.source_category_files[file_key],
                fieldnames=self.fieldnames
            )
            self.source_category_writers[file_key].writeheader()

        row_data = {field: adapter.get(field) for field in self.fieldnames}
        self.source_category_writers[file_key].writerow(row_data)
        return item