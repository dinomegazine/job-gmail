from app import get_db, generate_password_hash
with get_db() as conn:
    # Bikin akun admin: username=admin, password=rahasia123
    conn.execute("INSERT INTO users (username, password, role) VALUES (?, ?, ?)", 
                 ("admin", generate_password_hash("rahasia123"), "admin"))
    conn.commit()
print("Admin berhasil dibuat!")