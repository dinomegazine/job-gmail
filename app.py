from flask import Flask, render_template, request, redirect, url_for, session, flash, send_from_directory
import sqlite3
import datetime
import os
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = 'ganti_dengan_kunci_rahasia_kamu_123'

# KONFIGURASI SESI: Ingat login selama 30 hari
app.config['PERMANENT_SESSION_LIFETIME'] = datetime.timedelta(days=30)

DATABASE = 'database.db'

def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            password TEXT,
            saldo INTEGER DEFAULT 0,
            role TEXT DEFAULT 'worker'
        )''')
        conn.execute('''CREATE TABLE IF NOT EXISTS tugas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT,
            password TEXT,
            email_pemulihan TEXT,
            status TEXT DEFAULT 'tersedia', 
            worker_id INTEGER DEFAULT NULL,
            tanggal TEXT,
            waktu_diambil TEXT DEFAULT NULL
        )''')
        conn.execute('''CREATE TABLE IF NOT EXISTS penarikan (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            jumlah INTEGER,
            metode TEXT,
            nomor_tujuan TEXT,
            status TEXT DEFAULT 'pending',
            tanggal TEXT,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )''')
        conn.commit()

def cek_timeout_tugas():
    with get_db() as conn:
        tugas_diambil = conn.execute("SELECT id, waktu_diambil FROM tugas WHERE status = 'diambil' AND waktu_diambil IS NOT NULL").fetchall()
        now = datetime.datetime.now()
        for t in tugas_diambil:
            waktu_ambil = datetime.datetime.strptime(t['waktu_diambil'], "%Y-%m-%d %H:%M:%S")
            selisih_menit = (now - waktu_ambil).total_seconds() / 60
            if selisih_menit > 30:
                conn.execute("UPDATE tugas SET status = 'tersedia', worker_id = NULL, waktu_diambil = NULL WHERE id = ?", (t['id'],))
        conn.commit()

# --- RUTE MANIFEST PWA ---
@app.route('/manifest.json')
def manifest():
    return send_from_directory('static', 'manifest.json')

@app.route('/sw.js')
def sw():
    return send_from_directory('static', 'sw.js')

# --- AUTENTIKASI WORKER ---
@app.route('/')
def index(): return redirect(url_for('login'))

@app.route('/auth', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        with get_db() as conn:
            user = conn.execute("SELECT * FROM users WHERE username = ? AND role = 'worker'", (username,)).fetchone()
        if user and check_password_hash(user['password'], password):
            session['user_id'] = user['id']
            session['role'] = 'worker'
            return redirect(url_for('dashboard'))
        else:
            flash('Username atau Password salah!', 'error')
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        try:
            with get_db() as conn:
                conn.execute("INSERT INTO users (username, password) VALUES (?, ?)", (username, generate_password_hash(password)))
                conn.commit()
            flash('Pendaftaran berhasil, silakan login.', 'success')
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            flash('Username sudah dipakai!', 'error')
    return render_template('register.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# --- DASHBOARD WORKER ---
@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session or session.get('role') != 'worker': 
        return redirect(url_for('login'))
    cek_timeout_tugas()
    with get_db() as conn:
        user = conn.execute("SELECT * FROM users WHERE id = ?", (session['user_id'],)).fetchone()
        tersedia = conn.execute("SELECT * FROM tugas WHERE status = 'tersedia' ORDER BY id ASC").fetchall()
        tugas_saya = conn.execute("SELECT * FROM tugas WHERE worker_id = ? AND status != 'selesai' ORDER BY id DESC", (session['user_id'],)).fetchall()
        riwayat_tarik = conn.execute("SELECT * FROM penarikan WHERE user_id = ? ORDER BY id DESC", (session['user_id'],)).fetchall()
    return render_template('dashboard.html', user=user, tersedia=tersedia, saya=tugas_saya, riwayat_tarik=riwayat_tarik)

@app.route('/ambil/<int:id>')
def ambil_tugas(id):
    if 'user_id' not in session: return redirect(url_for('login'))
    cek_timeout_tugas()
    with get_db() as conn:
        tugas = conn.execute("SELECT * FROM tugas WHERE id = ? AND status = 'tersedia'", (id,)).fetchone()
        if tugas:
            now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            conn.execute("UPDATE tugas SET status = 'diambil', worker_id = ?, waktu_diambil = ? WHERE id = ?", (session['user_id'], now, id))
            conn.commit()
            flash('Tugas berhasil diambil! Waktu kamu 30 menit.', 'success')
        else:
            flash('Gagal! Tugas ini sudah diambil worker lain.', 'error')
    return redirect(url_for('dashboard'))

@app.route('/selesai/<int:id>')
def selesai_tugas(id):
    if 'user_id' not in session: return redirect(url_for('login'))
    with get_db() as conn:
        tugas = conn.execute("SELECT * FROM tugas WHERE id = ? AND worker_id = ? AND status = 'diambil'", (id, session['user_id'])).fetchone()
        if tugas:
            conn.execute("UPDATE tugas SET status = 'menunggu_verifikasi' WHERE id = ?", (id,))
            conn.commit()
            flash('Tugas ditandai selesai. Tunggu verifikasi Admin.', 'success')
    return redirect(url_for('dashboard'))

@app.route('/tarik-saldo', methods=['POST'])
def tarik_saldo():
    if 'user_id' not in session: return redirect(url_for('login'))
    jumlah = int(request.form['jumlah'])
    metode = request.form['metode']
    nomor = request.form['nomor_tujuan']
    with get_db() as conn:
        user = conn.execute("SELECT * FROM users WHERE id = ?", (session['user_id'],)).fetchone()
        if jumlah < 5000:
            flash('Gagal! Minimal penarikan adalah Rp 5.000.', 'error')
        elif user['saldo'] < jumlah:
            flash('Gagal! Saldo kamu tidak cukup untuk melakukan penarikan ini.', 'error')
        else:
            now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            conn.execute("UPDATE users SET saldo = saldo - ? WHERE id = ?", (jumlah, session['user_id']))
            conn.execute("INSERT INTO penarikan (user_id, jumlah, metode, nomor_tujuan, tanggal) VALUES (?, ?, ?, ?, ?)",
                         (session['user_id'], jumlah, metode, nomor, now))
            conn.commit()
            flash('Pengajuan penarikan berhasil! Tunggu admin memproses transfer.', 'success')
    return redirect(url_for('dashboard'))

# --- AUTENTIKASI & PANEL ADMIN ---
@app.route('/admin-login', methods=['GET', 'POST'])
def admin_login():
    if session.get('role') == 'admin':
        return redirect(url_for('admin_panel'))

    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        with get_db() as conn:
            user = conn.execute("SELECT * FROM users WHERE username = ? AND role = 'admin'", (username,)).fetchone()
        if user and check_password_hash(user['password'], password):
            session.permanent = True
            session['user_id'] = user['id']
            session['role'] = 'admin'
            return redirect(url_for('admin_panel'))
        else:
            flash('Akses Ditolak! Ini halaman khusus Admin.', 'error')
    return render_template('admin_login.html')

@app.route('/admin-panel', methods=['GET', 'POST'])
def admin_panel():
    if session.get('role') != 'admin': return redirect(url_for('admin_login'))
    cek_timeout_tugas()
    if request.method == 'POST':
        email = request.form['email']
        pw = request.form['password']
        pemulihan = request.form['pemulihan']
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with get_db() as conn:
            conn.execute("INSERT INTO tugas (email, password, email_pemulihan, tanggal) VALUES (?, ?, ?, ?)", (email, pw, pemulihan, now))
            conn.commit()
        flash('Data Tugas ditambahkan!', 'success')
        return redirect(url_for('admin_panel'))
    with get_db() as conn:
        semua_tugas = conn.execute('''SELECT t.*, u.username FROM tugas t 
                                      LEFT JOIN users u ON t.worker_id = u.id 
                                      ORDER BY t.id DESC''').fetchall()
        penarikan_pending = conn.execute('''SELECT p.*, u.username FROM penarikan p 
                                            JOIN users u ON p.user_id = u.id 
                                            WHERE p.status = 'pending' ORDER BY p.id DESC''').fetchall()
    return render_template('admin.html', data=semua_tugas, penarikan=penarikan_pending)

@app.route('/admin-approve/<int:id>')
def approve(id):
    if session.get('role') != 'admin': return redirect(url_for('admin_login'))
    with get_db() as conn:
        tugas = conn.execute("SELECT * FROM tugas WHERE id = ?", (id,)).fetchone()
        if tugas and tugas['status'] == 'menunggu_verifikasi':
            conn.execute("UPDATE tugas SET status = 'selesai' WHERE id = ?", (id,))
            conn.execute("UPDATE users SET saldo = saldo + 1000 WHERE id = ?", (tugas['worker_id'],))
            conn.commit()
    return redirect(url_for('admin_panel'))

@app.route('/admin-reject/<int:id>')
def reject(id):
    if session.get('role') != 'admin': return redirect(url_for('admin_login'))
    with get_db() as conn:
        conn.execute("UPDATE tugas SET status = 'tersedia', worker_id = NULL, waktu_diambil = NULL WHERE id = ?", (id,))
        conn.commit()
    return redirect(url_for('admin_panel'))

@app.route('/admin-selesai-tarik/<int:id>')
def selesai_tarik(id):
    if session.get('role') != 'admin': return redirect(url_for('admin_login'))
    with get_db() as conn:
        conn.execute("UPDATE penarikan SET status = 'selesai' WHERE id = ?", (id,))
        conn.commit()
        flash('Penarikan selesai.', 'success')
    return redirect(url_for('admin_panel'))

if __name__ == '__main__':
    init_db()
    # Botkeep/Docker butuh host 0.0.0.0 dan port dinamis
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)