import os
import base64
import hashlib
import requests
import pymysql
from dotenv import load_dotenv

# Load kredensial dari file .env
load_dotenv()

# ==========================================
# KONFIGURASI
# ==========================================
OLLAMA_API = os.getenv('OLLAMA_API')
IMAGE_FOLDER = os.getenv('IMAGE_FOLDER') 

VISION_MODEL = os.getenv('VISION_MODEL') or 'llava:7b'
EMBED_MODEL = os.getenv('EMBED_MODEL') or 'nomic-embed-text'
REQUEST_TIMEOUT = int(os.getenv('REQUEST_TIMEOUT', 30))

def connect_db():
    return pymysql.connect(
        host=os.getenv('DB_HOST'),
        port=int(os.getenv('DB_PORT', 4000)),
        user=os.getenv('DB_USERNAME'),
        password=os.getenv('DB_PASSWORD'),
        database=os.getenv('DB_DATABASE', 'smart_gallery'),
        ssl={'ssl': {}} # Wajib untuk TiDB Cloud
    )

def encode_image(image_path):
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')

# ==========================================
# FASE 1: INDEXING GAMBAR
# ==========================================
def index_images():
    conn = connect_db()
    cursor = conn.cursor()
    
    print(f"Memulai proses indexing pada folder: {IMAGE_FOLDER}\n")
    exts = ('.png', '.jpg', '.jpeg', '.heic')
    file_paths = []
    for root, _, names in os.walk(IMAGE_FOLDER):
        for name in names:
            if name.lower().endswith(exts):
                file_paths.append(os.path.join(root, name))
    total = len(file_paths)
    if total == 0:
        print("Tidak ada file gambar yang ditemukan.")
        conn.close()
        return
    
    for idx, image_path in enumerate(file_paths, 1):
        filename = os.path.basename(image_path)
        pct = int(((idx - 1) / total) * 100)
        print(f"⏳ Memproses ({idx}/{total}, ~{pct}%): {filename}...")
        
        try:
            img_b64 = encode_image(image_path)
            vision_payload = {
                "model": VISION_MODEL,
                "prompt": "Describe this image in detail. What is happening? What objects are present? Reply strictly in English.",
                "images": [img_b64],
                "stream": False
            }
            res_vision = requests.post(f"{OLLAMA_API}/generate", json=vision_payload, timeout=REQUEST_TIMEOUT).json()
            description_en = res_vision.get('response', '')
            
            print("   🔄 Menerjemahkan ke Bahasa Indonesia...")
            description_id = translate_text(description_en, "Indonesian")
            
            embed_payload = {
                "model": EMBED_MODEL,
                "prompt": description_en
            }
            res_embed = requests.post(f"{OLLAMA_API}/embeddings", json=embed_payload, timeout=REQUEST_TIMEOUT).json()
            vector = res_embed.get('embedding', [])
            vector_str = "[" + ",".join(map(str, vector)) + "]"
            
            path_hash = hashlib.md5(image_path.encode('utf-8')).hexdigest()
            sql_upsert = """
                INSERT INTO image_vectors 
                (image_name, file_path, path_hash, description, description_id, embedding) 
                VALUES (%s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE 
                  file_path=VALUES(file_path),
                  path_hash=VALUES(path_hash),
                  description=VALUES(description),
                  description_id=VALUES(description_id),
                  embedding=VALUES(embedding),
                  updated_at=CURRENT_TIMESTAMP
            """
            cursor.execute(sql_upsert, (filename, image_path, path_hash, description_en, description_id, vector_str))
            action = "Diupdate" if cursor.rowcount == 2 else "Disimpan"
            conn.commit()
            done_pct = int((idx / total) * 100)
            print(f"✅ {action}: {filename} (Progress {idx}/{total}, {done_pct}%)")
            
        except Exception as e:
            print(f"❌ Error memproses {filename}: {e}")
            
    conn.close()
    print("\nProses Indexing Selesai!")

