
# Python Image Search

A Python library for searching and retrieving images based on various criteria using Ollama.

## Features

- Fast image search functionality
- Support for multiple image formats
- Easy-to-use API
- Filtering and sorting capabilities

## Installation

install python dependencies
```bash
pip install requests pymysql python-dotenv
```

Pull Model AI Lokal (Ollama)
Pastikan Ollama sudah berjalan, lalu unduh model yang dibutuhkan:

```Bash
ollama pull llava:7b
ollama pull nomic-embed-text
```

Jalankan kueri SQL berikut di konsol TiDB Anda untuk membuat tabel penampung vektor gambar:

```
SQL
CREATE DATABASE IF NOT EXISTS smart_gallery;
USE smart_gallery;

CREATE TABLE image_vectors (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    image_name VARCHAR(255) NOT NULL,
    description TEXT,
    -- nomic-embed-text menghasilkan vektor dengan 768 dimensi
    embedding VECTOR<FLOAT>(768),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

## Quick Start

```python
from image_search import ImageSearch

searcher = ImageSearch()
results = searcher.search("query")
```

## Usage

```python
# Search for images
results = searcher.search("cat", limit=10)

# Filter results
filtered = [img for img in results if img.size > 1000]
```

## Requirements

- Python 3.8+
- Ollama

## License

MIT

## Contributing

Contributions are welcome. Please submit pull requests or open issues.
