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
                # 1. Vision: Ekstrak deskripsi gambar dengan Llava
                img_b64 = encode_image(image_path)
                vision_payload = {
                    "model": VISION_MODEL,
                    "prompt": "Describe this image in detail. What is happening? What objects are present? Reply in English.",
                    "images": [img_b64],
                    "stream": False
                }
                res_vision = requests.post(f"{OLLAMA_API}/generate", json=vision_payload).json()
                description = res_vision.get('response', '')
                
                # 2. Embedding: Ubah teks menjadi Vektor dengan Nomic
                embed_payload = {
                    "model": EMBED_MODEL,
                    "prompt": description
                }
                res_embed = requests.post(f"{OLLAMA_API}/embeddings", json=embed_payload).json()
                vector = res_embed.get('embedding', [])
                
                # 3. Simpan ke TiDB (Format array Python -> String list "[0.1, 0.2, ...]")
                vector_str = "[" + ",".join(map(str, vector)) + "]"
                sql = "INSERT INTO image_vectors (image_name, description, embedding) VALUES (%s, %s, %s)"
                cursor.execute(sql, (filename, description, vector_str))
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
    
    print(f"\n🔍 Mencari gambar untuk kueri: '{search_query}'")
    
    try:
        # 1. Ubah kueri pencarian menjadi vektor
        embed_payload = {"model": EMBED_MODEL, "prompt": search_query}
        res_embed = requests.post(f"{OLLAMA_API}/embeddings", json=embed_payload).json()
        query_vector = "[" + ",".join(map(str, res_embed['embedding'])) + "]"
        
        # 2. Cari di TiDB menggunakan VEC_COSINE_DISTANCE
        # Semakin kecil nilainya (mendekati 0), semakin mirip jarak vektornya.
        sql = """
            SELECT 
                image_name, 
                description, 
                VEC_COSINE_DISTANCE(embedding, %s) as distance 
            FROM image_vectors 
            ORDER BY distance ASC 
            LIMIT %s
        """
        cursor.execute(sql, (query_vector, limit))
        results = cursor.fetchall()
        
        print("\n--- Hasil Pencarian Teratas ---")
        for idx, row in enumerate(results, 1):
            print(f"{idx}. 📸 File: {row[0]} (Skor Kedekatan: {row[2]:.4f})")
            print(f"   💡 Deskripsi: {row[1]}\n")
            
    except Exception as e:
        print(f"❌ Error saat pencarian: {e}")
        
    finally:
        conn.close()

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