# ==========================================
# FASE 2: PENCARIAN (SEMANTIC SEARCH)
# ==========================================
def search_images(search_query, limit=3):
    conn = connect_db()
    cursor = conn.cursor()
    
    print(f"\n🔍 Kueri asli Anda: '{search_query}'")
    
    try:
        # 1. Translate kueri ke bahasa Inggris untuk pencarian vektor
        query_en = translate_text(search_query, "English")
        print(f"🧠 AI menerjemahkan kueri menjadi: '{query_en}'")
        
        # 2. Ubah kueri Inggris menjadi vektor
        embed_payload = {"model": EMBED_MODEL, "prompt": query_en}
        res_embed = requests.post(f"{OLLAMA_API}/embeddings", json=embed_payload, timeout=REQUEST_TIMEOUT).json()
        query_vector = "[" + ",".join(map(str, res_embed['embedding'])) + "]"
        
        # 3. Ambil hasil dari TiDB (panggil juga kolom file_path)
        sql = """
            SELECT 
                image_name, 
                file_path,
                description,
                description_id,
                VEC_COSINE_DISTANCE(embedding, %s) as distance 
            FROM image_vectors 
            ORDER BY distance ASC 
            LIMIT %s
        """
        #debug
        print("SQL Query:", sql)
        print("Parameters:", (query_vector, limit))
        cursor.execute(sql, (query_vector, limit))
        results = cursor.fetchall()
        
        
        print("\n--- Hasil Pencarian Teratas ---")
        for idx, row in enumerate(results, 1):
            # Penyesuaian index row karena kita menambahkan file_path di urutan ke-2 (index 1)
            image_name = row[0]
            file_path = row[1]
            desc_en = row[2]
            desc_id = row[3]
            distance = row[4]
            
            print(f"{idx}. 📸 File: {image_name} (Skor Kedekatan: {distance:.4f})")
            print(f"   📂 Lokasi: {file_path}")
            print(f"   🇮🇩 ID: {desc_id}")
            print(f"   🇬🇧 EN: {desc_en}\n")
            
    except Exception as e:
        print(f"❌ Error saat pencarian: {e}")
        
    finally:
        conn.close()

def translate_text(text, target_lang="Indonesian"):
    payload = {
        "model": os.getenv('TRANSLATE_MODEL', 'llava:7b'),
        "prompt": f"Translate the following text to {target_lang}. Only output the translation directly without any introductory words or quotes.\n\nText: {text}",
        "stream": False,
        "options": {"temperature": 0, "num_ctx": 2048, "max_tokens": 256}
    }
    try:
        res = requests.post(f"{OLLAMA_API}/generate", json=payload, timeout=REQUEST_TIMEOUT).json()
        return res.get('response', '').strip()
    except Exception as e:
        print(f"⚠️ Gagal menerjemahkan: {e}")
        return text # Jika gagal, kembalikan teks aslinya
    
if __name__ == "__main__":
    while True:
        print("\n" + "="*45)
        print(" 🤖 SMART GALLERY CLI - MENU UTAMA 🤖 ")
        print("="*45)
        print("1. 📥 Indexing Foto (Analisis AI & Simpan ke DB)")
        print("2. 🔍 Cari Foto (Semantic Search AI)")
        print("3. 🚪 Keluar")
        print("="*45)
        
        pilihan = input("Masukkan pilihan Anda (1/2/3): ")
        
        if pilihan == '1':
            konfirmasi = input(f"Anda yakin ingin memproses semua foto di folder {IMAGE_FOLDER}? (y/n): ")
            if konfirmasi.lower() == 'y':
                index_images()
            else:
                print("Dibatalkan.")
                
        elif pilihan == '2':
            search_query = input("\nMasukkan kueri pencarian (contoh: 'family at the beach'): ")
            
            # Memastikan input tidak kosong
            if search_query.strip():
                try:
                    limit_input = input("Berapa jumlah hasil maksimal yang ingin ditampilkan? (default: 3): ")
                    limit = int(limit_input) if limit_input.strip() else 3
                    search_images(search_query, limit)
                except ValueError:
                    print("⚠️ Input limit harus berupa angka! Menggunakan default 3.")
                    search_images(search_query, 3)
            else:
                print("⚠️ Kueri pencarian tidak boleh kosong!")
                
        elif pilihan == '3':
            print("\nMematikan sistem Smart Gallery. Sampai jumpa!")
            break
            
        else:
            print("\n❌ Pilihan tidak valid. Silakan masukkan angka 1, 2, atau 3.")
