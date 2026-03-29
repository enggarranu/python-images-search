import os
import base64
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

VISION_MODEL = os.getenv('VISION_MODEL', 'llava:7b')
EMBED_MODEL = os.getenv('EMBED_MODEL', 'nomic-embed-text')

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
    
    for filename in os.listdir(IMAGE_FOLDER):
        if filename.lower().endswith(('.png', '.jpg', '.jpeg')):
            image_path = os.path.join(IMAGE_FOLDER, filename)
            print(f"⏳ Memproses: {filename}...")
            
            try:
                # 1. Vision: Ekstrak deskripsi bahasa Inggris
                img_b64 = encode_image(image_path)
                vision_payload = {
                    "model": VISION_MODEL,
                    "prompt": "Describe this image in detail. What is happening? What objects are present? Reply strictly in English.",
                    "images": [img_b64],
                    "stream": False
                }
                res_vision = requests.post(f"{OLLAMA_API}/generate", json=vision_payload).json()
                description_en = res_vision.get('response', '')
                
                # 2. Translate: Terjemahkan ke Bahasa Indonesia
                print("   🔄 Menerjemahkan ke Bahasa Indonesia...")
                description_id = translate_text(description_en, "Indonesian")
                
                # 3. Embedding: Gunakan versi Inggris agar akurasi Nomic maksimal
                embed_payload = {
                    "model": EMBED_MODEL,
                    "prompt": description_en
                }
                res_embed = requests.post(f"{OLLAMA_API}/embeddings", json=embed_payload).json()
                vector = res_embed.get('embedding', [])
                
                # 4. Simpan ke TiDB (Masukkan kedua deskripsi)
                vector_str = "[" + ",".join(map(str, vector)) + "]"
                
                # Update SQL untuk memasukkan file_path
                sql = """
                    INSERT INTO image_vectors 
                    (image_name, file_path, description, description_id, embedding) 
                    VALUES (%s, %s, %s, %s, %s)
                """
                
                # Masukkan image_path ke dalam eksekusi
                cursor.execute(sql, (filename, image_path, description_en, description_id, vector_str))
                conn.commit()
                            
                print(f"✅ Selesai: {filename} (Disimpan ke TiDB)")
                
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
        res_embed = requests.post(f"{OLLAMA_API}/embeddings", json=embed_payload).json()
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
        "model": TRANSLATE_MODEL,
        "prompt": f"Translate the following text to {target_lang}. Only output the translation directly without any introductory words or quotes.\n\nText: {text}",
        "stream": False
    }
    try:
        res = requests.post(f"{OLLAMA_API}/generate", json=payload).json()
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